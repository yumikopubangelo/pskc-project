# ============================================================
# PSKC — Predictor Module
# ML-based key prediction engine
# ============================================================
import asyncio
import time
from typing import Dict, List, Optional, Tuple, Any
import logging

from src.ml.data_collector import get_data_collector
from src.ml.feature_engineering import get_feature_engineer
from src.ml.model import EnsembleModel
from src.ml.model_registry import SecurityError, get_model_registry
from src.auth.key_fetcher import get_key_fetcher
from config.settings import settings

logger = logging.getLogger(__name__)


class KeyPredictor:
    """
    Predicts which keys will be needed next.
    Uses ML model to generate Top-N predictions for pre-caching.
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
            
            # Get model predictions
            if self._model and hasattr(self._model, 'predict_top_n'):
                raw_predictions, probs = self._model.predict_top_n(
                    n=n,
                    X_rf=X.reshape(1, -1),
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
        """Get prediction statistics"""
        return {
            "top_n": self._top_n,
            "threshold": self._threshold,
            "cache_size": len(self._prediction_cache),
            "collector_stats": self._collector.get_stats(),
            "model_loaded": bool(self._model and getattr(self._model, "is_trained", False)),
            "model_source": self._model_source,
            "model_version": self._model_version,
            "artifact_path": self._artifact_path,
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
