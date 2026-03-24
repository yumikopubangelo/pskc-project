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
import time

from config.settings import settings

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
        smoothing: float = None,
        max_history: int = None,
        max_transitions: int = None,
    ):
        self.num_classes = num_classes
        self.smoothing = smoothing if smoothing is not None else settings.ml_markov_smoothing
        self.max_history = max_history if max_history is not None else settings.ml_markov_max_history
        self.max_transitions = max_transitions if max_transitions is not None else settings.ml_markov_max_transitions
        
        # transition_counts[from_key][to_key] = count
        self._transition_counts: Dict[str, Dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        self._key_index: Dict[str, int] = {}  # key_id → class index
        self._index_key: Dict[int, str] = {}  # class index → key_id
        self._history: deque = deque(maxlen=max_history)
        self._last_key: Optional[str] = None
        self._total_transitions: int = 0  # Track total for bounds enforcement

    def update(self, key_id: str) -> None:
        """
        Record a new access event and update transition counts.
        Enforces max_transitions limit to prevent unbounded memory growth.
        """
        # Register key if new
        if key_id not in self._key_index:
            idx = len(self._key_index)
            self._key_index[key_id] = idx
            self._index_key[idx] = key_id

        # Update transition with bounds checking
        if self._last_key is not None:
            self._transition_counts[self._last_key][key_id] += 1
            self._total_transitions += 1
            
            # If exceeding max_transitions, prune old entries
            if self._total_transitions > self.max_transitions:
                self._prune_transitions()

        self._history.append(key_id)
        self._last_key = key_id

    def _prune_transitions(self) -> None:
        """
        Prune transition counts to stay within max_transitions limit.
        Removes lowest-count transitions first.
        """
        total = 0
        for source_dict in self._transition_counts.values():
            total += sum(source_dict.values())
        
        if total <= self.max_transitions:
            return
        
        # Create list of (count, source_key, dest_key) sorted by count ascending
        transitions_list: List[Tuple[int, str, str]] = []
        for source_key, destinations in self._transition_counts.items():
            for dest_key, count in destinations.items():
                transitions_list.append((count, source_key, dest_key))
        
        transitions_list.sort()
        
        # Remove lowest count transitions until under limit
        target_size = int(self.max_transitions * 0.8)  # Prune to 80% to reduce churn
        removed = 0
        for count, source_key, dest_key in transitions_list:
            if total <= target_size:
                break
            del self._transition_counts[source_key][dest_key]
            total -= count
            removed += 1
        
        self._total_transitions = total
        logger.debug(f"Markov: Pruned {removed} transitions, total now: {total}")

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
        return self._total_transitions


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
        window_size: int = None,
        update_every: int = None,
        temperature: float = None,
        min_weight: float = None,
    ):
        self.model_names = model_names
        self.window_size = window_size if window_size is not None else settings.ml_ensemble_window_size
        self.update_every = update_every if update_every is not None else settings.ml_ensemble_update_every
        self.temperature = temperature if temperature is not None else settings.ml_ensemble_temperature
        self.min_weight = min_weight if min_weight is not None else settings.ml_ensemble_min_weight

        n = len(model_names)
        # Start with equal weights
        self._weights: Dict[str, float] = {name: 1.0 / n for name in model_names}

        # Per-model rolling accuracy window: deque of 0/1 (miss/hit)
        self._windows: Dict[str, deque] = {
            name: deque(maxlen=self.window_size) for name in model_names
        }
        self._step = 0

        logger.info(
            f"EnsembleWeightTracker initialized: models={model_names}, "
            f"window={self.window_size}, update_every={self.update_every}"
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
    """
    LSTM model for sequence-based key prediction.
    
    Improvements:
    - Configurable hyperparameters via settings
    - Learning rate scheduling with ReduceLROnPlateau
    - Early stopping with patience and min_delta
    - Validation loss tracking  
    """

    def __init__(
        self,
        input_size: int = None,
        hidden_size: int = None,
        num_layers: int = None,
        num_classes: int = 100,
        dropout: float = None,
    ):
        if not TORCH_AVAILABLE:
            return

        super().__init__()

        # Use config defaults if not provided
        input_size = input_size if input_size is not None else settings.ml_lstm_input_size
        hidden_size = hidden_size if hidden_size is not None else settings.ml_lstm_hidden_size
        num_layers = num_layers if num_layers is not None else settings.ml_lstm_num_layers
        dropout = dropout if dropout is not None else settings.ml_lstm_dropout

        self.input_size = input_size
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

        # Label encoder for training
        if SKLEARN_AVAILABLE:
            self.label_encoder = LabelEncoder()
        else:
            self.label_encoder = None

        # Training state
        self.is_trained = False
        self._last_training_epochs = 0
        self._training_history = {"loss": [], "val_loss": []}

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
    """
    Random Forest model for feature-based key prediction.
    
    Improvements:
    - Configurable hyperparameters via settings
    - Class weight balancing for imbalanced data
    - Feature importance tracking
    """

    def __init__(
        self,
        n_estimators: int = None,
        max_depth: int = None,
        min_samples_split: int = None,
        min_samples_leaf: int = None,
        num_classes: int = 100,
        use_class_weight: bool = None,
    ):
        if not SKLEARN_AVAILABLE:
            return
        
        # Use config defaults if not provided
        n_estimators = n_estimators if n_estimators is not None else settings.ml_rf_n_estimators
        max_depth = max_depth if max_depth is not None else settings.ml_rf_max_depth
        min_samples_split = min_samples_split if min_samples_split is not None else settings.ml_rf_min_samples_split
        min_samples_leaf = min_samples_leaf if min_samples_leaf is not None else settings.ml_rf_min_samples_leaf
        use_class_weight = use_class_weight if use_class_weight is not None else settings.ml_rf_use_class_weight
        
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.num_classes = num_classes
        self.use_class_weight = use_class_weight
        
        # class_weight="balanced" addresses label imbalance (Issue #6)
        class_weight = "balanced" if use_class_weight else None
        
        self.model = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            min_samples_split=min_samples_split,
            min_samples_leaf=min_samples_leaf,
            class_weight=class_weight,
            random_state=settings.ml_rf_random_state,
            n_jobs=settings.ml_rf_n_jobs,
        )
        self.label_encoder = LabelEncoder()
        self.is_trained = False
        self._feature_importances = None

    def fit(self, X: np.ndarray, y: np.ndarray):
        if not SKLEARN_AVAILABLE:
            return
        y_encoded = self.label_encoder.fit_transform(y)
        self.model.fit(X, y_encoded)
        self.is_trained = True
        
        # Track feature importances for monitoring (Issue #5)
        self._feature_importances = self.model.feature_importances_
        
        logger.info(
            f"RandomForest trained: n_estimators={self.n_estimators}, "
            f"max_depth={self.max_depth}, samples={len(X)}, classes={len(self.label_encoder.classes_)}"
        )

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not SKLEARN_AVAILABLE or not self.is_trained:
            return None
        return self.model.predict_proba(X)

    def predict(self, X: np.ndarray) -> np.ndarray:
        if not SKLEARN_AVAILABLE or not self.is_trained:
            return None
        return self.model.predict(X)
    
    def get_feature_importances(self) -> Optional[np.ndarray]:
        """Return feature importances for debugging/monitoring."""
        return self._feature_importances if self.is_trained else None
    
    def log_feature_importances(self, feature_names: List[str] = None):
        """Log top feature importances for inspection."""
        if self._feature_importances is None:
            return
        
        importances = self._feature_importances
        if feature_names is None:
            feature_names = [f"feature_{i}" for i in range(len(importances))]
        
        # Top 10 features
        top_indices = np.argsort(importances)[::-1][:10]
        top_features = [
            (feature_names[i] if i < len(feature_names) else f"feature_{i}", float(importances[i]))
            for i in top_indices
        ]
        
        logger.info(
            "RandomForest top features: " +
            ", ".join(f"{name}={imp:.4f}" for name, imp in top_features)
        )


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
        lstm_weight: float = None,
        rf_weight: float = None,
        markov_weight: float = None,
        num_classes: int = 100,
        dynamic_weights: bool = None,
    ):
        self.num_classes = num_classes
        
        # Use config defaults if not provided
        lstm_weight = lstm_weight if lstm_weight is not None else settings.ml_ensemble_lstm_weight
        rf_weight = rf_weight if rf_weight is not None else settings.ml_ensemble_rf_weight
        markov_weight = markov_weight if markov_weight is not None else settings.ml_ensemble_markov_weight
        dynamic_weights = dynamic_weights if dynamic_weights is not None else settings.ml_ensemble_dynamic_weights
        
        self.dynamic_weights = dynamic_weights

        # Sub-models
        self.lstm = LSTMModel(input_size=8, num_classes=num_classes) if TORCH_AVAILABLE else None  # Sequential input: 8 features per event
        self.rf = RandomForestModel(num_classes=num_classes) if SKLEARN_AVAILABLE else None
        self.markov = MarkovChainPredictor(num_classes=num_classes)

        # Dynamic weight tracker
        self._weight_tracker = EnsembleWeightTracker(
            model_names=["lstm", "rf", "markov"],
        )
        # Seed with initial weights
        self._static_weights = {
            "lstm":   lstm_weight,
            "rf":     rf_weight,
            "markov": markov_weight,
        }

        self.is_trained = False
        logger.info(
            f"EnsembleModel initialized: "
            f"LSTM={lstm_weight:.2f}, RF={rf_weight:.2f}, Markov={markov_weight:.2f}, "
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
        if TORCH_AVAILABLE and self.lstm is not None and X_lstm is not None and y_lstm is not None:
            self._train_lstm(X_lstm, y_lstm)

        if SKLEARN_AVAILABLE and self.rf is not None and X_rf is not None and y_rf is not None:
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
        """
        Train LSTM with improvements:
        - Learning rate scheduling
        - Early stopping with patience
        - Validation monitoring
        - Adaptive epochs (configurable, not fixed to 10)
        """
        if not TORCH_AVAILABLE or self.lstm is None:
            return
        
        try:
            # Config parameters
            batch_size = settings.ml_lstm_batch_size
            max_epochs = settings.ml_lstm_max_epochs
            learning_rate = settings.ml_lstm_learning_rate
            patience = settings.ml_lstm_early_stopping_patience
            min_delta = settings.ml_lstm_early_stopping_min_delta
            use_lr_scheduler = settings.ml_lstm_use_lr_scheduler
            
            # Encode labels
            if self.lstm and self.lstm.label_encoder is not None:
                y_encoded = self.lstm.label_encoder.fit_transform(y)
            else:
                # Fallback: simple mapping
                unique_keys = list(set(y))
                key_to_idx = {k: i for i, k in enumerate(unique_keys)}
                y_encoded = [key_to_idx[k] for k in y]

            # Prepare dataset with validation split
            X_tensor = torch.FloatTensor(X)
            y_tensor = torch.LongTensor(y_encoded)
            dataset = TensorDataset(X_tensor, y_tensor)
            
            # 80/20 train/val split
            val_size = int(0.2 * len(dataset))
            train_size = len(dataset) - val_size
            train_dataset, val_dataset = torch.utils.data.random_split(
                dataset, [train_size, val_size]
            )
            
            train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
            val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)
            
            self.lstm.train()
            criterion = nn.CrossEntropyLoss()
            optimizer = torch.optim.Adam(self.lstm.parameters(), lr=learning_rate)
            
            # Learning rate scheduler (if enabled)
            scheduler = None
            if use_lr_scheduler:
                scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
                    optimizer,
                    mode='min',
                    factor=settings.ml_lstm_lr_scheduler_factor,
                    patience=settings.ml_lstm_lr_scheduler_patience,
                    verbose=False
                )
            
            # Early stopping tracking
            best_val_loss = float('inf')
            patience_counter = 0
            
            for epoch in range(max_epochs):
                # Training phase
                train_loss = 0.0
                for batch_X, batch_y in train_loader:
                    optimizer.zero_grad()
                    outputs = self.lstm(batch_X)
                    loss = criterion(outputs, batch_y)
                    loss.backward()
                    optimizer.step()
                    train_loss += loss.item()
                
                avg_train_loss = train_loss / len(train_loader)
                
                # Validation phase
                val_loss = 0.0
                self.lstm.eval()
                with torch.no_grad():
                    for batch_X, batch_y in val_loader:
                        outputs = self.lstm(batch_X)
                        loss = criterion(outputs, batch_y)
                        val_loss += loss.item()
                
                avg_val_loss = val_loss / len(val_loader)
                
                # Track history
                self.lstm._training_history["loss"].append(avg_train_loss)
                self.lstm._training_history["val_loss"].append(avg_val_loss)
                
                logger.debug(
                    f"LSTM Epoch {epoch+1}/{max_epochs}, "
                    f"Loss: {avg_train_loss:.4f}, Val Loss: {avg_val_loss:.4f}"
                )
                
                # Learning rate scheduling
                if scheduler:
                    scheduler.step(avg_val_loss)
                
                # Early stopping check
                if avg_val_loss < best_val_loss - min_delta:
                    best_val_loss = avg_val_loss
                    patience_counter = 0
                else:
                    patience_counter += 1
                    if patience_counter >= patience:
                        logger.info(
                            f"LSTM early stopping at epoch {epoch+1} "
                            f"(val_loss: {avg_val_loss:.4f})"
                        )
                        break
                
                self.lstm.train()
            
            self.lstm.is_trained = True
            self.lstm._last_training_epochs = epoch + 1
            
            logger.info(
                f"LSTM training completed: {epoch + 1} epochs, "
                f"final val_loss: {avg_val_loss:.4f}"
            )
        
        except Exception as e:
            logger.error(f"LSTM training failed: {e}", exc_info=True)
            if self.lstm:
                self.lstm.is_trained = False

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
        probs = self.predict_proba(X_lstm=X_lstm, X_rf=X_rf, current_key=current_key)

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
