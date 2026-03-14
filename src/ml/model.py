# ============================================================
# PSKC — Model Architecture Module (IMPROVED)
# LSTM + Random Forest + Markov Chain Ensemble
#
# IMPROVEMENTS:
#   1. Dynamic ensemble weight adjustment — bobot LSTM vs RF berubah
#      otomatis berdasarkan performa masing-masing di sliding window
#      terakhir. Sebelumnya hardcoded 0.6/0.4 selamanya.
#   2. Markov Chain sebagai predictor ke-3 — ringan, tidak butuh training,
#      langsung efektif bahkan di cold start. Menangkap sequential
#      dependency yang sederhana tapi sangat powerful untuk key access.
#   3. EnsembleWeightTracker — modul terpisah yang melacak per-model
#      accuracy di sliding window, lalu update bobot secara softmax.
# ============================================================
import numpy as np
from collections import defaultdict, deque
from typing import Dict, List, Optional, Tuple, Any
import logging

logger = logging.getLogger(__name__)

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    logger.warning("PyTorch not available, LSTM model disabled")

try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import LabelEncoder
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.warning("scikit-learn not available, Random Forest disabled")


# ============================================================
# Markov Chain Predictor (NEW — Predictor ke-3)
# ============================================================

class MarkovChainPredictor:
    """
    First-order Markov Chain untuk prediksi sequential key access.

    KENAPA MARKOV CHAIN:
    - Bekerja dari request pertama (no cold start problem)
    - O(1) prediction, sangat ringan
    - Menangkap pola "setelah key A selalu diakses key B"
      yang sulit ditangkap RF (stateless) maupun LSTM (butuh data banyak)
    - Complementary dengan LSTM dan RF, bukan competing

    Model: P(next_key | current_key) = count(current→next) / count(current→*)
    Menggunakan Laplace smoothing untuk key yang belum pernah dilihat.
    """

    def __init__(
        self,
        num_classes: int = 100,
        smoothing: float = 0.1,
        max_history: int = 10_000,
    ):
        self.num_classes = num_classes
        self.smoothing = smoothing
        self.max_history = max_history

        # transition_counts[from_key][to_key] = count
        self._transition_counts: Dict[str, Dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        self._key_index: Dict[str, int] = {}  # key_id → class index
        self._index_key: Dict[int, str] = {}  # class index → key_id
        self._history: deque = deque(maxlen=max_history)
        self._last_key: Optional[str] = None

    def update(self, key_id: str) -> None:
        """Record a new access event and update transition counts."""
        # Register key if new
        if key_id not in self._key_index:
            idx = len(self._key_index)
            self._key_index[key_id] = idx
            self._index_key[idx] = key_id

        # Update transition
        if self._last_key is not None:
            self._transition_counts[self._last_key][key_id] += 1

        self._history.append(key_id)
        self._last_key = key_id

    def predict_proba_from_key(self, current_key: str) -> np.ndarray:
        """
        Return probability distribution over all known keys
        given the current key was just accessed.

        Returns:
            Array of shape (num_known_keys,) with probabilities.
            Keys ordered by self._key_index.
        """
        n_known = len(self._key_index)
        if n_known == 0:
            return np.array([])

        probs = np.full(n_known, self.smoothing)  # Laplace smoothing baseline

        if current_key in self._transition_counts:
            for to_key, count in self._transition_counts[current_key].items():
                if to_key in self._key_index:
                    probs[self._key_index[to_key]] += count

        # Normalize
        total = probs.sum()
        if total > 0:
            probs /= total

        return probs

    def predict_top_n(self, current_key: str, n: int = 10) -> List[Tuple[str, float]]:
        """
        Return top-N predicted next keys with probabilities.

        Returns:
            List of (key_id, probability) sorted by probability desc.
        """
        probs = self.predict_proba_from_key(current_key)
        if len(probs) == 0:
            return []

        top_indices = np.argsort(probs)[::-1][:n]
        return [
            (self._index_key[idx], float(probs[idx]))
            for idx in top_indices
            if idx in self._index_key
        ]

    def get_known_keys(self) -> List[str]:
        return list(self._key_index.keys())

    @property
    def n_transitions(self) -> int:
        return sum(
            sum(v.values()) for v in self._transition_counts.values()
        )


# ============================================================
# Dynamic Ensemble Weight Tracker (NEW)
# ============================================================

class EnsembleWeightTracker:
    """
    Melacak akurasi per-model di sliding window dan update bobot ensemble.

    SEBELUMNYA: bobot LSTM=0.6, RF=0.4 hardcoded — tidak pernah berubah
    meskipun kondisi berubah (misal LSTM lebih baik di peak traffic tapi
    RF lebih baik di normal traffic).

    SEKARANG: bobot dihitung ulang tiap `update_every` prediksi menggunakan
    softmax dari recent accuracy. Model yang lebih akurat mendapat bobot
    lebih tinggi secara otomatis.

    Mekanisme:
        score_i = hits_i / (hits_i + misses_i) dalam window terakhir
        weight_i = softmax(score_i * temperature)
    """

    def __init__(
        self,
        model_names: List[str],
        window_size: int = 200,
        update_every: int = 50,
        temperature: float = 3.0,
        min_weight: float = 0.05,
    ):
        self.model_names = model_names
        self.window_size = window_size
        self.update_every = update_every
        self.temperature = temperature
        self.min_weight = min_weight

        n = len(model_names)
        # Start with equal weights
        self._weights: Dict[str, float] = {name: 1.0 / n for name in model_names}

        # Per-model rolling accuracy window: deque of 0/1 (miss/hit)
        self._windows: Dict[str, deque] = {
            name: deque(maxlen=window_size) for name in model_names
        }
        self._step = 0

        logger.info(
            f"EnsembleWeightTracker initialized: models={model_names}, "
            f"window={window_size}, update_every={update_every}"
        )

    def record(self, model_name: str, correct: bool) -> None:
        """Record a prediction outcome for a model."""
        if model_name not in self._windows:
            return
        self._windows[model_name].append(1 if correct else 0)
        self._step += 1

        if self._step % self.update_every == 0:
            self._recompute_weights()

    def _recompute_weights(self) -> None:
        """Recompute weights using softmax of recent accuracies."""
        scores = {}
        for name in self.model_names:
            window = self._windows[name]
            if len(window) < 10:
                # Not enough data yet — keep equal weight
                scores[name] = 1.0 / len(self.model_names)
            else:
                scores[name] = sum(window) / len(window)

        # Softmax with temperature
        vals = np.array([scores[n] for n in self.model_names])
        exp_vals = np.exp(vals * self.temperature)
        softmax_weights = exp_vals / exp_vals.sum()

        # Apply minimum weight floor
        softmax_weights = np.maximum(softmax_weights, self.min_weight)
        softmax_weights /= softmax_weights.sum()  # Re-normalize after floor

        for i, name in enumerate(self.model_names):
            self._weights[name] = float(softmax_weights[i])

        logger.debug(
            f"Ensemble weights updated: "
            + ", ".join(f"{n}={w:.3f}" for n, w in self._weights.items())
        )

    def get_weight(self, model_name: str) -> float:
        return self._weights.get(model_name, 0.0)

    def get_all_weights(self) -> Dict[str, float]:
        return dict(self._weights)

    def get_accuracy(self, model_name: str) -> Optional[float]:
        window = self._windows.get(model_name, deque())
        if len(window) < 5:
            return None
        return sum(window) / len(window)


# ============================================================
# LSTM Model (unchanged architecture, improved integration)
# ============================================================

class LSTMModel(nn.Module if TORCH_AVAILABLE else object):
    """LSTM model for sequence-based key prediction."""

    def __init__(
        self,
        input_size: int = 30,
        hidden_size: int = 64,
        num_layers: int = 2,
        num_classes: int = 100,
        dropout: float = 0.2,
    ):
        if not TORCH_AVAILABLE:
            return
        super().__init__()
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0,
        )
        self.fc1 = nn.Linear(hidden_size, hidden_size // 2)
        self.relu = nn.ReLU()
        self.dropout = nn.Dropout(dropout)
        self.fc2 = nn.Linear(hidden_size // 2, num_classes)

    def forward(self, x):
        if len(x.shape) == 2:
            x = x.unsqueeze(1)
        lstm_out, _ = self.lstm(x)
        last_output = lstm_out[:, -1, :]
        out = self.fc1(last_output)
        out = self.relu(out)
        out = self.dropout(out)
        out = self.fc2(out)
        return out

    def predict_proba(self, x):
        if not TORCH_AVAILABLE:
            return None
        self.eval()
        with torch.no_grad():
            logits = self.forward(x)
            probs = torch.softmax(logits, dim=1)
        return probs.numpy()


# ============================================================
# Random Forest Model (unchanged)
# ============================================================

class RandomForestModel:
    """Random Forest model for feature-based key prediction."""

    def __init__(
        self,
        n_estimators: int = 100,
        max_depth: int = 10,
        num_classes: int = 100,
    ):
        if not SKLEARN_AVAILABLE:
            return
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.num_classes = num_classes
        self.model = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            random_state=42,
            n_jobs=-1,
        )
        self.label_encoder = LabelEncoder()
        self.is_trained = False

    def fit(self, X: np.ndarray, y: np.ndarray):
        if not SKLEARN_AVAILABLE:
            return
        y_encoded = self.label_encoder.fit_transform(y)
        self.model.fit(X, y_encoded)
        self.is_trained = True
        logger.info(f"RandomForest trained on {len(X)} samples")

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not SKLEARN_AVAILABLE or not self.is_trained:
            return None
        return self.model.predict_proba(X)

    def predict(self, X: np.ndarray) -> np.ndarray:
        if not SKLEARN_AVAILABLE or not self.is_trained:
            return None
        return self.model.predict(X)


# ============================================================
# Ensemble Model (IMPROVED)
# ============================================================

class EnsembleModel:
    """
    Ensemble of LSTM + Random Forest + Markov Chain.

    Perubahan utama vs sebelumnya:
    - Bobot tidak lagi hardcoded — dikelola oleh EnsembleWeightTracker
    - Markov Chain ditambahkan sebagai predictor ke-3
    - Markov Chain diupdate otomatis saat record_outcome() dipanggil
    - Method record_outcome() untuk feedback loop akurasi per model
    """

    def __init__(
        self,
        lstm_weight: float = 0.5,
        rf_weight: float = 0.35,
        markov_weight: float = 0.15,
        num_classes: int = 100,
        dynamic_weights: bool = True,
    ):
        self.num_classes = num_classes
        self.dynamic_weights = dynamic_weights

        # Sub-models
        self.lstm = LSTMModel(num_classes=num_classes) if TORCH_AVAILABLE else None
        self.rf = RandomForestModel(num_classes=num_classes) if SKLEARN_AVAILABLE else None
        self.markov = MarkovChainPredictor(num_classes=num_classes)

        # Dynamic weight tracker
        self._weight_tracker = EnsembleWeightTracker(
            model_names=["lstm", "rf", "markov"],
            window_size=200,
            update_every=50,
        )
        # Seed with initial weights
        # (tracker starts equal, but we nudge it toward config values via temp)
        self._static_weights = {
            "lstm":   lstm_weight,
            "rf":     rf_weight,
            "markov": markov_weight,
        }

        self.is_trained = False
        logger.info(
            f"EnsembleModel initialized: "
            f"LSTM={lstm_weight}, RF={rf_weight}, Markov={markov_weight}, "
            f"dynamic_weights={dynamic_weights}"
        )

    # ----------------------------------------------------------
    # Training
    # ----------------------------------------------------------

    def fit(
        self,
        X_lstm: np.ndarray = None,
        y_lstm: np.ndarray = None,
        X_rf: np.ndarray = None,
        y_rf: np.ndarray = None,
        access_sequence: List[str] = None,  # For Markov Chain update
    ):
        """Train all sub-models."""
        if TORCH_AVAILABLE and X_lstm is not None and y_lstm is not None:
            self._train_lstm(X_lstm, y_lstm)

        if SKLEARN_AVAILABLE and X_rf is not None and y_rf is not None:
            self._train_rf(X_rf, y_rf)

        # Feed access sequence to Markov Chain
        if access_sequence:
            for key_id in access_sequence:
                self.markov.update(key_id)
            logger.info(
                f"Markov Chain updated: {self.markov.n_transitions} transitions tracked"
            )

        self.is_trained = True

    def _train_lstm(self, X: np.ndarray, y: np.ndarray):
        if not TORCH_AVAILABLE:
            return
        X_tensor = torch.FloatTensor(X)
        y_tensor = torch.LongTensor(y)
        dataset = TensorDataset(X_tensor, y_tensor)
        loader = DataLoader(dataset, batch_size=32, shuffle=True)
        self.lstm.train()
        criterion = nn.CrossEntropyLoss()
        optimizer = torch.optim.Adam(self.lstm.parameters(), lr=0.001)
        for epoch in range(10):
            total_loss = 0
            for batch_X, batch_y in loader:
                optimizer.zero_grad()
                outputs = self.lstm(batch_X)
                loss = criterion(outputs, batch_y)
                loss.backward()
                optimizer.step()
                total_loss += loss.item()
            logger.debug(f"LSTM Epoch {epoch+1}/10, Loss: {total_loss/len(loader):.4f}")
        logger.info("LSTM training completed")

    def _train_rf(self, X: np.ndarray, y: np.ndarray):
        if not SKLEARN_AVAILABLE:
            return
        self.rf.fit(X, y)

    # ----------------------------------------------------------
    # Prediction
    # ----------------------------------------------------------

    def _get_weights(self) -> Dict[str, float]:
        """Get current ensemble weights (dynamic or static)."""
        if self.dynamic_weights:
            w = self._weight_tracker.get_all_weights()
            # If tracker hasn't seen enough data yet, blend with static
            lstm_acc = self._weight_tracker.get_accuracy("lstm")
            if lstm_acc is None:
                return self._static_weights
            return w
        return self._static_weights

    def predict_proba(
        self,
        X_lstm: np.ndarray = None,
        X_rf: np.ndarray = None,
        current_key: str = None,  # For Markov Chain
    ) -> np.ndarray:
        """
        Get weighted ensemble probability distribution.

        Args:
            X_lstm: Feature array for LSTM
            X_rf: Feature array for RF
            current_key: Last accessed key (for Markov prediction)

        Returns:
            Combined probability array, or None if no model ready.
        """
        weights = self._get_weights()
        contributions = []

        # --- LSTM ---
        if TORCH_AVAILABLE and self.lstm is not None and X_lstm is not None:
            lstm_probs = self.lstm.predict_proba(
                torch.FloatTensor(X_lstm) if not isinstance(X_lstm, torch.Tensor) else X_lstm
            )
            if lstm_probs is not None:
                contributions.append(("lstm", lstm_probs, weights["lstm"]))

        # --- Random Forest ---
        if (
            self.rf is not None
            and getattr(self.rf, "is_trained", False)
            and X_rf is not None
            and hasattr(self.rf, "predict_proba")
        ):
            rf_probs = self.rf.predict_proba(X_rf)
            if rf_probs is not None:
                contributions.append(("rf", rf_probs, weights["rf"]))

        # --- Markov Chain ---
        if current_key is not None and len(self.markov.get_known_keys()) > 0:
            markov_probs = self.markov.predict_proba_from_key(current_key)
            if len(markov_probs) > 0:
                # Markov probs are over known_keys; pad/align to num_classes
                full_probs = np.zeros((1, self.num_classes))
                n = min(len(markov_probs), self.num_classes)
                full_probs[0, :n] = markov_probs[:n]
                contributions.append(("markov", full_probs, weights["markov"]))

        if not contributions:
            return None

        # Align all to same number of classes
        min_classes = min(p.shape[-1] for _, p, _ in contributions)
        combined = np.zeros((1, min_classes))
        total_w = sum(w for _, _, w in contributions)

        for name, probs, w in contributions:
            if len(probs.shape) == 1:
                probs = probs.reshape(1, -1)
            combined += (w / total_w) * probs[:, :min_classes]

        # Normalize
        row_sums = combined.sum(axis=1, keepdims=True)
        combined = np.where(row_sums > 0, combined / row_sums, combined)

        return combined

    def predict_top_n(
        self,
        n: int = 10,
        X_lstm: np.ndarray = None,
        X_rf: np.ndarray = None,
        current_key: str = None,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Get top N predicted class indices and their probabilities."""
        probs = self.predict_proba(X_lstm, X_rf, current_key)

        if probs is None:
            # Fallback: use Markov only if available
            if current_key and len(self.markov.get_known_keys()) > 0:
                top = self.markov.predict_top_n(current_key, n=n)
                if top:
                    keys = [k for k, _ in top]
                    p = np.array([prob for _, prob in top])
                    return np.array(keys), p
            return np.array([]), np.array([])

        top_indices = np.argsort(probs[0])[::-1][:n]
        top_probs = probs[0][top_indices]
        return top_indices, top_probs

    # ----------------------------------------------------------
    # Feedback Loop (for dynamic weights)
    # ----------------------------------------------------------

    def record_outcome(
        self,
        model_name: str,
        predicted_key: str,
        actual_key: str,
    ) -> None:
        """
        Record whether a model's prediction was correct.
        Called after each real access to enable dynamic weight updates.

        Args:
            model_name: "lstm" | "rf" | "markov"
            predicted_key: Key the model predicted would be accessed next
            actual_key: Key that was actually accessed
        """
        correct = predicted_key == actual_key
        self._weight_tracker.record(model_name, correct)

        # Always update Markov Chain with real access
        self.markov.update(actual_key)

    # ----------------------------------------------------------
    # Diagnostics
    # ----------------------------------------------------------

    def get_model_stats(self) -> Dict[str, Any]:
        """Return current model stats for monitoring/debugging."""
        weights = self._get_weights()
        return {
            "is_trained": self.is_trained,
            "dynamic_weights": self.dynamic_weights,
            "current_weights": weights,
            "per_model_accuracy": {
                name: self._weight_tracker.get_accuracy(name)
                for name in ["lstm", "rf", "markov"]
            },
            "markov_transitions": self.markov.n_transitions,
            "markov_known_keys": len(self.markov.get_known_keys()),
        }


# ============================================================
# Model Factory
# ============================================================

class ModelFactory:
    """Factory for creating model instances."""

    @staticmethod
    def create_model(model_type: str = "ensemble", **kwargs) -> Any:
        if model_type == "lstm" and TORCH_AVAILABLE:
            return LSTMModel(**kwargs)
        elif model_type == "rf" and SKLEARN_AVAILABLE:
            return RandomForestModel(**kwargs)
        elif model_type == "markov":
            return MarkovChainPredictor(**kwargs)
        elif model_type == "ensemble":
            return EnsembleModel(**kwargs)
        else:
            raise ValueError(f"Unknown model type: {model_type}")
