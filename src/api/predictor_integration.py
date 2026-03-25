# ============================================================
# PSKC — Predictor Integration Wrapper
# ============================================================
"""
Integration untuk predictor/route_keys.py:
- Record setiap prediction dengan metrics
- Update drift detection
- Track cache operations
- Use algorithms untuk boost confidence

Drop-in integration tanpa mengubah existing prediction logic.
"""

import logging
import time
from typing import Optional, Tuple
from src.ml.trainer_integration import get_trainer_integration

logger = logging.getLogger(__name__)


class PredictorIntegration:
    """
    Lightweight integration untuk prediction endpoints.
    
    Usage dalam route_keys.py:
    ```python
    predictor_int = PredictorIntegration()
    
    # Sebelum prediction:
    start_time = time.time()
    
    # Make prediction (existing code)
    predicted_value = model.predict(cache_key)
    confidence = model.confidence
    
    # Setelah prediction:
    latency_ms = (time.time() - start_time) * 1000
    predictor_int.record_and_enhance(
        key=cache_key,
        predicted_value=predicted_value,
        confidence=confidence,
        latency_ms=latency_ms,
        actual_value=actual_from_cache  # Set later when available
    )
    
    # Get enhanced prediction with algorithms
    enhanced_confidence = predictor_int.get_enhanced_confidence(cache_key, confidence)
    ```
    """
    
    def __init__(self):
        """Initialize predictor integration."""
        self.trainer_int = get_trainer_integration()
    
    def record_and_enhance(
        self,
        key: str,
        predicted_value: str,
        confidence: float = 0.5,
        latency_ms: Optional[float] = None,
        actual_value: Optional[str] = None,
        model_name: str = "cache_predictor"
    ) -> bool:
        """
        Record prediction dan update algorithms.
        
        Args:
            key: Cache key
            predicted_value: Predicted value
            confidence: Model confidence (0-1)
            latency_ms: Prediction latency
            actual_value: Actual value (if known)
            model_name: Model name
            
        Returns:
            True if successful
        """
        try:
            # Record in database & observability
            success = self.trainer_int.record_prediction(
                key=key,
                predicted_value=predicted_value,
                actual_value=actual_value,
                confidence=confidence,
                latency_ms=latency_ms,
                model_name=model_name
            )
            
            if not success:
                return False
            
            # Update cache operation
            is_correct = (predicted_value == actual_value) if actual_value else None
            if is_correct is not None:
                self.trainer_int.update_cache_operation(key, is_correct)
            
            return True
        except Exception as e:
            logger.error(f"Failed to record prediction for {key}: {e}")
            return False
    
    def get_enhanced_confidence(
        self,
        key: str,
        base_confidence: float,
        use_algorithms: bool = True
    ) -> float:
        """
        Boost confidence using algorithms (EWMA trend, drift detection).
        
        Args:
            key: Cache key
            base_confidence: Base model confidence (0-1)
            use_algorithms: Whether to apply algorithm boosting
            
        Returns:
            Enhanced confidence (0-1)
        """
        if not use_algorithms:
            return base_confidence
        
        try:
            # Get EWMA trend
            trend = self.trainer_int.get_ewma_trend(key)
            
            # Get drift score
            drift_score = self.trainer_int.get_drift_score(key)
            
            # Boost confidence based on trend
            confidence = base_confidence
            
            if trend == "increasing":
                confidence *= 1.1  # 10% boost
            elif trend == "decreasing":
                confidence *= 0.9  # 10% penalty
            
            # Penalty for drift
            if drift_score > 0.3:
                confidence *= 0.8  # 20% penalty for critical drift
            elif drift_score > 0.15:
                confidence *= 0.9  # 10% penalty for warning drift
            
            # Clamp to 0-1
            return max(0.0, min(1.0, confidence))
        except Exception as e:
            logger.error(f"Failed to enhance confidence for {key}: {e}")
            return base_confidence
    
    def should_retrain(self, key: str) -> bool:
        """
        Check if retraining should be triggered based on drift.
        
        Args:
            key: Cache key
            
        Returns:
            True if critical drift detected
        """
        try:
            drift_score = self.trainer_int.get_drift_score(key)
            return drift_score > 0.3  # Critical threshold
        except Exception as e:
            logger.error(f"Failed to check retrain condition for {key}: {e}")
            return False
    
    def get_metrics(self, key: Optional[str] = None) -> dict:
        """
        Get current metrics for a key or all keys.
        
        Args:
            key: Specific key (optional)
            
        Returns:
            Metrics dictionary
        """
        try:
            if key:
                return {
                    "key": key,
                    "ewma_trend": self.trainer_int.get_ewma_trend(key),
                    "drift_score": self.trainer_int.get_drift_score(key)
                }
            else:
                return self.trainer_int.get_per_key_metrics()
        except Exception as e:
            logger.error(f"Failed to get metrics: {e}")
            return {}


# Singleton instance
_predictor_int = None

def get_predictor_integration() -> PredictorIntegration:
    """Get or create singleton PredictorIntegration instance."""
    global _predictor_int
    if _predictor_int is None:
        _predictor_int = PredictorIntegration()
    return _predictor_int
