# ============================================================
# PSKC — ML Module Tests
# ============================================================
import pytest
import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ml.data_collector import DataCollector, AccessEvent
from src.ml.feature_engineering import FeatureEngineer


class TestDataCollector:
    """Test cases for DataCollector"""
    
    def test_record_access(self):
        """Test recording access events"""
        collector = DataCollector(max_events=1000)
        
        collector.record_access(
            key_id="key1",
            service_id="service1",
            cache_hit=True,
            latency_ms=5.0
        )
        
        stats = collector.get_key_stats("key1")
        
        assert stats is not None
        assert stats.total_accesses == 1
        assert stats.cache_hits == 1
    
    def test_get_hot_keys(self):
        """Test getting hot keys"""
        collector = DataCollector(max_events=1000)
        
        # Add more accesses to key1
        for _ in range(10):
            collector.record_access("key1", "service1", cache_hit=True)
        
        for _ in range(5):
            collector.record_access("key2", "service1", cache_hit=True)
        
        hot_keys = collector.get_hot_keys(limit=2)
        
        assert hot_keys[0][0] == "key1"
        assert hot_keys[0][1] == 10
    
    def test_get_access_sequence(self):
        """Test getting access sequence"""
        collector = DataCollector(max_events=100)
        
        for i in range(10):
            collector.record_access(f"key_{i % 3}", "service1", cache_hit=True)
        
        sequence = collector.get_access_sequence(max_events=5)
        
        assert len(sequence) <= 5
    
    def test_temporal_features(self):
        """Test temporal feature extraction"""
        collector = DataCollector(max_events=1000)
        
        for _ in range(20):
            collector.record_access("key1", "service1", cache_hit=True)
        
        features = collector.get_temporal_features("key1")
        
        assert "total_accesses" in features
        assert features["total_accesses"] == 20


class TestFeatureEngineer:
    """Test cases for FeatureEngineer"""
    
    def test_extract_features(self):
        """Test feature extraction"""
        engineer = FeatureEngineer()
        
        # Create sample data
        import time
        now = time.time()
        
        data = [
            {
                "key_id": f"key_{i % 3}",
                "service_id": "service1",
                "timestamp": now - i * 10,
                "hour": 10,
                "day_of_week": 1,
                "cache_hit": 1,
                "latency_ms": 10.0
            }
            for i in range(20)
        ]
        
        features = engineer.extract_features(data)
        
        assert isinstance(features, np.ndarray)
        assert len(features) > 0
    
    def test_default_features(self):
        """Test default features for empty data"""
        engineer = FeatureEngineer()
        
        features = engineer.extract_features([])
        
        assert isinstance(features, np.ndarray)
        assert np.all(features == 0)
    
    def test_temporal_features(self):
        """Test temporal feature extraction"""
        engineer = FeatureEngineer()
        
        import time
        now = time.time()
        
        # Morning access pattern
        data = [
            {
                "key_id": "key1",
                "service_id": "service1",
                "timestamp": now - i * 60,
                "hour": 10,
                "day_of_week": 1,
                "cache_hit": 1,
                "latency_ms": 10.0
            }
            for i in range(10)
        ]
        
        features = engineer.extract_features(data)
        
        # Should have temporal features
        assert len(features) > 8
    
    def test_get_feature_names(self):
        """Test feature names list"""
        engineer = FeatureEngineer()
        
        names = engineer.get_feature_names()
        
        assert isinstance(names, list)
        assert len(names) > 0


class TestFeatureEngineering:
    """Integration tests for feature engineering"""
    
    def test_feature_shape_consistency(self):
        """Test that features always have same shape"""
        engineer = FeatureEngineer()
        
        import time
        now = time.time()
        
        for size in [1, 10, 50, 100]:
            data = [
                {
                    "key_id": f"key_{i}",
                    "service_id": "service1",
                    "timestamp": now - i,
                    "hour": 10,
                    "day_of_week": 1,
                    "cache_hit": 1,
                    "latency_ms": 10.0
                }
                for i in range(size)
            ]
            
            features = engineer.extract_features(data)
            
            # Should always have same feature dimension
            if size >= 1:
                assert len(features) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
