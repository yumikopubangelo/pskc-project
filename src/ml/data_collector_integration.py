# ============================================================
# PSKC — Data Collector Integration
# ============================================================
"""
Integration untuk data_collector.py untuk extract patterns
dari collected data dan store di Redis.

Menambahkan pattern extraction ke existing data collection flow.
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from src.ml.trainer_integration import get_trainer_integration

logger = logging.getLogger(__name__)


class DataCollectorIntegration:
    """
    Wrapper untuk integrate pattern extraction dengan data collector.
    
    Usage:
    ```python
    from src.ml.data_collector_integration import DataCollectorIntegration
    
    collector_int = DataCollectorIntegration()
    
    # Setelah mengumpulkan session data:
    collector_int.process_session_data(
        session_id="session1",
        pages_accessed=["home", "profile", "settings"],
        access_times=[datetime1, datetime2, datetime3],
        cache_operations=[{"key": "k1", "hit": True}, ...]
    )
    ```
    """
    
    def __init__(self):
        """Initialize data collector integration."""
        self.trainer_int = get_trainer_integration()
        self.processed_sessions = set()  # Track processed sessions
    
    def process_session_data(
        self,
        session_id: str,
        pages_accessed: List[str],
        access_times: List[datetime],
        cache_operations: List[Dict[str, Any]],
        model_name: str = "cache_predictor",
        auto_record_predictions: bool = False
    ) -> bool:
        """
        Process session data and extract patterns.
        
        Args:
            session_id: Unique session identifier
            pages_accessed: List of pages accessed in order
            access_times: Timestamps for each access
            cache_operations: List of cache hit/miss operations
            model_name: Model to associate patterns with
            auto_record_predictions: Also record cache predictions
            
        Returns:
            True if successful
        """
        try:
            # Avoid duplicate processing
            if session_id in self.processed_sessions:
                logger.debug(f"Session {session_id} already processed")
                return True
            
            # Extract and store patterns
            success = self.trainer_int.extract_and_store_patterns(
                session_id=session_id,
                pages_accessed=pages_accessed,
                access_times=access_times,
                cache_operations=cache_operations,
                model_name=model_name
            )
            
            if success:
                self.processed_sessions.add(session_id)
                logger.info(f"✅ Processed patterns for session {session_id}")
                
                # Optionally record cache operations as predictions
                if auto_record_predictions:
                    self._record_cache_predictions(session_id, cache_operations)
            
            return success
        except Exception as e:
            logger.error(f"Failed to process session {session_id}: {e}")
            return False
    
    def _record_cache_predictions(
        self,
        session_id: str,
        cache_operations: List[Dict[str, Any]]
    ):
        """
        Record cache operations as predictions for drift tracking.
        
        Args:
            session_id: Session identifier
            cache_operations: List of cache operations
        """
        try:
            for i, op in enumerate(cache_operations):
                key = op.get('key', f'{session_id}_key_{i}')
                is_hit = op.get('hit', False)
                
                # Record as prediction
                self.trainer_int.record_prediction(
                    key=key,
                    predicted_value="hit" if is_hit else "miss",
                    actual_value="hit" if is_hit else "miss",
                    confidence=0.95 if is_hit else 0.05
                )
        except Exception as e:
            logger.error(f"Failed to record cache predictions: {e}")
    
    def extract_feature_engineering_data(
        self,
        session_id: str,
        model_name: str = "cache_predictor"
    ) -> Optional[Dict[str, Any]]:
        """
        Extract features from stored patterns for training.
        
        Returns features that can be used in model training.
        
        Args:
            session_id: Session identifier
            model_name: Model name
            
        Returns:
            Dictionary of engineered features or None
        """
        try:
            current_version = self.trainer_int.version_manager.get_current_version(model_name)
            if not current_version:
                return None
            
            # Get patterns for this session
            page_pattern = self.trainer_int.pattern_manager.get_pattern(
                current_version.version_id, "page_access", session_id
            )
            temporal_pattern = self.trainer_int.pattern_manager.get_pattern(
                current_version.version_id, "temporal", session_id
            )
            cache_pattern = self.trainer_int.pattern_manager.get_pattern(
                current_version.version_id, "cache_hit", session_id
            )
            
            # Engineer features
            features = {}
            
            if page_pattern:
                features['unique_pages'] = page_pattern.get('unique_pages', 0)
                features['total_page_accesses'] = page_pattern.get('total_accesses', 0)
                features['page_frequency_max'] = max(
                    page_pattern.get('page_frequency', {}).values()
                ) if page_pattern.get('page_frequency') else 0
            
            if temporal_pattern:
                features['peak_hour_frequency'] = len(temporal_pattern.get('peak_hours', []))
                features['avg_request_interval'] = temporal_pattern.get('avg_request_interval_seconds', 0)
            
            if cache_pattern:
                features['cache_hit_rate'] = cache_pattern.get('hit_rate', 0.0)
                features['total_cache_operations'] = cache_pattern.get('total_operations', 0)
                features['frequently_hit_keys_count'] = len(
                    cache_pattern.get('frequently_hit_keys', {})
                )
            
            return features
        except Exception as e:
            logger.error(f"Failed to extract features for {session_id}: {e}")
            return None
    
    def apply_pattern_weights(
        self,
        training_data: List[Dict[str, Any]],
        session_patterns: Dict[str, Any],
        model_name: str = "cache_predictor"
    ) -> List[Dict[str, Any]]:
        """
        Adjust training data weights based on session patterns.
        
        Sessions with common patterns get higher weight.
        
        Args:
            training_data: List of training samples
            session_patterns: Pattern statistics from sessions
            model_name: Model name
            
        Returns:
            Training data with adjusted weights
        """
        try:
            weighted_data = []
            
            for sample in training_data:
                weight = 1.0  # Default weight
                
                # Boost weight for samples matching common patterns
                if session_patterns.get('avg_cache_hit_rate', 0) > 0.8:
                    # High cache hit rate sessions are valuable
                    if sample.get('is_cache_hit'):
                        weight *= 1.5
                
                # Boost weight for frequently accessed pages
                if sample.get('page') in session_patterns.get('frequently_accessed_pages', []):
                    weight *= 1.3
                
                # Boost weight for peak hour patterns
                if sample.get('hour') in session_patterns.get('peak_hours', []):
                    weight *= 1.2
                
                sample['weight'] = weight
                weighted_data.append(sample)
            
            logger.info(f"Applied pattern weights to {len(weighted_data)} samples")
            return weighted_data
        except Exception as e:
            logger.error(f"Failed to apply pattern weights: {e}")
            return training_data
    
    def get_pattern_statistics(
        self,
        model_name: str = "cache_predictor"
    ) -> Optional[Dict[str, Any]]:
        """
        Get aggregate pattern statistics for all collected sessions.
        
        Args:
            model_name: Model name
            
        Returns:
            Aggregate pattern statistics
        """
        try:
            current_version = self.trainer_int.version_manager.get_current_version(model_name)
            if not current_version:
                return None
            
            # Get all patterns
            page_patterns = self.trainer_int.pattern_manager.get_all_patterns(
                current_version.version_id, "page_access"
            )
            temporal_patterns = self.trainer_int.pattern_manager.get_all_patterns(
                current_version.version_id, "temporal"
            )
            cache_patterns = self.trainer_int.pattern_manager.get_all_patterns(
                current_version.version_id, "cache_hit"
            )
            
            # Calculate statistics
            return {
                "total_sessions_analyzed": len(page_patterns) + len(temporal_patterns),
                "page_patterns": self.trainer_int.pattern_manager.calculate_pattern_statistics(
                    page_patterns
                ),
                "temporal_patterns": self.trainer_int.pattern_manager.calculate_pattern_statistics(
                    temporal_patterns
                ),
                "cache_patterns": self.trainer_int.pattern_manager.calculate_pattern_statistics(
                    cache_patterns
                ),
                "timestamp": datetime.utcnow().isoformat()
            }
        except Exception as e:
            logger.error(f"Failed to get pattern statistics: {e}")
            return None
    
    def cleanup_old_patterns(
        self,
        model_name: str = "cache_predictor",
        keep_versions: int = 3
    ) -> int:
        """
        Clean up patterns for old model versions.
        
        Args:
            model_name: Model name
            keep_versions: Number of recent versions to keep patterns for
            
        Returns:
            Number of pattern versions cleaned up
        """
        try:
            versions = self.trainer_int.version_manager.list_versions(
                model_name, limit=keep_versions+5
            )
            
            cleaned = 0
            for version in versions[keep_versions:]:
                count = self.trainer_int.pattern_manager.cleanup_patterns(
                    version.version_id
                )
                cleaned += count
            
            logger.info(f"Cleaned up {cleaned} patterns from old versions")
            return cleaned
        except Exception as e:
            logger.error(f"Failed to cleanup patterns: {e}")
            return 0


# Singleton instance
_collector_int = None

def get_data_collector_integration() -> DataCollectorIntegration:
    """Get or create singleton DataCollectorIntegration instance."""
    global _collector_int
    if _collector_int is None:
        _collector_int = DataCollectorIntegration()
    return _collector_int
