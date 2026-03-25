# ============================================================
# PSKC — Trainer Integration Wrapper
# ============================================================
"""
Integration layer untuk menghubungkan existing trainer.py dengan:
- ModelVersionManager (database versioning)
- PatternManager (Redis pattern learning)
- Advanced algorithms (EWMA, Drift, Dynamic Markov)
- EnhancedObservabilityService (metrics collection)

Drop-in integration tanpa mengubah existing trainer logic.
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from src.ml.model_version_manager import ModelVersionManager
from src.ml.pattern_manager import PatternManager
from src.ml.algorithm_improvements import EWMACalculator, DriftDetector, DynamicMarkovChain
from src.observability.enhanced_observability import EnhancedObservabilityService
from src.database.connection import get_db

logger = logging.getLogger(__name__)


class TrainerIntegration:
    """
    Wrapper untuk integrate trainer.py dengan semua enhancement modules.
    
    Usage:
    ```python
    integration = TrainerIntegration()
    
    # Setelah training selesai:
    integration.after_training(
        model_name="cache_predictor",
        new_accuracy=0.95,
        old_accuracy=0.92,
        samples_count=10000
    )
    ```
    """
    
    def __init__(self):
        """Initialize integration components."""
        try:
            self.db = next(get_db())
            self.version_manager = ModelVersionManager(self.db)
            self.pattern_manager = PatternManager()
            self.observability = EnhancedObservabilityService(self.db)
            
            # Algorithm components
            self.ewma = EWMACalculator(alpha_short=0.3, alpha_long=0.1)
            self.drift_detector = DriftDetector(short_window=30, long_window=200)
            self.markov = DynamicMarkovChain(
                states=["cache_hit", "cache_miss", "prediction_correct", "prediction_incorrect"]
            )
            
            logger.info("✅ TrainerIntegration initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize TrainerIntegration: {e}")
            raise
    
    def after_training(
        self,
        model_name: str,
        new_accuracy: float,
        old_accuracy: Optional[float] = None,
        samples_count: int = 0,
        training_start_time: Optional[datetime] = None,
        training_end_time: Optional[datetime] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Call this after training completes to:
        1. Create new model version
        2. Record training metadata
        3. Optionally promote to production
        
        Args:
            model_name: Name of model (e.g., "cache_predictor")
            new_accuracy: New accuracy after training
            old_accuracy: Previous accuracy (optional)
            samples_count: Number of training samples
            training_start_time: Training start time
            training_end_time: Training end time
            
        Returns:
            Dictionary with version info, or None if failed
        """
        try:
            # Get latest version number
            latest = self.version_manager.get_latest_version(model_name)
            version_number = (latest.version_number + 1) if latest else 1
            
            # Create new version (start as "dev")
            version = self.version_manager.create_version(
                model_name=model_name,
                version_number=version_number,
                status="dev",
                parent_version_id=latest.version_id if latest else None
            )
            
            logger.info(f"✅ Created version {version.version_id} for {model_name}@v{version_number}")
            
            # Record training metadata
            if training_start_time and training_end_time:
                self.version_manager.record_training(
                    version_id=version.version_id,
                    training_start_time=training_start_time,
                    training_end_time=training_end_time,
                    samples_count=samples_count,
                    accuracy_before=old_accuracy,
                    accuracy_after=new_accuracy
                )
            
            # Record accuracy metric
            self.version_manager.record_metric(
                version_id=version.version_id,
                metric_name="accuracy",
                metric_value=new_accuracy
            )
            
            # Check if should promote to production
            should_promote = False
            if old_accuracy and new_accuracy > old_accuracy * 1.05:  # 5% improvement
                should_promote = True
                self.version_manager.switch_version(version.version_id, "production")
                logger.info(f"✅ Version {version.version_id} promoted to production (accuracy: {old_accuracy:.4f} → {new_accuracy:.4f})")
            
            return {
                "version_id": version.version_id,
                "model_name": model_name,
                "version_number": version_number,
                "accuracy": new_accuracy,
                "promoted_to_production": should_promote
            }
        except Exception as e:
            logger.error(f"Failed to process training completion: {e}")
            return None
    
    def before_training(
        self,
        model_name: str
    ) -> Optional[int]:
        """
        Call this before training starts to get current version ID for reference.
        
        Args:
            model_name: Name of model
            
        Returns:
            Current version ID or None
        """
        try:
            current = self.version_manager.get_current_version(model_name)
            if current:
                logger.info(f"Current production version: {current.version_id}")
                return current.version_id
            return None
        except Exception as e:
            logger.error(f"Failed to get current version: {e}")
            return None
    
    def record_prediction(
        self,
        key: str,
        predicted_value: str,
        actual_value: Optional[str] = None,
        confidence: Optional[float] = None,
        latency_ms: Optional[float] = None,
        model_name: str = "cache_predictor"
    ) -> bool:
        """
        Record a prediction for analytics and drift detection.
        
        Args:
            key: Cache key
            predicted_value: Model's prediction
            actual_value: Actual value (if known)
            confidence: Model confidence (0-1)
            latency_ms: Prediction latency in milliseconds
            model_name: Model name
            
        Returns:
            True if successful
        """
        try:
            # Get current version
            current_version = self.version_manager.get_current_version(model_name)
            if not current_version:
                return False
            
            # Determine if prediction is correct
            is_correct = (predicted_value == actual_value) if actual_value else None
            
            # Record in database
            success = self.version_manager.record_prediction(
                version_id=current_version.version_id,
                key=key,
                predicted_value=predicted_value,
                actual_value=actual_value,
                is_correct=is_correct,
                confidence=confidence
            )
            
            if not success:
                return False
            
            # Update algorithms
            if is_correct is not None:
                # Update EWMA
                self.ewma.update(key, 1.0 if is_correct else 0.0)
                
                # Update drift detector
                drift_result = self.drift_detector.update(key, 1.0 if is_correct else 0.0)
                
                # Check if retraining needed
                if drift_result["drift_level"] == "critical":
                    logger.warning(f"⚠️  Critical drift detected for {key}: {drift_result['drift_score']:.3f}")
            
            # Record in observability service
            self.observability.record_prediction(
                version_id=current_version.version_id,
                key=key,
                predicted_value=predicted_value,
                actual_value=actual_value,
                confidence=confidence,
                latency_ms=latency_ms
            )
            
            return True
        except Exception as e:
            logger.error(f"Failed to record prediction for {key}: {e}")
            return False
    
    def extract_and_store_patterns(
        self,
        session_id: str,
        pages_accessed: list,
        access_times: list,
        cache_operations: list,
        model_name: str = "cache_predictor"
    ) -> bool:
        """
        Extract behavioral patterns from session and store in Redis.
        
        Args:
            session_id: Session identifier
            pages_accessed: List of pages accessed
            access_times: List of access timestamps
            cache_operations: List of cache hit/miss operations
            model_name: Model name
            
        Returns:
            True if successful
        """
        try:
            current_version = self.version_manager.get_current_version(model_name)
            if not current_version:
                return False
            
            # Extract patterns
            page_pattern = self.pattern_manager.extract_page_access_pattern(
                session_id, pages_accessed
            )
            temporal_pattern = self.pattern_manager.extract_temporal_pattern(
                session_id, access_times
            )
            cache_pattern = self.pattern_manager.extract_cache_hit_pattern(
                session_id, cache_operations
            )
            
            # Store in Redis
            self.pattern_manager.store_pattern(
                version_id=current_version.version_id,
                pattern_type="page_access",
                pattern_key=session_id,
                pattern_data=page_pattern
            )
            
            self.pattern_manager.store_pattern(
                version_id=current_version.version_id,
                pattern_type="temporal",
                pattern_key=session_id,
                pattern_data=temporal_pattern
            )
            
            self.pattern_manager.store_pattern(
                version_id=current_version.version_id,
                pattern_type="cache_hit",
                pattern_key=session_id,
                pattern_data=cache_pattern
            )
            
            logger.info(f"✅ Extracted and stored patterns for session {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to extract patterns for {session_id}: {e}")
            return False
    
    def get_per_key_metrics(
        self,
        model_name: str = "cache_predictor"
    ) -> Dict[str, Any]:
        """
        Get current per-key metrics for monitoring.
        
        Args:
            model_name: Model name
            
        Returns:
            Dictionary of metrics per key
        """
        try:
            current_version = self.version_manager.get_current_version(model_name)
            if not current_version:
                return {}
            
            metrics = self.version_manager.get_per_key_metrics(current_version.version_id)
            return {
                "version_id": current_version.version_id,
                "total_keys": len(metrics),
                "metrics": [
                    {
                        "key": m.key,
                        "accuracy": m.accuracy,
                        "drift_score": m.drift_score,
                        "cache_hit_rate": m.cache_hit_rate
                    }
                    for m in metrics
                ]
            }
        except Exception as e:
            logger.error(f"Failed to get per-key metrics: {e}")
            return {}
    
    def get_benchmark_metrics(
        self,
        baseline_latency_ms: float = 100.0,
        model_name: str = "cache_predictor"
    ) -> Dict[str, Any]:
        """
        Get benchmark metrics showing PSKC effectiveness.
        
        Args:
            baseline_latency_ms: Baseline latency to compare against
            model_name: Model name
            
        Returns:
            Benchmark metrics
        """
        try:
            current_version = self.version_manager.get_current_version(model_name)
            if not current_version:
                return {}
            
            return self.observability.get_benchmark_metrics(
                current_version.version_id,
                baseline_latency_ms
            )
        except Exception as e:
            logger.error(f"Failed to get benchmark metrics: {e}")
            return {}
    
    def get_drift_score(self, key: str) -> float:
        """Get current drift score for a key."""
        return self.drift_detector.get_drift_score(key)
    
    def get_ewma_trend(self, key: str) -> str:
        """Get EWMA trend for a key (increasing/decreasing/stable)."""
        return self.ewma.get_trend(key)
    
    def update_cache_operation(self, key: str, is_hit: bool):
        """Record cache hit/miss for a key."""
        self.observability.record_cache_operation(key, is_hit)
    
    def cleanup(self):
        """Clean up resources."""
        try:
            if self.db:
                self.db.close()
            logger.info("✅ TrainerIntegration cleaned up")
        except Exception as e:
            logger.error(f"Failed to cleanup: {e}")


# Singleton instance
_integration = None

def get_trainer_integration() -> TrainerIntegration:
    """Get or create singleton TrainerIntegration instance."""
    global _integration
    if _integration is None:
        _integration = TrainerIntegration()
    return _integration
