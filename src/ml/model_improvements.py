# ============================================================
# PSKC — ML Training Improvements Module
# Hyperparameter Tuning, Class Imbalance Handling, Data Augmentation
# ============================================================
import numpy as np
import logging
from typing import Dict, List, Tuple, Optional, Any
from collections import Counter
from datetime import datetime, timedelta
import json

logger = logging.getLogger(__name__)

try:
    from sklearn.preprocessing import StandardScaler
    from sklearn.decomposition import PCA
    from sklearn.feature_selection import SelectKBest, f_classif
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.warning("scikit-learn not available for feature selection")


# ============================================================
# 1. CLASS IMBALANCE HANDLING — SMOTE-like Data Balancing
# ============================================================

class DataBalancer:
    """
    Handles class imbalance by oversampling minority keys
    and undersampling majority keys (SMOTE-inspired approach).
    
    Problem: Popular keys (e.g., key_0) appear 1000x more than rare keys.
    Solution: Balance training samples so every key has roughly same representation.
    """
    
    def __init__(self, target_samples_per_class: int = None):
        self.target_samples_per_class = target_samples_per_class
        self.sampling_history = {}
    
    def balance_dataset(
        self,
        X: np.ndarray,
        y: np.ndarray,
        strategy: str = "auto"
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Balance dataset by adjusting class representation.
        
        Args:
            X: Feature matrix shape (n_samples, n_features)
            y: Labels array shape (n_samples,)
            strategy: "auto" (median class), "oversample" (max class), or int (target count)
            
        Returns:
            Balanced (X, y)
        """
        if not SKLEARN_AVAILABLE:
            logger.warning("Cannot balance without scikit-learn")
            return X, y
        
        unique_classes = np.unique(y)
        class_counts = Counter(y)
        
        if strategy == "auto":
            # Target = median class size
            counts = sorted(class_counts.values())
            target = int(np.median(counts))
        elif strategy == "oversample":
            # Target = max class size
            target = max(class_counts.values())
        elif isinstance(strategy, int):
            target = strategy
        else:
            return X, y
        
        logger.info(f"Balancing dataset: target {target} samples per class")
        
        balanced_X = []
        balanced_y = []
        
        for cls in unique_classes:
            cls_mask = (y == cls)
            cls_X = X[cls_mask]
            cls_y = y[cls_mask]
            
            current_count = len(cls_y)
            
            if current_count < target:
                # Oversample: randomly duplicate samples
                indices = np.random.choice(len(cls_X), size=target, replace=True)
                balanced_X.append(cls_X[indices])
                balanced_y.append(cls_y[indices])
            elif current_count > target:
                # Undersample: randomly select subset
                indices = np.random.choice(len(cls_X), size=target, replace=False)
                balanced_X.append(cls_X[indices])
                balanced_y.append(cls_y[indices])
            else:
                balanced_X.append(cls_X)
                balanced_y.append(cls_y)
            
            self.sampling_history[cls] = {
                "original": current_count,
                "balanced": len(balanced_y[-1])
            }
        
        X_balanced = np.vstack(balanced_X)
        y_balanced = np.hstack(balanced_y)
        
        # Shuffle to mix oversampled/undersampled batches
        shuffle_idx = np.random.permutation(len(y_balanced))
        
        logger.info(f"Dataset balanced: {len(y)} → {len(y_balanced)} samples")
        
        return X_balanced[shuffle_idx], y_balanced[shuffle_idx]


# ============================================================
# 2. FEATURE SELECTION & DIMENSIONALITY REDUCTION
# ============================================================

class FeatureSelector:
    """
    Select most important features to:
    1. Reduce noise from redundant features
    2. Speed up training
    3. Improve generalization
    
    Uses SelectKBest + f_classif to find top features.
    """
    
    def __init__(self, n_features: int = 20):
        self.n_features = n_features
        self.selector = None
        self.feature_scores = None
        self.selected_indices = None
    
    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        """
        Fit feature selector on training data.
        
        Args:
            X: Feature matrix (n_samples, n_features)
            y: Labels (n_samples,)
        """
        if not SKLEARN_AVAILABLE:
            logger.warning("Cannot select features without scikit-learn")
            return
        
        self.selector = SelectKBest(f_classif, k=min(self.n_features, X.shape[1]))
        self.selector.fit(X, y)
        
        # Get feature scores and selected indices
        self.feature_scores = self.selector.scores_
        self.selected_indices = self.selector.get_support(indices=True)
        
        logger.info(f"Selected {len(self.selected_indices)} features")
        logger.debug(f"Feature scores: {self.feature_scores[:10]}")
    
    def transform(self, X: np.ndarray) -> np.ndarray:
        """
        Apply feature selection to data.
        
        Args:
            X: Feature matrix (n_samples, n_features)
            
        Returns:
            Reduced feature matrix (n_samples, k_features)
        """
        if self.selector is None:
            return X
        
        return self.selector.transform(X)
    
    def fit_transform(self, X: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Fit and transform in one step."""
        self.fit(X, y)
        return self.transform(X)
    
    def get_selected_features(self) -> List[int]:
        """Return indices of selected features."""
        return self.selected_indices.tolist() if self.selected_indices is not None else []


# ============================================================
# 3. DATA AUGMENTATION
# ============================================================

class DataAugmenter:
    """
    Augment training data to improve robustness and generalization.
    
    Techniques:
    1. Gaussian noise - simulate measurement errors
    2. Feature scaling variations - simulate different service loads
    3. Time shift augmentation - temporal variations
    4. Mixup - interpolate between samples
    """
    
    def __init__(self, augmentation_factor: float = 0.3):
        self.augmentation_factor = augmentation_factor  # 30% of data augmented
    
    def augment_dataset(
        self,
        X: np.ndarray,
        y: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Apply augmentation to increase training data diversity.
        
        Args:
            X: Feature matrix (n_samples, n_features)
            y: Labels (n_samples,)
            
        Returns:
            Augmented (X, y)
        """
        n_augment = int(len(X) * self.augmentation_factor)

        if n_augment == 0:
            return X, y

        augmented_X = []
        augmented_y = []

        # Randomly select samples to augment
        indices = np.random.choice(len(X), size=n_augment, replace=True)
        
        for idx in indices:
            aug_type = np.random.choice(['noise', 'scale', 'mixup'])
            
            if aug_type == 'noise':
                X_aug = self._augment_with_noise(X[idx])
            elif aug_type == 'scale':
                X_aug = self._augment_with_scaling(X[idx])
            else:  # mixup
                other_idx = np.random.choice(len(X))
                X_aug = self._augment_with_mixup(X[idx], X[other_idx])
            
            augmented_X.append(X_aug)
            augmented_y.append(y[idx])
        
        # Combine original and augmented
        X_combined = np.vstack([X, np.array(augmented_X)])
        y_combined = np.hstack([y, np.array(augmented_y)])
        
        logger.info(f"Data augmented: {len(X)} → {len(X_combined)} samples")
        
        return X_combined, y_combined
    
    def _augment_with_noise(self, x: np.ndarray, noise_std: float = 0.05) -> np.ndarray:
        """Add Gaussian noise to features."""
        noise = np.random.normal(0, noise_std, size=x.shape)
        return x + noise
    
    def _augment_with_scaling(self, x: np.ndarray, scale_range: float = 0.2) -> np.ndarray:
        """Scale features by random factor (simulates load variations)."""
        scale = np.random.uniform(1 - scale_range, 1 + scale_range)
        return x * scale
    
    def _augment_with_mixup(
        self,
        x1: np.ndarray,
        x2: np.ndarray,
        alpha: float = 0.2
    ) -> np.ndarray:
        """Mixup: interpolate between two samples."""
        lam = np.random.beta(alpha, alpha)
        return lam * x1 + (1 - lam) * x2


# ============================================================
# 4. HYPERPARAMETER TUNING
# ============================================================

class HyperparameterTuner:
    """
    Simple grid-search based hyperparameter tuning.
    Tests different configurations and returns best.
    """
    
    def __init__(self):
        self.tuning_results = []
    
    def suggest_hyperparameters(
        self,
        data_size: int,
        num_keys: int,
        training_time_budget: float = 300.0
    ) -> Dict[str, Any]:
        """
        Suggest hyperparameters based on data characteristics.
        
        Args:
            data_size: Number of training samples
            num_keys: Number of unique keys (output classes)
            training_time_budget: Max training time in seconds
            
        Returns:
            Suggested hyperparameters dict
        """
        # Adaptive LSTM size based on data and keys
        if data_size < 1000:
            lstm_hidden = 64
        elif data_size < 10000:
            lstm_hidden = 128
        else:
            lstm_hidden = 256
        
        # Random Forest trees based on data size
        if data_size < 1000:
            rf_trees = 50
        elif data_size < 10000:
            rf_trees = 100
        else:
            rf_trees = 200
        
        # Batch size
        if data_size < 1000:
            batch_size = 32
        else:
            batch_size = 64
        
        # Learning rate (smaller for large datasets)
        if data_size < 5000:
            lr = 0.001
        else:
            lr = 0.0005
        
        # Dropout (higher for larger models to prevent overfitting)
        dropout = 0.3 if lstm_hidden > 128 else 0.2
        
        # Markov smoothing
        markov_smoothing = 0.1
        
        hparams = {
            "lstm": {
                "hidden_size": lstm_hidden,
                "num_layers": 2,
                "batch_size": batch_size,
                "learning_rate": lr,
                "dropout": dropout,
                "weight_decay": 1e-5,
                "epochs": min(50, int(training_time_budget / 2)),
                "early_stopping_patience": 5,
            },
            "random_forest": {
                "n_estimators": rf_trees,
                "max_depth": int(np.log2(num_keys)) + 3,
                "min_samples_split": max(2, int(data_size * 0.001)),
                "min_samples_leaf": max(1, int(data_size * 0.0005)),
                "n_jobs": -1,
            },
            "markov": {
                "smoothing": markov_smoothing,
                "max_transitions": 100000,
            },
            "ensemble": {
                "window_size": 100,
                "temperature": 1.0,
            },
            "training": {
                "validation_split": 0.15,
                "test_split": 0.15,
                "data_balancing": "auto",
                "feature_selection": True,
                "n_selected_features": min(25, int(np.sqrt(data_size))),
                "augmentation_factor": 0.2,
            }
        }
        
        logger.info(f"Suggested hyperparameters for {data_size} samples, {num_keys} keys:")
        logger.info(f"  LSTM: hidden={lstm_hidden}, lr={lr}, dropout={dropout}")
        logger.info(f"  RF: trees={rf_trees}, max_depth={hparams['random_forest']['max_depth']}")
        logger.info(f"  Data: balance={hparams['training']['data_balancing']}, augment={hparams['training']['augmentation_factor']}")
        
        return hparams


# ============================================================
# 5. TRAINING PROGRESS TRACKING
# ============================================================

class TrainingProgressTracker:
    """
    Track training metrics for logging and early stopping.
    """
    
    def __init__(self):
        self.train_loss_history = []
        self.val_loss_history = []
        self.train_accuracy_history = []
        self.val_accuracy_history = []
        self.epoch_times = []
        self.best_val_accuracy = 0.0
        self.best_epoch = 0
        self.early_stop_counter = 0
    
    def add_epoch(
        self,
        train_loss: float,
        val_loss: float,
        train_acc: float,
        val_acc: float,
        epoch_time: float
    ) -> None:
        """Record metrics for one epoch."""
        self.train_loss_history.append(train_loss)
        self.val_loss_history.append(val_loss)
        self.train_accuracy_history.append(train_acc)
        self.val_accuracy_history.append(val_acc)
        self.epoch_times.append(epoch_time)
        
        # Track best validation accuracy
        if val_acc > self.best_val_accuracy:
            self.best_val_accuracy = val_acc
            self.best_epoch = len(self.train_loss_history) - 1
            self.early_stop_counter = 0
        else:
            self.early_stop_counter += 1
    
    def should_stop_early(self, patience: int = 5) -> bool:
        """Check if early stopping criteria met."""
        return self.early_stop_counter >= patience
    
    def get_summary(self) -> Dict[str, Any]:
        """Get training summary."""
        if not self.train_loss_history:
            return {}
        
        return {
            "final_train_loss": self.train_loss_history[-1],
            "final_val_loss": self.val_loss_history[-1],
            "final_train_accuracy": self.train_accuracy_history[-1],
            "final_val_accuracy": self.val_accuracy_history[-1],
            "best_val_accuracy": self.best_val_accuracy,
            "best_epoch": self.best_epoch,
            "total_epochs": len(self.train_loss_history),
            "total_training_time": sum(self.epoch_times),
            "avg_epoch_time": np.mean(self.epoch_times) if self.epoch_times else 0.0,
        }


# ============================================================
# 6. NORMALIZATION & SCALING
# ============================================================

class FeatureNormalizer:
    """
    Normalize features to improve LSTM training stability.
    """
    
    def __init__(self):
        self.scaler = None
    
    def fit(self, X: np.ndarray) -> None:
        """Fit scaler on training data."""
        if not SKLEARN_AVAILABLE:
            logger.warning("Cannot normalize without scikit-learn")
            return
        
        self.scaler = StandardScaler()
        self.scaler.fit(X)
    
    def transform(self, X: np.ndarray) -> np.ndarray:
        """Apply normalization."""
        if self.scaler is None:
            return X
        return self.scaler.transform(X)
    
    def fit_transform(self, X: np.ndarray) -> np.ndarray:
        """Fit and transform in one step."""
        self.fit(X)
        return self.transform(X)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get normalization statistics."""
        if self.scaler is None:
            return {}
        
        return {
            "mean": self.scaler.mean_.tolist() if hasattr(self.scaler.mean_, 'tolist') else self.scaler.mean_,
            "std": self.scaler.scale_.tolist() if hasattr(self.scaler.scale_, 'tolist') else self.scaler.scale_,
        }


# ============================================================
# 7. RF PREPROCESSING PIPELINE
# ============================================================

class RFPreprocessor:
    """
    Encapsulates the full RF feature preprocessing pipeline:
      1. Normalize (StandardScaler)
      2. Drop constant-variance columns
      3. Select top-K features (SelectKBest)

    Fitted during training, then stored with the model so the same
    transformations are applied at prediction time.
    """

    def __init__(self, n_select: int = 25):
        self._n_select = n_select
        # Fitted state
        self._mean: Optional[np.ndarray] = None
        self._scale: Optional[np.ndarray] = None
        self._non_constant_mask: Optional[np.ndarray] = None
        self._selected_indices: Optional[np.ndarray] = None
        self._is_fitted = False

    @property
    def is_fitted(self) -> bool:
        return self._is_fitted

    def get_input_feature_count(self) -> Optional[int]:
        """Return the raw feature width expected before normalization/selection."""
        if self._mean is not None:
            return int(len(self._mean))
        if self._non_constant_mask is not None:
            return int(len(self._non_constant_mask))
        return None

    def _align_input_features(self, X: np.ndarray) -> np.ndarray:
        """
        Align runtime features with the shape used when this preprocessor was fitted.

        This preserves compatibility with older artifacts that were trained before the
        feature vector expanded from 30 to 36 dimensions.
        """
        X_arr = np.atleast_2d(np.asarray(X, dtype=np.float32))
        expected = self.get_input_feature_count()
        if expected is None or X_arr.shape[1] == expected:
            return X_arr

        if X_arr.shape[1] > expected:
            logger.warning(
                "RFPreprocessor: truncating runtime features from %d to %d for legacy artifact compatibility.",
                X_arr.shape[1],
                expected,
            )
            return X_arr[:, :expected]

        logger.warning(
            "RFPreprocessor: padding runtime features from %d to %d for legacy artifact compatibility.",
            X_arr.shape[1],
            expected,
        )
        padded = np.zeros((X_arr.shape[0], expected), dtype=X_arr.dtype)
        padded[:, : X_arr.shape[1]] = X_arr
        return padded

    # ---- fit / transform ----

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        """Fit the full pipeline on training data."""
        # 1. Normalize
        self._mean = np.mean(X, axis=0)
        self._scale = np.std(X, axis=0)
        self._scale[self._scale == 0] = 1.0  # avoid division by zero
        X_norm = (X - self._mean) / self._scale

        # 2. Drop constant columns (post-normalization variance == 0)
        col_var = np.var(X_norm, axis=0)
        self._non_constant_mask = col_var > 0
        if not np.all(self._non_constant_mask):
            logger.warning(
                "RFPreprocessor: dropping %d constant feature(s).",
                int((~self._non_constant_mask).sum()),
            )
        X_reduced = X_norm[:, self._non_constant_mask]

        # 3. Feature selection (SelectKBest)
        k = min(self._n_select, X_reduced.shape[1])
        if SKLEARN_AVAILABLE and k < X_reduced.shape[1]:
            selector = SelectKBest(f_classif, k=k)
            import warnings as _w
            with _w.catch_warnings():
                _w.simplefilter("ignore")
                selector.fit(X_reduced, y)
            self._selected_indices = selector.get_support(indices=True)
        else:
            self._selected_indices = np.arange(X_reduced.shape[1])

        self._is_fitted = True
        logger.info(
            "RFPreprocessor fitted: %d → %d features",
            X.shape[1],
            len(self._selected_indices),
        )

    def transform(self, X: np.ndarray) -> np.ndarray:
        """Apply the fitted pipeline to new data."""
        if not self._is_fitted:
            return X
        X_arr = self._align_input_features(X)
        X_norm = (X_arr - self._mean) / self._scale
        X_reduced = X_norm[:, self._non_constant_mask]
        return X_reduced[:, self._selected_indices]

    def fit_transform(self, X: np.ndarray, y: np.ndarray) -> np.ndarray:
        self.fit(X, y)
        return self.transform(X)

    # ---- serialization (JSON-safe) ----

    def to_dict(self) -> Optional[Dict[str, Any]]:
        if not self._is_fitted:
            return None
        return {
            "n_select": self._n_select,
            "mean": self._mean.tolist(),
            "scale": self._scale.tolist(),
            "non_constant_mask": self._non_constant_mask.tolist(),
            "selected_indices": self._selected_indices.tolist(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RFPreprocessor":
        obj = cls(n_select=data.get("n_select", 25))
        obj._mean = np.array(data["mean"])
        obj._scale = np.array(data["scale"])
        obj._non_constant_mask = np.array(data["non_constant_mask"], dtype=bool)
        obj._selected_indices = np.array(data["selected_indices"], dtype=int)
        obj._is_fitted = True
        return obj

    @classmethod
    def make_passthrough(cls, input_n: int, output_n: int) -> "RFPreprocessor":
        """Construct an identity preprocessor for legacy artifacts.

        Accepts *input_n* raw features and returns the first *output_n* by
        simple truncation — no normalization, no feature selection.  Used when
        a saved model has no stored preprocessor but the RF sub-model records
        how many features it was trained on via ``n_features_in_``.
        """
        obj = cls(n_select=output_n)
        obj._mean = np.zeros(input_n, dtype=np.float32)
        obj._scale = np.ones(input_n, dtype=np.float32)
        obj._non_constant_mask = np.ones(input_n, dtype=bool)
        obj._selected_indices = np.arange(output_n, dtype=int)
        obj._is_fitted = True
        return obj


# ============================================================
# 8. MODEL PERFORMANCE TRACKER
# ============================================================

class PerModelPerformanceTracker:
    """
    Track individual model performance (LSTM, RF, Markov separately)
    to ensure ensemble uses good weights.
    """
    
    def __init__(self, window_size: int = 100):
        self.window_size = window_size
        self.lstm_accuracies = []
        self.rf_accuracies = []
        self.markov_accuracies = []
        self.ensemble_accuracies = []
    
    def add_prediction(
        self,
        lstm_correct: bool,
        rf_correct: bool,
        markov_correct: bool,
        ensemble_correct: bool
    ) -> None:
        """Record prediction correctness for each model."""
        self.lstm_accuracies.append(float(lstm_correct))
        self.rf_accuracies.append(float(rf_correct))
        self.markov_accuracies.append(float(markov_correct))
        self.ensemble_accuracies.append(float(ensemble_correct))
        
        # Keep only recent window
        if len(self.lstm_accuracies) > self.window_size:
            self.lstm_accuracies.pop(0)
            self.rf_accuracies.pop(0)
            self.markov_accuracies.pop(0)
            self.ensemble_accuracies.pop(0)
    
    def get_window_accuracy(self) -> Dict[str, float]:
        """Get accuracy over recent window."""
        if not self.lstm_accuracies:
            return {
                "lstm": 0.0,
                "random_forest": 0.0,
                "markov": 0.0,
                "ensemble": 0.0,
            }
        
        return {
            "lstm": np.mean(self.lstm_accuracies),
            "random_forest": np.mean(self.rf_accuracies),
            "markov": np.mean(self.markov_accuracies),
            "ensemble": np.mean(self.ensemble_accuracies),
        }
    
    def get_report(self) -> Dict[str, Any]:
        """Get detailed performance report."""
        window_acc = self.get_window_accuracy()
        
        return {
            "window_accuracy": window_acc,
            "predictions_evaluated": len(self.lstm_accuracies),
            "lstm_dominant": window_acc["lstm"] == max(window_acc.values()),
            "rf_dominant": window_acc["random_forest"] == max(window_acc.values()),
            "markov_dominant": window_acc["markov"] == max(window_acc.values()),
        }
