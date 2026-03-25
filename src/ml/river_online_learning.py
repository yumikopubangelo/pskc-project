# ============================================================
# PSKC - River Online Learning Module
# True online learning integration using River library
# ============================================================

import inspect
import logging
from collections import deque
from typing import Any, Dict

import numpy as np

logger = logging.getLogger(__name__)

# Try to import River - optional dependency
RIVER_AVAILABLE = False
try:
    import river
    from river import compose, ensemble, linear_model, metrics, preprocessing, tree

    RIVER_AVAILABLE = True
except ImportError:
    logger.warning("River not available - using fallback online learning")
    river = None


def is_river_available() -> bool:
    """Compatibility helper used by predictor/trainer code."""
    return bool(RIVER_AVAILABLE)


class RiverOnlineLearner:
    """
    River-based online learning for true incremental updates.

    Supports:
    - Adaptive forest via Streaming Random Patches
    - Hoeffding Tree
    - Logistic Regression
    """

    def __init__(
        self,
        model_type: str = "adaptive_forest",
        max_depth: int = 5,
        n_models: int = 5,
        drift_threshold: float = 0.5,
        grace_period: int = 200,
        max_size: int = 1000,
    ):
        self.model_type = model_type
        self.max_depth = max_depth
        self.n_models = n_models
        self.drift_threshold = drift_threshold
        self.grace_period = grace_period
        self.max_size = max_size

        self._model = None
        self._accuracy = metrics.Accuracy() if RIVER_AVAILABLE else None
        self._initialized = False
        self._sample_count = 0
        self._recent_predictions = deque(maxlen=100)
        self._drift_detector = None

        if RIVER_AVAILABLE:
            try:
                self._drift_detector = river.drift.detectors.ADWIN()
            except Exception:
                self._drift_detector = None

        self._setup_model()

    def _instantiate_with_supported_kwargs(self, factory, **kwargs):
        try:
            signature = inspect.signature(factory)
            supported_kwargs = {
                key: value
                for key, value in kwargs.items()
                if key in signature.parameters
            }
        except (TypeError, ValueError):
            supported_kwargs = kwargs
        return factory(**supported_kwargs)

    def _setup_model(self):
        """Initialize the River model based on the installed River version."""
        if not RIVER_AVAILABLE:
            logger.warning("River not available, using fallback")
            self._model = None
            self._initialized = False
            return

        try:
            if self.model_type == "adaptive_forest":
                self._model = self._instantiate_with_supported_kwargs(
                    ensemble.SRPClassifier,
                    n_models=self.n_models,
                    max_depth=self.max_depth,
                    grace_period=self.grace_period,
                    seed=42,
                )
                logger.info("Initialized SRPClassifier (Streaming Random Patches)")

            elif self.model_type == "hoeffding_tree":
                self._model = self._instantiate_with_supported_kwargs(
                    tree.HoeffdingTreeClassifier,
                    max_depth=self.max_depth,
                    grace_period=self.grace_period,
                    split_confidence=0.01,
                    seed=42,
                )
                logger.info("Initialized Hoeffding Tree")

            elif self.model_type == "logistic":
                logistic_model = self._instantiate_with_supported_kwargs(
                    linear_model.LogisticRegression,
                    optimizer=river.optim.SGD(lr=0.01),
                    loss="log",
                )
                self._model = compose.Pipeline(
                    preprocessing.StandardScaler(),
                    logistic_model,
                )
                logger.info("Initialized Logistic Regression")

            else:
                self._model = self._instantiate_with_supported_kwargs(
                    ensemble.SRPClassifier,
                    n_models=self.n_models,
                    max_depth=self.max_depth,
                    seed=42,
                )
                logger.info("Initialized default SRPClassifier")

            self._initialized = self._model is not None
        except Exception as exc:
            logger.error(f"Failed to setup River model: {exc}")
            self._model = None
            self._initialized = False

    def partial_fit(self, X: np.ndarray, y: np.ndarray) -> None:
        """Incrementally train on new data."""
        if not self._initialized or self._model is None:
            return

        try:
            if len(X.shape) == 1:
                X = X.reshape(1, -1)
            if isinstance(y, list):
                y = np.array(y)

            for i in range(len(X)):
                sample_x = X[i]
                sample_y = y[i] if isinstance(y, np.ndarray) else y
                x_dict = {f"feat_{j}": float(v) for j, v in enumerate(sample_x)}
                self._model.learn_one(x_dict, sample_y)
                self._sample_count += 1

                if self._drift_detector is not None:
                    pred = self._model.predict_one(x_dict)
                    drift_signal = 1.0 if pred == sample_y else 0.0
                    change_detected = self._drift_detector.update(drift_signal)
                    if change_detected:
                        logger.warning("Concept drift detected by River ADWIN")

        except Exception as exc:
            logger.error(f"Error in partial_fit: {exc}")

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Make predictions on new data."""
        if not self._initialized or self._model is None:
            return np.array([])

        try:
            if len(X.shape) == 1:
                X = X.reshape(1, -1)

            predictions = []
            for sample_x in X:
                x_dict = {f"feat_{j}": float(v) for j, v in enumerate(sample_x)}
                pred = self._model.predict_one(x_dict)
                predictions.append(pred)
                self._recent_predictions.append(pred)

            return np.array(predictions)
        except Exception as exc:
            logger.error(f"Error in predict: {exc}")
            return np.array([])

    def predict_proba(self, X: np.ndarray, n_classes: int = 10) -> np.ndarray:
        """Get prediction probabilities."""
        if not self._initialized or self._model is None:
            return np.array([])

        try:
            if len(X.shape) == 1:
                X = X.reshape(1, -1)

            probabilities = []
            for sample_x in X:
                x_dict = {f"feat_{j}": float(v) for j, v in enumerate(sample_x)}
                try:
                    proba = self._model.predict_proba_one(x_dict)
                    proba_arr = [proba.get(i, 0.0) for i in range(n_classes)]
                    probabilities.append(proba_arr)
                except Exception:
                    probabilities.append([0.0] * n_classes)

            return np.array(probabilities)
        except Exception as exc:
            logger.error(f"Error in predict_proba: {exc}")
            return np.array([])

    def get_stats(self) -> Dict[str, Any]:
        """Get learner statistics."""
        return {
            "initialized": self._initialized,
            "model_type": self.model_type,
            "sample_count": self._sample_count,
            "model": str(type(self._model).__name__) if self._model else None,
            "recent_predictions_count": len(self._recent_predictions),
        }

    def reset(self) -> None:
        """Reset the model."""
        self._setup_model()
        self._sample_count = 0
        self._recent_predictions.clear()
        if RIVER_AVAILABLE:
            try:
                self._drift_detector = river.drift.detectors.ADWIN()
            except Exception:
                self._drift_detector = None


class RiverEnsemble:
    """
    Ensemble combining River online learning with existing PSKC models.
    """

    def __init__(
        self,
        river_weight: float = 0.4,
        rf_weight: float = 0.4,
        markov_weight: float = 0.2,
    ):
        self.river_weight = river_weight
        self.rf_weight = rf_weight
        self.markov_weight = markov_weight
        self._river_learner = RiverOnlineLearner(model_type="adaptive_forest")
        self._rf_model = None
        self._markov_model = None

        logger.info(
            "RiverEnsemble initialized: river=%s, rf=%s, markov=%s",
            river_weight,
            rf_weight,
            markov_weight,
        )

    def set_rf_model(self, rf_model) -> None:
        self._rf_model = rf_model

    def set_markov_model(self, markov_model) -> None:
        self._markov_model = markov_model

    def partial_fit(self, X: np.ndarray, y: np.ndarray) -> None:
        self._river_learner.partial_fit(X, y)
        if self._rf_model is not None and hasattr(self._rf_model, "partial_fit"):
            try:
                self._rf_model.partial_fit(X, y)
            except Exception as exc:
                logger.debug(f"RF partial_fit not available: {exc}")

    def predict(self, X: np.ndarray) -> np.ndarray:
        river_pred = self._river_learner.predict(X)

        rf_pred = np.array([])
        if self._rf_model is not None:
            try:
                rf_pred = self._rf_model.predict(X)
            except Exception:
                rf_pred = np.array([])

        if len(river_pred) > 0:
            return river_pred
        if len(rf_pred) > 0:
            return rf_pred
        return np.array([])
