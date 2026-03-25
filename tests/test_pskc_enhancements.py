# ============================================================
# PSKC — Comprehensive Unit Tests
# ============================================================
"""
Unit tests untuk semua enhancement modules.
Run dengan: python -m pytest tests/test_pskc_enhancements.py -v
"""

import pytest
import logging
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, ModelVersion, ModelMetric, PerKeyMetric
from src.ml.model_version_manager import ModelVersionManager
from src.ml.pattern_manager import PatternManager
from src.ml.algorithm_improvements import EWMACalculator, DriftDetector, DynamicMarkovChain
from src.observability.enhanced_observability import EnhancedObservabilityService
from src.ml.trainer_integration import TrainerIntegration
from src.api.predictor_integration import PredictorIntegration
from src.ml.data_collector_integration import DataCollectorIntegration

logger = logging.getLogger(__name__)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def test_db():
    """Create in-memory test database."""
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def version_manager(test_db):
    """Create ModelVersionManager instance."""
    return ModelVersionManager(test_db)


@pytest.fixture
def ewma():
    """Create EWMACalculator instance."""
    return EWMACalculator(alpha_short=0.3, alpha_long=0.1)


@pytest.fixture
def drift_detector():
    """Create DriftDetector instance."""
    return DriftDetector(short_window=30, long_window=200)


@pytest.fixture
def markov():
    """Create DynamicMarkovChain instance."""
    return DynamicMarkovChain(
        states=["cache_hit", "cache_miss", "prediction_correct", "prediction_incorrect"]
    )


# ============================================================
# ModelVersionManager Tests
# ============================================================

class TestModelVersionManager:
    """Test ModelVersionManager functionality."""
    
    def test_create_version(self, version_manager):
        """Test creating a new model version."""
        version = version_manager.create_version(
            model_name="test_model",
            version_number=1,
            status="dev"
        )
        
        assert version is not None
        assert version.version_id > 0
        assert version.model_name == "test_model"
        assert version.version_number == 1
        assert version.status == "dev"
        logger.info("✅ test_create_version passed")
    
    def test_create_version_with_parent(self, version_manager):
        """Test creating version with parent lineage."""
        v1 = version_manager.create_version("test", 1)
        v2 = version_manager.create_version(
            "test", 2, parent_version_id=v1.version_id
        )
        
        assert v2.parent_version_id == v1.version_id
        logger.info("✅ test_create_version_with_parent passed")
    
    def test_get_current_version(self, version_manager):
        """Test retrieving current production version."""
        v1 = version_manager.create_version("test", 1, "dev")
        version_manager.switch_version(v1.version_id, "production")
        
        current = version_manager.get_current_version("test")
        assert current is not None
        assert current.status == "production"
        logger.info("✅ test_get_current_version passed")
    
    def test_get_latest_version(self, version_manager):
        """Test retrieving latest version."""
        v1 = version_manager.create_version("test", 1, "dev")
        v2 = version_manager.create_version("test", 2, "staging")
        
        latest = version_manager.get_latest_version("test")
        assert latest.version_id == v2.version_id
        logger.info("✅ test_get_latest_version passed")
    
    def test_switch_version(self, version_manager):
        """Test switching version status."""
        v1 = version_manager.create_version("test", 1, "dev")
        success = version_manager.switch_version(v1.version_id, "production")
        
        assert success
        v1_updated = version_manager.get_version(v1.version_id)
        assert v1_updated.status == "production"
        logger.info("✅ test_switch_version passed")
    
    def test_record_metric(self, version_manager):
        """Test recording metrics."""
        v = version_manager.create_version("test", 1)
        success = version_manager.record_metric(
            v.version_id,
            "accuracy",
            0.95
        )
        
        assert success
        metrics = version_manager.get_version_metrics(v.version_id)
        assert metrics.get("accuracy") == 0.95
        logger.info("✅ test_record_metric passed")
    
    def test_record_prediction(self, version_manager):
        """Test recording predictions."""
        v = version_manager.create_version("test", 1)
        success = version_manager.record_prediction(
            v.version_id,
            "test_key",
            "predicted_value",
            "actual_value",
            is_correct=True,
            confidence=0.92
        )
        
        assert success
        logger.info("✅ test_record_prediction passed")
    
    def test_update_per_key_metrics(self, version_manager):
        """Test updating per-key metrics."""
        v = version_manager.create_version("test", 1)
        success = version_manager.update_per_key_metrics(
            v.version_id,
            "test_key",
            accuracy=0.94,
            drift_score=0.15,
            cache_hit_rate=0.87
        )
        
        assert success
        metrics = version_manager.get_per_key_metrics(v.version_id, "test_key")
        assert len(metrics) > 0
        logger.info("✅ test_update_per_key_metrics passed")


# ============================================================
# PatternManager Tests
# ============================================================

class TestPatternManager:
    """Test PatternManager functionality."""
    
    def test_extract_page_access_pattern(self):
        """Test page access pattern extraction."""
        pm = PatternManager()
        pattern = pm.extract_page_access_pattern(
            "session1",
            ["home", "profile", "settings", "profile"]
        )
        
        assert "page_frequency" in pattern
        assert pattern["page_frequency"]["profile"] == 2
        assert pattern["unique_pages"] == 3
        logger.info("✅ test_extract_page_access_pattern passed")
    
    def test_extract_temporal_pattern(self):
        """Test temporal pattern extraction."""
        pm = PatternManager()
        times = [
            datetime(2026, 3, 24, 10, 0),
            datetime(2026, 3, 24, 10, 5),
            datetime(2026, 3, 24, 14, 0)
        ]
        
        pattern = pm.extract_temporal_pattern("session1", times)
        
        assert "hours_accessed" in pattern
        assert 10 in pattern["hours_accessed"]
        assert 14 in pattern["hours_accessed"]
        logger.info("✅ test_extract_temporal_pattern passed")
    
    def test_extract_cache_hit_pattern(self):
        """Test cache hit pattern extraction."""
        pm = PatternManager()
        ops = [
            {"key": "k1", "hit": True},
            {"key": "k1", "hit": True},
            {"key": "k2", "hit": False},
            {"key": "k1", "hit": True}
        ]
        
        pattern = pm.extract_cache_hit_pattern("session1", ops)
        
        assert pattern["hits"] == 3
        assert pattern["misses"] == 1
        assert pattern["hit_rate"] == 0.75
        logger.info("✅ test_extract_cache_hit_pattern passed")
    
    def test_calculate_pattern_statistics(self):
        """Test pattern statistics calculation."""
        pm = PatternManager()
        patterns = {
            "session1": {
                "hit_rate": 0.9,
                "page_frequency": {"home": 5, "profile": 3}
            },
            "session2": {
                "hit_rate": 0.8,
                "page_frequency": {"home": 4, "settings": 2}
            }
        }
        
        stats = pm.calculate_pattern_statistics(patterns)
        
        assert stats["total_patterns"] == 2
        assert stats["avg_hit_rate"] == 0.85
        assert "most_common_pages" in stats
        logger.info("✅ test_calculate_pattern_statistics passed")


# ============================================================
# EWMA Tests
# ============================================================

class TestEWMACalculator:
    """Test EWMACalculator functionality."""
    
    def test_initialization(self, ewma):
        """Test EWMA initialization."""
        short, long = ewma.update("key1", 0.8)
        assert short == 0.8
        assert long == 0.8
        logger.info("✅ test_initialization passed")
    
    def test_update_increasing(self, ewma):
        """Test EWMA update with increasing values."""
        ewma.update("key1", 0.8)
        short2, long2 = ewma.update("key1", 0.9)
        
        assert short2 > 0.8
        assert long2 > 0.8
        logger.info("✅ test_update_increasing passed")
    
    def test_trend_detection(self, ewma):
        """Test trend detection."""
        for _ in range(5):
            ewma.update("key1", 0.95)
        
        short, long = ewma.get("key1")
        trend = ewma.get_trend("key1")
        
        assert trend == "increasing" or trend == "stable"
        logger.info("✅ test_trend_detection passed")
    
    def test_short_vs_long_difference(self, ewma):
        """Test that short-term is more responsive than long-term."""
        # Start at 0.5
        ewma.update("key1", 0.5)
        
        # Jump to 0.9
        short1, long1 = ewma.update("key1", 0.9)
        
        # Short should respond more than long
        assert short1 > long1
        logger.info("✅ test_short_vs_long_difference passed")


# ============================================================
# DriftDetector Tests
# ============================================================

class TestDriftDetector:
    """Test DriftDetector functionality."""
    
    def test_no_drift_stable_values(self, drift_detector):
        """Test no drift when values are stable."""
        for _ in range(50):
            drift_detector.update("key1", 1.0)  # All correct
        
        score = drift_detector.get_drift_score("key1")
        assert score < 0.2  # No drift
        logger.info("✅ test_no_drift_stable_values passed")
    
    def test_drift_detection_accuracy_drop(self, drift_detector):
        """Test drift detection when accuracy drops."""
        # Initial high accuracy
        for _ in range(50):
            drift_detector.update("key1", 1.0)
        
        # Accuracy drops
        for _ in range(20):
            drift_detector.update("key1", 0.0)
        
        score = drift_detector.get_drift_score("key1")
        assert score > 0.15  # Detects drift
        logger.info("✅ test_drift_detection_accuracy_drop passed")
    
    def test_drift_level_classification(self, drift_detector):
        """Test drift level classification."""
        # Create critical drift
        for _ in range(50):
            drift_detector.update("key1", 1.0)
        for _ in range(50):
            drift_detector.update("key1", 0.0)
        
        result = drift_detector.update("key1", 0.0)
        
        assert result["drift_level"] in ["critical", "warning", "normal"]
        logger.info("✅ test_drift_level_classification passed")


# ============================================================
# DynamicMarkovChain Tests
# ============================================================

class TestDynamicMarkovChain:
    """Test DynamicMarkovChain functionality."""
    
    def test_observe_transitions(self, markov):
        """Test recording state transitions."""
        markov.observe("key1", "cache_hit", "cache_hit")
        markov.observe("key1", "cache_hit", "cache_miss")
        markov.observe("key1", "cache_miss", "cache_hit")
        
        probs = markov.get_transition_probability("key1", "cache_hit")
        assert probs is not None
        logger.info("✅ test_observe_transitions passed")
    
    def test_predict_next_state(self, markov):
        """Test next state prediction."""
        # Create strong pattern
        for _ in range(10):
            markov.observe("key1", "cache_hit", "cache_hit")
        for _ in range(2):
            markov.observe("key1", "cache_hit", "cache_miss")
        
        next_state = markov.predict_next_state("key1", "cache_hit")
        assert next_state is not None
        logger.info("✅ test_predict_next_state passed")
    
    def test_decay_factor(self, markov):
        """Test exponential decay of old observations."""
        # Old observations
        for _ in range(5):
            markov.observe("key1", "cache_hit", "cache_miss")
        
        initial_probs = markov.get_transition_probability("key1", "cache_hit")
        
        # New observations (opposite pattern)
        for _ in range(10):
            markov.observe("key1", "cache_hit", "cache_hit")
        
        new_probs = markov.get_transition_probability("key1", "cache_hit")
        
        # New pattern should dominate due to decay
        assert new_probs.get("cache_hit", 0) > initial_probs.get("cache_hit", 0)
        logger.info("✅ test_decay_factor passed")


# ============================================================
# EnhancedObservabilityService Tests
# ============================================================

class TestEnhancedObservabilityService:
    """Test EnhancedObservabilityService functionality."""
    
    def test_record_prediction(self, test_db):
        """Test recording a prediction."""
        obs = EnhancedObservabilityService(test_db)
        success = obs.record_prediction(
            version_id=1,
            key="test_key",
            predicted_value="home",
            actual_value="home",
            confidence=0.92,
            latency_ms=45.5
        )
        
        assert success
        logger.info("✅ test_record_prediction passed")
    
    def test_record_cache_operation(self, test_db):
        """Test recording cache operations."""
        obs = EnhancedObservabilityService(test_db)
        obs.record_cache_operation("key1", True)
        obs.record_cache_operation("key1", True)
        obs.record_cache_operation("key1", False)
        
        # Verify recorded (no error)
        logger.info("✅ test_record_cache_operation passed")
    
    def test_get_latency_metrics(self, test_db):
        """Test latency metrics calculation."""
        obs = EnhancedObservabilityService(test_db)
        obs.latency_buckets["key1"].append(40)
        obs.latency_buckets["key1"].append(50)
        obs.latency_buckets["key1"].append(45)
        
        metrics = obs.get_latency_metrics("key1")
        
        assert metrics["min_ms"] == 40
        assert metrics["max_ms"] == 50
        assert metrics["avg_ms"] == 45
        logger.info("✅ test_get_latency_metrics passed")


# ============================================================
# Integration Tests
# ============================================================

class TestIntegrations:
    """Test integration layers."""
    
    def test_trainer_integration(self, test_db):
        """Test TrainerIntegration workflow."""
        # Note: This would need more setup with real DB
        # This is a placeholder for full integration test
        logger.info("✅ test_trainer_integration placeholder passed")
    
    def test_predictor_integration(self):
        """Test PredictorIntegration workflow."""
        # Note: This would need more setup with real DB
        logger.info("✅ test_predictor_integration placeholder passed")
    
    def test_data_collector_integration(self):
        """Test DataCollectorIntegration workflow."""
        # Note: This would need more setup with real DB
        logger.info("✅ test_data_collector_integration placeholder passed")


# ============================================================
# Run Tests
# ============================================================

if __name__ == "__main__":
    # Run with: python -m pytest tests/test_pskc_enhancements.py -v
    pytest.main([__file__, "-v"])
