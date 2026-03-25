# ============================================================
# PSKC — Predictor Module
# ML-based key prediction engine with EWMA + Markov ensemble
# ============================================================
import asyncio
import threading
import time
from typing import Dict, List, Optional, Tuple, Any
import logging

from src.ml.data_collector import get_data_collector
from src.ml.feature_engineering import get_feature_engineer
from src.ml.model import EnsembleModel
from src.ml.model_registry import SecurityError, get_model_registry
from src.ml.algorithm_improvements import EWMACalculator, DriftDetector, DynamicMarkovChain
from src.ml.river_online_learning import RiverOnlineLearner, is_river_available
from src.auth.key_fetcher import get_key_fetcher
from config.settings import settings

logger = logging.getLogger(__name__)

# Ensemble weights for confidence blending
_W_SHORT_EWMA = 0.40
_W_LONG_EWMA = 0.30
_W_MARKOV = 0.30

# Drift-triggered retrain cooldown (seconds)
_DRIFT_RETRAIN_COOLDOWN = 300


class KeyPredictor:
    """
    Predicts which keys will be needed next.
    Uses ML model + EWMA trend + DynamicMarkovChain ensemble.
    """

    def __init__(
        self,
        model: EnsembleModel = None,
        top_n: int = None,
        threshold: float = None
    ):
        from config.settings import settings

        self._model = model
        self._top_n = top_n if top_n is not None else settings.ml_predictor_top_n
        self._threshold = threshold if threshold is not None else settings.ml_predictor_confidence_threshold

        # Cache configuration
        self._cache_ttl = settings.ml_predictor_cache_ttl_seconds
        self._cache_max_size = settings.ml_predictor_cache_max_size

        # Components
        self._collector = get_data_collector()
        self._engineer = get_feature_engineer()

        # For getting key data
        self._key_fetcher = get_key_fetcher()

        # Prediction cache with eviction support (Issue #15)
        self._prediction_cache = {}
        self._model_source = "uninitialized"
        self._model_version: Optional[str] = None
        self._artifact_path: Optional[str] = None

        # --- EWMA + Markov + Drift ensemble components ---
        self._ewma = EWMACalculator(alpha_short=0.3, alpha_long=0.1, window_size=200)
        self._drift = DriftDetector(
            short_window=30,
            long_window=200,
            drift_threshold=0.3,
            warning_threshold=0.15,
        )
        self._markov = DynamicMarkovChain(states=[], window_size=200, decay_factor=0.95)
        self._last_key_by_service: Dict[str, str] = {}
        self._last_drift_retrain_time = 0.0
        self._outcome_count = 0

        # River online learner — lightweight drift-triggered learning
        # (separate from scheduled full retraining)
        self._river_learner: Optional[RiverOnlineLearner] = None
        self._river_learn_count = 0
        if is_river_available():
            self._river_learner = RiverOnlineLearner(model_type="adaptive_forest")
            logger.info("River online learner initialized for drift-based adaptation")

        if model is not None:
            self.attach_model(model, source="runtime")

        logger.info(
            f"KeyPredictor initialized: top_n={self._top_n}, "
            f"threshold={self._threshold}, cache_ttl={self._cache_ttl}s"
        )

    @property
    def model(self) -> EnsembleModel:
        return self._model

    @model.setter
    def model(self, value: EnsembleModel):
        self._model = value
        self._prediction_cache.clear()
        if value is None:
            self._model_source = "uninitialized"
            self._model_version = None
            self._artifact_path = None

    def _evict_old_cache_entries(self):
        """
        Evict expired cache entries (Issue #15).
        Called periodically to prevent unbounded cache growth.
        """
        now = time.time()
        keys_to_delete = []

        # Find expired entries
        for cache_key, (cached_time, _) in self._prediction_cache.items():
            if now - cached_time > self._cache_ttl:
                keys_to_delete.append(cache_key)

        # Delete expired entries
        for key in keys_to_delete:
            del self._prediction_cache[key]

        # If still over max size, remove oldest entries
        if len(self._prediction_cache) > self._cache_max_size:
            num_to_remove = len(self._prediction_cache) - int(self._cache_max_size * 0.8)
            # Sort by timestamp and remove oldest
            sorted_items = sorted(
                self._prediction_cache.items(),
                key=lambda x: x[1][0]  # Sort by cache time
            )
            for cache_key, _ in sorted_items[:num_to_remove]:
                del self._prediction_cache[cache_key]

            logger.debug(f"Predictor: Evicted {num_to_remove} cache entries, now at {len(self._prediction_cache)}")

    def attach_model(
        self,
        model: Optional[EnsembleModel],
        source: str = "runtime",
        version: Optional[str] = None,
        artifact_path: Optional[str] = None,
    ) -> None:
        self.model = model
        self._model_source = source if model is not None else "uninitialized"
        self._model_version = version
        self._artifact_path = artifact_path

    def load_active_model(self, model_name: Optional[str] = None) -> bool:
        effective_model_name = model_name or settings.ml_model_name
        registry = get_model_registry()
        active_version = registry.get_active_version(effective_model_name)
        if active_version is None:
            return False

        loaded_model = registry.load_model(effective_model_name, actor="predictor")
        if loaded_model is None:
            return False

        self.attach_model(
            loaded_model,
            source="registry",
            version=active_version.version,
            artifact_path=active_version.file_path,
        )
        return True

    def ensure_model_loaded(self, model_name: Optional[str] = None) -> bool:
        if self._model is not None and getattr(self._model, "is_trained", False):
            return True
        return self.load_active_model(model_name=model_name)

    def _decode_predicted_key(self, raw_prediction: Any) -> Optional[str]:
        """Map model output back to a concrete key identifier."""
        if isinstance(raw_prediction, str):
            return raw_prediction

        if isinstance(raw_prediction, (int, float)):
            index = int(raw_prediction)

            rf_model = getattr(self._model, "rf", None)
            label_encoder = getattr(rf_model, "label_encoder", None)
            classes = getattr(label_encoder, "classes_", None)
            if classes is not None and 0 <= index < len(classes):
                return str(classes[index])

            markov_model = getattr(self._model, "markov", None)
            known_keys = markov_model.get_known_keys() if markov_model is not None else []
            if 0 <= index < len(known_keys):
                return str(known_keys[index])

        return None

    def _is_suspicious_pattern(self, access_data: List[Dict], min_events: int = 20, suspicious_ratio: float = 0.1) -> bool:
        """
        Detects if access patterns are suspicious (potential poisoning attempt).
        A low ratio of unique keys to total access events can indicate an
        attacker trying to inflate the importance of a few keys.
        """
        if not access_data or len(access_data) < min_events:
            return False

        unique_key_ids = {d['key_id'] for d in access_data if 'key_id' in d}
        ratio = len(unique_key_ids) / len(access_data)

        if ratio < suspicious_ratio:
            logger.warning(
                f"Suspicious access pattern detected. "
                f"Ratio of unique keys to events is {ratio:.2f} ({len(unique_key_ids)} unique keys "
                f"in {len(access_data)} events), which is below the threshold of {suspicious_ratio}. "
                f"This could indicate a cache poisoning attempt. Aborting prediction."
            )
            return True

        return False

    # ----------------------------------------------------------
    # Confidence enhancement via EWMA + Markov ensemble
    # ----------------------------------------------------------

    def _enhance_confidence(
        self,
        predictions: List[Tuple[str, float]],
        current_key: Optional[str],
        service_id: str,
    ) -> List[Tuple[str, float]]:
        """
        Adjust prediction confidence using EWMA trends and Markov chain.

        Blending weights:
          40% short-EWMA trend signal
          30% long-EWMA baseline signal
          30% DynamicMarkovChain transition probability
        """
        if not predictions:
            return predictions

        # Get Markov transition probabilities from current_key
        markov_probs: Dict[str, float] = {}
        if current_key:
            markov_probs = self._markov.get_transition_probability(service_id, current_key)

        enhanced: List[Tuple[str, float]] = []
        for key_id, base_conf in predictions:
            # EWMA signals for this key
            short_ewma, long_ewma = self._ewma.get(key_id)
            trend = self._ewma.get_trend(key_id)

            # EWMA-based multiplier: boost if trending up, dampen if down
            if short_ewma is not None and long_ewma is not None:
                short_signal = min(short_ewma, 1.0)
                long_signal = min(long_ewma, 1.0)
            else:
                short_signal = 0.5
                long_signal = 0.5

            # Markov signal
            markov_signal = markov_probs.get(key_id, 0.0)

            # Blend: weighted combination as adjustment factor
            ensemble_signal = (
                _W_SHORT_EWMA * short_signal
                + _W_LONG_EWMA * long_signal
                + _W_MARKOV * markov_signal
            )

            # Trend-based confidence adjustment
            if trend == "increasing":
                trend_boost = 1.10
            elif trend == "decreasing":
                trend_boost = 0.90
            else:
                trend_boost = 1.0

            # Final confidence: base model confidence adjusted by ensemble + trend
            # ensemble_signal acts as a multiplier centered around 0.5
            adjustment = 0.5 + ensemble_signal  # range ~[0.5, 1.5]
            adjusted_conf = base_conf * adjustment * trend_boost
            enhanced.append((key_id, min(max(adjusted_conf, 0.0), 1.0)))

        # Re-sort by adjusted confidence
        enhanced.sort(key=lambda x: x[1], reverse=True)
        return enhanced

    # ----------------------------------------------------------
    # Outcome recording (feedback loop)
    # ----------------------------------------------------------

    def record_outcome(
        self,
        service_id: str,
        actual_key: str,
        predicted_keys: List[str],
        cache_hit: bool = False,
    ) -> Dict[str, Any]:
        """
        Record the actual key that was accessed after a prediction.
        Updates EWMA, Markov, and drift detector.  Triggers retrain if drift detected.

        Args:
            service_id: Service identifier
            actual_key: The key that was actually accessed
            predicted_keys: The keys that were predicted (ordered)
            cache_hit: Whether the access was a cache hit

        Returns:
            Dict with outcome analysis
        """
        self._outcome_count += 1
        is_correct = actual_key in predicted_keys[:10] if predicted_keys else False
        is_top1 = predicted_keys[0] == actual_key if predicted_keys else False

        # Update EWMA with access frequency signal (1.0 = accessed)
        self._ewma.update(actual_key, 1.0)

        # Decay EWMA for keys NOT accessed (lazy — only for predicted keys)
        for pk in predicted_keys[:10]:
            if pk != actual_key:
                current_short, _ = self._ewma.get(pk)
                if current_short is not None:
                    self._ewma.update(pk, 0.0)

        # Update DynamicMarkovChain
        prev_key = self._last_key_by_service.get(service_id)
        if prev_key and actual_key:
            # Dynamically add states
            self._markov.states.add(prev_key)
            self._markov.states.add(actual_key)
            self._markov.observe(service_id, prev_key, actual_key)
        self._last_key_by_service[service_id] = actual_key

        # Update drift detector with prediction correctness
        drift_result = self._drift.update("global", 1.0 if is_correct else 0.0)
        drift_score = drift_result.get("drift_score", 0.0)
        drift_level = drift_result.get("drift_level", "normal")

        # Trigger retrain if critical drift detected
        retrain_triggered = False
        if drift_level == "critical":
            retrain_triggered = self._try_drift_retrain()

        # Persist to DB (best-effort, non-blocking)
        self._persist_outcome(service_id, actual_key, predicted_keys, is_correct, cache_hit)

        return {
            "is_correct": is_correct,
            "is_top1": is_top1,
            "drift_score": drift_score,
            "drift_level": drift_level,
            "retrain_triggered": retrain_triggered,
            "outcome_count": self._outcome_count,
        }

    def _try_drift_retrain(self) -> bool:
        """
        Handle drift via River online learning (lightweight, non-blocking).
        Does NOT trigger full scheduled training — those two paths are separate:
          - Drift → River partial_fit on recent data (fast, incremental)
          - Scheduled → Full retrain with new model version (heavy, periodic)
        """
        now = time.time()
        if now - self._last_drift_retrain_time < _DRIFT_RETRAIN_COOLDOWN:
            return False

        self._last_drift_retrain_time = now

        if self._river_learner is None:
            logger.debug("River not available, skipping drift adaptation")
            return False

        try:
            # Get recent events from data collector for online learning
            import numpy as np
            recent_data = self._collector.get_access_sequence(
                window_seconds=600,   # Last 10 minutes
                max_events=500,       # Small batch — fast
            )
            if len(recent_data) < 10:
                return False

            # Extract features and labels
            X_features = []
            y_labels = []
            for idx in range(1, len(recent_data)):
                context = recent_data[max(0, idx - 10):idx + 1]
                features = self._engineer.extract_features(context)
                X_features.append(features)
                y_labels.append(recent_data[idx]["key_id"])

            if not X_features:
                return False

            X = np.array(X_features)
            y = np.array(y_labels)

            # River partial_fit — true incremental, no version bump
            self._river_learner.partial_fit(X, y)
            self._river_learn_count += len(X)

            logger.info(
                f"River online learning: processed {len(X)} samples "
                f"(total: {self._river_learn_count})"
            )
            return True

        except Exception as e:
            logger.error(f"River drift adaptation failed: {e}")
            return False

    def _persist_outcome(
        self,
        service_id: str,
        actual_key: str,
        predicted_keys: List[str],
        is_correct: bool,
        cache_hit: bool,
    ) -> None:
        """Best-effort persistence of prediction outcome to database."""
        try:
            from src.observability.enhanced_observability import get_observability_service
            obs = get_observability_service()
            if obs is None:
                return

            top_pred = predicted_keys[0] if predicted_keys else ""
            confidence = None  # Not available in this context

            obs.record_prediction(
                version_id=0,  # Will use active version
                key=actual_key,
                predicted_value=top_pred,
                actual_value=actual_key,
                confidence=confidence,
            )
            obs.record_cache_operation(actual_key, cache_hit)
            obs.record_drift(actual_key, is_correct)
        except Exception as e:
            logger.debug(f"Outcome persistence skipped: {e}")

    # ----------------------------------------------------------
    # Main prediction
    # ----------------------------------------------------------

    def predict(
        self,
        service_id: str = "default",
        n: int = None,
        min_confidence: Optional[float] = None,
    ) -> List[Tuple[str, float]]:
        """
        Predict next N keys that will be accessed, with anti-poisoning checks.

        Args:
            service_id: Service to predict for
            n: Number of predictions (uses default if not specified)

        Returns:
            List of (key_id, confidence) tuples, or empty list if suspicious activity is detected.
        """
        n = n or self._top_n
        min_confidence = self._threshold if min_confidence is None else min_confidence
        self.ensure_model_loaded()

        # Check cache with eviction
        cache_key = f"{service_id}:{n}"
        self._evict_old_cache_entries()  # Periodic cleanup

        if cache_key in self._prediction_cache:
            cached_time, cached_predictions = self._prediction_cache[cache_key]
            if time.time() - cached_time < self._cache_ttl:
                logger.debug(f"Prediction cache hit: {cache_key}")
                return cached_predictions

        # Get recent access data
        access_data = self._collector.get_access_sequence(
            window_seconds=300,
            max_events=1000
        )

        # Filter by service if needed
        if service_id != "default":
            access_data = [d for d in access_data if d.get('service_id') == service_id]

        # SECURITY: Check for cache poisoning attempts before prediction.
        if self._is_suspicious_pattern(access_data):
            # If suspicious, return no predictions to avoid poisoning the cache.
            return []

        # Get hot keys as fallback
        hot_keys = self._collector.get_hot_keys(limit=n)

        if not access_data:
            # Return hot keys if no recent data
            predictions = [(key_id, 0.5) for key_id, _ in hot_keys[:n]]
            self._prediction_cache[cache_key] = (time.time(), predictions)
            return predictions

        try:
            # Extract features
            X = self._engineer.extract_features(access_data)
            current_key = access_data[-1].get("key_id") if access_data else None

            # Apply the same preprocessing used during training
            X_rf = X.reshape(1, -1)
            if self._model and hasattr(self._model, 'preprocess_rf'):
                X_rf = self._model.preprocess_rf(X_rf)

            # Get model predictions
            if self._model and hasattr(self._model, 'predict_top_n'):
                raw_predictions, probs = self._model.predict_top_n(
                    n=n,
                    X_rf=X_rf,
                    current_key=current_key,
                )

                predictions = []
                for raw_prediction, prob in zip(raw_predictions, probs):
                    key_id = self._decode_predicted_key(raw_prediction)
                    if key_id:
                        predictions.append((key_id, float(prob)))

                if not predictions:
                    predictions = [(key_id, 1.0 / (i + 1)) for i, (key_id, _) in enumerate(hot_keys[:n])]
            else:
                # Use hot keys as predictions
                predictions = [(key_id, 1.0 / (i + 1)) for i, (key_id, _) in enumerate(hot_keys[:n])]

            # Enhance confidence using EWMA + Markov ensemble
            predictions = self._enhance_confidence(predictions, current_key, service_id)

            # Filter by threshold
            predictions = [(k, p) for k, p in predictions if p >= min_confidence]

            # Cache predictions
            self._prediction_cache[cache_key] = (time.time(), predictions)

            return predictions

        except SecurityError:
            raise
        except Exception as e:
            logger.error(f"Prediction failed: {e}")
            # Fallback to hot keys
            predictions = [(key_id, 1.0 / (i + 1)) for i, (key_id, _) in enumerate(hot_keys[:n])]
            return predictions

    def predict_for_prefetch(
        self,
        service_id: str = "default"
    ) -> Dict[str, Tuple[bytes, float]]:
        """
        Predict keys and fetch them for pre-caching.

        Returns:
            Dict of {key_id: (key_data, priority)}
        """
        predictions = self.predict(service_id)

        prefetch_data = {}
        running_loop = None

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop and running_loop.is_running():
            logger.warning("predict_for_prefetch skipped: called from a running event loop")
            return prefetch_data

        for key_id, priority in predictions:
            try:
                key_data = asyncio.run(self._key_fetcher.fetch_key(key_id, service_id))

                if key_data:
                    prefetch_data[key_id] = (key_data, priority)

            except Exception as e:
                logger.warning(f"Failed to fetch key {key_id} for prefetch: {e}")

        return prefetch_data

    async def prefetch_predictions(
        self,
        service_id: str = "default",
        cache_store = None
    ) -> int:
        """
        Automatically prefetch predicted keys.

        Returns:
            Number of keys prefetched
        """
        try:
            # Get predictions with data
            predictions = self.predict(service_id)

            if cache_store is None:
                logger.warning("Prefetch skipped: no cache store is attached to predictor")
                return 0

            prefetched = 0

            for key_id, priority in predictions:
                # Fetch from KMS
                key_data = await self._key_fetcher.fetch_key(key_id, service_id)

                if key_data:
                    # Cache with priority-based TTL
                    ttl = int(300 * priority)  # Higher priority = longer TTL
                    cache_store.set(key_id, key_data, service_id, ttl)
                    prefetched += 1

            logger.info(f"Prefetched {prefetched} keys for service {service_id}")
            return prefetched

        except Exception as e:
            logger.error(f"Prefetch failed: {e}")
            return 0

    def get_prediction_stats(self) -> Dict[str, Any]:
        """Get prediction statistics including ensemble component health."""
        drift_score = self._drift.get_drift_score("global")
        ewma_keys_tracked = len(self._ewma.ewma_short)
        markov_transitions = sum(
            len(to_states)
            for from_states in self._markov.transitions.values()
            for to_states in from_states.values()
        )

        river_stats = (
            self._river_learner.get_stats()
            if self._river_learner is not None
            else {"initialized": False}
        )

        return {
            "top_n": self._top_n,
            "threshold": self._threshold,
            "cache_size": len(self._prediction_cache),
            "collector_stats": self._collector.get_stats(),
            "model_loaded": bool(self._model and getattr(self._model, "is_trained", False)),
            "model_source": self._model_source,
            "model_version": self._model_version,
            "artifact_path": self._artifact_path,
            "ensemble": {
                "ewma_keys_tracked": ewma_keys_tracked,
                "markov_transitions": markov_transitions,
                "drift_score": round(drift_score, 4),
                "drift_level": self._drift.drift_scores.get("global", 0.0),
                "outcome_count": self._outcome_count,
                "weights": {
                    "short_ewma": _W_SHORT_EWMA,
                    "long_ewma": _W_LONG_EWMA,
                    "markov": _W_MARKOV,
                },
            },
            "river_online": {
                **river_stats,
                "learn_count": self._river_learn_count,
            },
        }

    def clear_cache(self):
        """Clear prediction cache"""
        self._prediction_cache.clear()
        logger.info("Prediction cache cleared")


# Global predictor instance
_predictor_instance: Optional[KeyPredictor] = None


def get_key_predictor() -> KeyPredictor:
    """Get global key predictor"""
    global _predictor_instance
    if _predictor_instance is None:
        _predictor_instance = KeyPredictor(
            top_n=settings.ml_top_n_predictions,
            threshold=settings.ml_prediction_threshold
        )
    return _predictor_instance


def predict_next_keys(service_id: str = "default", n: int = 10) -> List[Tuple[str, float]]:
    """Convenience function for key prediction"""
    return get_key_predictor().predict(service_id, n)
