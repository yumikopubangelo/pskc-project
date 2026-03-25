# ============================================================
# PSKC — Unit Tests for EnhancedObservabilityService
# ============================================================
"""
Unit tests for EnhancedObservabilityService.
Tests prediction recording, metrics calculation, drift detection, and latency tracking.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta
from collections import deque

from src.observability.enhanced_observability import EnhancedObservabilityService
from src.database.models import KeyPrediction, PerKeyMetric


class TestEnhancedObservabilityService:
    """Test suite for EnhancedObservabilityService."""
    
    @pytest.fixture
    def mock_db_session(self):
        """Create a mock database session."""
        session = Mock()
        session.add = Mock()
        session.commit = Mock()
        session.rollback = Mock()
        session.query = Mock()
        return session
    
    @pytest.fixture
    def service(self, mock_db_session):
        """Create EnhancedObservabilityService instance with mock DB."""
        return EnhancedObservabilityService(db_session=mock_db_session)
    
    # =========================================================================
    # Test record_prediction
    # =========================================================================
    
    def test_record_prediction_success(self, service, mock_db_session):
        """Test successful prediction recording."""
        # Arrange
        version_id = 1
        key = "test_key"
        predicted_value = "value1"
        actual_value = "value1"
        confidence = 0.95
        latency_ms = 10.5
        
        # Act
        result = service.record_prediction(
            version_id=version_id,
            key=key,
            predicted_value=predicted_value,
            actual_value=actual_value,
            confidence=confidence,
            latency_ms=latency_ms
        )
        
        # Assert
        assert result is True
        mock_db_session.add.assert_called_once()
        mock_db_session.commit.assert_called_once()
        
        # Verify the prediction object was created correctly
        call_args = mock_db_session.add.call_args[0][0]
        assert isinstance(call_args, KeyPrediction)
        assert call_args.version_id == version_id
        assert call_args.key == key
        assert call_args.predicted_value == predicted_value
        assert call_args.actual_value == actual_value
        assert call_args.is_correct is True
        assert call_args.confidence == confidence
    
    def test_record_prediction_incorrect(self, service, mock_db_session):
        """Test recording incorrect prediction."""
        # Arrange
        version_id = 1
        key = "test_key"
        predicted_value = "value1"
        actual_value = "value2"
        
        # Act
        result = service.record_prediction(
            version_id=version_id,
            key=key,
            predicted_value=predicted_value,
            actual_value=actual_value
        )
        
        # Assert
        assert result is True
        call_args = mock_db_session.add.call_args[0][0]
        assert call_args.is_correct is False
    
    def test_record_prediction_no_actual_value(self, service, mock_db_session):
        """Test recording prediction without actual value."""
        # Arrange
        version_id = 1
        key = "test_key"
        predicted_value = "value1"
        
        # Act
        result = service.record_prediction(
            version_id=version_id,
            key=key,
            predicted_value=predicted_value
        )
        
        # Assert
        assert result is True
        call_args = mock_db_session.add.call_args[0][0]
        assert call_args.is_correct is None
    
    def test_record_prediction_updates_ewma(self, service):
        """Test that EWMA is updated when correctness is known."""
        # Arrange
        key = "test_key"
        service.accuracy_ewma = Mock()
        service.accuracy_ewma.update = Mock()
        
        # Act
        service.record_prediction(
            version_id=1,
            key=key,
            predicted_value="value1",
            actual_value="value1"
        )
        
        # Assert
        service.accuracy_ewma.update.assert_called_once_with(key, 1.0)
    
    def test_record_prediction_tracks_latency(self, service):
        """Test that latency is tracked in buckets."""
        # Arrange
        key = "test_key"
        latency_ms = 15.5
        
        # Act
        service.record_prediction(
            version_id=1,
            key=key,
            predicted_value="value1",
            latency_ms=latency_ms
        )
        
        # Assert
        assert latency_ms in service.latency_buckets[key]
    
    def test_record_prediction_database_error(self, service, mock_db_session):
        """Test handling of database errors during prediction recording."""
        # Arrange
        mock_db_session.commit.side_effect = Exception("Database error")
        
        # Act
        result = service.record_prediction(
            version_id=1,
            key="test_key",
            predicted_value="value1"
        )
        
        # Assert
        assert result is False
        mock_db_session.rollback.assert_called_once()
    
    # =========================================================================
    # Test record_cache_operation
    # =========================================================================
    
    def test_record_cache_hit(self, service):
        """Test recording cache hit."""
        # Arrange
        key = "test_key"
        
        # Act
        service.record_cache_operation(key=key, is_hit=True)
        
        # Assert
        assert service.cache_stats[key]["hits"] == 1
        assert service.cache_stats[key]["misses"] == 0
    
    def test_record_cache_miss(self, service):
        """Test recording cache miss."""
        # Arrange
        key = "test_key"
        
        # Act
        service.record_cache_operation(key=key, is_hit=False)
        
        # Assert
        assert service.cache_stats[key]["hits"] == 0
        assert service.cache_stats[key]["misses"] == 1
    
    def test_record_multiple_cache_operations(self, service):
        """Test recording multiple cache operations."""
        # Arrange
        key = "test_key"
        
        # Act
        service.record_cache_operation(key=key, is_hit=True)
        service.record_cache_operation(key=key, is_hit=True)
        service.record_cache_operation(key=key, is_hit=False)
        
        # Assert
        assert service.cache_stats[key]["hits"] == 2
        assert service.cache_stats[key]["misses"] == 1
    
    # =========================================================================
    # Test record_drift
    # =========================================================================
    
    def test_record_drift_correct(self, service):
        """Test recording correct prediction for drift detection."""
        # Arrange
        key = "test_key"
        service.drift_detector = Mock()
        service.drift_detector.update = Mock(return_value={"drift_detected": False})
        
        # Act
        result = service.record_drift(key=key, is_correct=True)
        
        # Assert
        service.drift_detector.update.assert_called_once_with(key, 1.0)
        assert result == {"drift_detected": False}
    
    def test_record_drift_incorrect(self, service):
        """Test recording incorrect prediction for drift detection."""
        # Arrange
        key = "test_key"
        service.drift_detector = Mock()
        service.drift_detector.update = Mock(return_value={"drift_detected": True})
        
        # Act
        result = service.record_drift(key=key, is_correct=False)
        
        # Assert
        service.drift_detector.update.assert_called_once_with(key, 0.0)
        assert result == {"drift_detected": True}
    
    # =========================================================================
    # Test get_latency_metrics
    # =========================================================================
    
    def test_get_latency_metrics_specific_key(self, service):
        """Test getting latency metrics for a specific key."""
        # Arrange
        key = "test_key"
        service.latency_buckets[key] = deque([10.0, 15.0, 20.0, 25.0, 30.0])
        
        # Act
        result = service.get_latency_metrics(key=key)
        
        # Assert
        assert result["key"] == key
        assert result["count"] == 5
        assert result["min_ms"] == 10.0
        assert result["max_ms"] == 30.0
        assert result["avg_ms"] == 20.0
        assert result["median_ms"] == 20.0
    
    def test_get_latency_metrics_no_data(self, service):
        """Test getting latency metrics when no data exists."""
        # Arrange
        key = "test_key"
        
        # Act
        result = service.get_latency_metrics(key=key)
        
        # Assert
        assert result["key"] == key
        assert result["no_data"] is True
    
    def test_get_latency_metrics_all_keys(self, service):
        """Test getting aggregated latency metrics across all keys."""
        # Arrange
        service.latency_buckets["key1"] = deque([10.0, 20.0])
        service.latency_buckets["key2"] = deque([15.0, 25.0])
        
        # Act
        result = service.get_latency_metrics()
        
        # Assert
        assert result["total_keys"] == 2
        assert result["total_samples"] == 4
        assert result["min_ms"] == 10.0
        assert result["max_ms"] == 25.0
        assert result["avg_ms"] == 17.5
    
    def test_get_latency_metrics_percentiles(self, service):
        """Test that percentiles are calculated correctly."""
        # Arrange
        key = "test_key"
        # Create 100 latency values for percentile calculation
        latencies = [float(i) for i in range(1, 101)]
        service.latency_buckets[key] = deque(latencies)
        
        # Act
        result = service.get_latency_metrics(key=key)
        
        # Assert
        assert result["count"] == 100
        assert "p95_ms" in result
        assert "p99_ms" in result
        assert result["p95_ms"] > result["median_ms"]
        assert result["p99_ms"] > result["p95_ms"]
    
    # =========================================================================
    # Test update_per_key_metrics
    # =========================================================================
    
    def test_update_per_key_metrics_success(self, service, mock_db_session):
        """Test successful per-key metrics update."""
        # Arrange
        version_id = 1
        key = "test_key"
        
        # Mock recent predictions
        mock_prediction1 = Mock()
        mock_prediction1.is_correct = True
        mock_prediction2 = Mock()
        mock_prediction2.is_correct = False
        mock_prediction3 = Mock()
        mock_prediction3.is_correct = True
        
        mock_query = Mock()
        mock_query.filter = Mock(return_value=mock_query)
        mock_query.all = Mock(return_value=[mock_prediction1, mock_prediction2, mock_prediction3])
        mock_db_session.query = Mock(return_value=mock_query)
        
        # Mock existing metric
        mock_db_session.query.return_value.filter.return_value.first = Mock(return_value=None)
        
        # Act
        result = service.update_per_key_metrics(version_id=version_id, key=key)
        
        # Assert
        assert result is True
        mock_db_session.add.assert_called_once()
        mock_db_session.commit.assert_called_once()
    
    def test_update_per_key_metrics_updates_existing(self, service, mock_db_session):
        """Test that existing metrics are updated."""
        # Arrange
        version_id = 1
        key = "test_key"
        
        # Mock recent predictions
        mock_prediction = Mock()
        mock_prediction.is_correct = True
        
        mock_query = Mock()
        mock_query.filter = Mock(return_value=mock_query)
        mock_query.all = Mock(return_value=[mock_prediction])
        mock_db_session.query = Mock(return_value=mock_query)
        
        # Mock existing metric
        existing_metric = Mock()
        existing_metric.accuracy = 0.5
        existing_metric.drift_score = 0.1
        existing_metric.cache_hit_rate = 0.8
        mock_db_session.query.return_value.filter.return_value.first = Mock(return_value=existing_metric)
        
        # Act
        result = service.update_per_key_metrics(version_id=version_id, key=key)
        
        # Assert
        assert result is True
        assert existing_metric.accuracy == 1.0  # Updated to 100% accuracy
        mock_db_session.commit.assert_called_once()
    
    def test_update_per_key_metrics_no_predictions(self, service, mock_db_session):
        """Test update when no recent predictions exist."""
        # Arrange
        version_id = 1
        key = "test_key"
        
        mock_query = Mock()
        mock_query.filter = Mock(return_value=mock_query)
        mock_query.all = Mock(return_value=[])
        mock_db_session.query = Mock(return_value=mock_query)
        
        # Act
        result = service.update_per_key_metrics(version_id=version_id, key=key)
        
        # Assert
        assert result is True
        mock_db_session.add.assert_not_called()
    
    # =========================================================================
    # Test get_per_key_metrics
    # =========================================================================
    
    def test_get_per_key_metrics_success(self, service, mock_db_session):
        """Test successful retrieval of per-key metrics."""
        # Arrange
        version_id = 1
        
        mock_metric1 = Mock()
        mock_metric1.key = "key1"
        mock_metric1.accuracy = 0.95
        mock_metric1.drift_score = 0.1
        mock_metric1.cache_hit_rate = 0.85
        mock_metric1.updated_at = datetime.utcnow()
        
        mock_metric2 = Mock()
        mock_metric2.key = "key2"
        mock_metric2.accuracy = 0.90
        mock_metric2.drift_score = 0.2
        mock_metric2.cache_hit_rate = 0.80
        mock_metric2.updated_at = datetime.utcnow()
        
        mock_query = Mock()
        mock_query.filter = Mock(return_value=mock_query)
        mock_query.order_by = Mock(return_value=mock_query)
        mock_query.all = Mock(return_value=[mock_metric1, mock_metric2])
        mock_db_session.query = Mock(return_value=mock_query)
        
        # Act
        result = service.get_per_key_metrics(version_id=version_id)
        
        # Assert
        assert len(result) == 2
        assert result[0]["key"] == "key1"
        assert result[0]["accuracy"] == 0.95
        assert result[1]["key"] == "key2"
        assert result[1]["accuracy"] == 0.90
    
    def test_get_per_key_metrics_specific_key(self, service, mock_db_session):
        """Test retrieval of metrics for a specific key."""
        # Arrange
        version_id = 1
        key = "test_key"
        
        mock_metric = Mock()
        mock_metric.key = key
        mock_metric.accuracy = 0.95
        mock_metric.drift_score = 0.1
        mock_metric.cache_hit_rate = 0.85
        mock_metric.updated_at = datetime.utcnow()
        
        mock_query = Mock()
        mock_query.filter = Mock(return_value=mock_query)
        mock_query.order_by = Mock(return_value=mock_query)
        mock_query.all = Mock(return_value=[mock_metric])
        mock_db_session.query = Mock(return_value=mock_query)
        
        # Act
        result = service.get_per_key_metrics(version_id=version_id, key=key)
        
        # Assert
        assert len(result) == 1
        assert result[0]["key"] == key
    
    def test_get_per_key_metrics_empty(self, service, mock_db_session):
        """Test retrieval when no metrics exist."""
        # Arrange
        version_id = 1
        
        mock_query = Mock()
        mock_query.filter = Mock(return_value=mock_query)
        mock_query.order_by = Mock(return_value=mock_query)
        mock_query.all = Mock(return_value=[])
        mock_db_session.query = Mock(return_value=mock_query)
        
        # Act
        result = service.get_per_key_metrics(version_id=version_id)
        
        # Assert
        assert result == []
    
    # =========================================================================
    # Test get_benchmark_metrics
    # =========================================================================
    
    def test_get_benchmark_metrics_success(self, service, mock_db_session):
        """Test successful benchmark metrics calculation."""
        # Arrange
        version_id = 1
        baseline_latency_ms = 100.0
        
        # Mock predictions
        mock_prediction1 = Mock()
        mock_prediction1.is_correct = True
        mock_prediction2 = Mock()
        mock_prediction2.is_correct = False
        mock_prediction3 = Mock()
        mock_prediction3.is_correct = True
        
        mock_query = Mock()
        mock_query.filter = Mock(return_value=mock_query)
        mock_query.all = Mock(return_value=[mock_prediction1, mock_prediction2, mock_prediction3])
        mock_db_session.query = Mock(return_value=mock_query)
        
        # Mock latency metrics
        service.get_latency_metrics = Mock(return_value={"avg_ms": 50.0})
        
        # Mock cache stats
        service.cache_stats = {
            "key1": {"hits": 80, "misses": 20},
            "key2": {"hits": 70, "misses": 30}
        }
        
        # Act
        result = service.get_benchmark_metrics(
            version_id=version_id,
            baseline_latency_ms=baseline_latency_ms
        )
        
        # Assert
        assert result["version_id"] == version_id
        assert result["hit_rate"] == 2/3  # 2 correct out of 3
        assert result["prediction_accuracy"] == 2/3
        assert result["avg_latency_ms"] == 50.0
        assert result["speedup_factor"] == 2.0  # 100 / 50
        assert result["cache_hit_rate"] == 0.75  # 150 hits / 200 total
        assert result["total_predictions"] == 3
        assert result["correct_predictions"] == 2
    
    def test_get_benchmark_metrics_no_data(self, service, mock_db_session):
        """Test benchmark metrics when no predictions exist."""
        # Arrange
        version_id = 1
        
        mock_query = Mock()
        mock_query.filter = Mock(return_value=mock_query)
        mock_query.all = Mock(return_value=[])
        mock_db_session.query = Mock(return_value=mock_query)
        
        # Act
        result = service.get_benchmark_metrics(version_id=version_id)
        
        # Assert
        assert result["version_id"] == version_id
        assert result["no_data"] is True
    
    def test_get_benchmark_metrics_no_baseline(self, service, mock_db_session):
        """Test benchmark metrics without baseline latency."""
        # Arrange
        version_id = 1
        
        mock_prediction = Mock()
        mock_prediction.is_correct = True
        
        mock_query = Mock()
        mock_query.filter = Mock(return_value=mock_query)
        mock_query.all = Mock(return_value=[mock_prediction])
        mock_db_session.query = Mock(return_value=mock_query)
        
        service.get_latency_metrics = Mock(return_value={"avg_ms": 50.0})
        service.cache_stats = {}
        
        # Act
        result = service.get_benchmark_metrics(version_id=version_id)
        
        # Assert
        assert result["speedup_factor"] == 1.0
        assert result["latency_reduction_percent"] == 0
    
    # =========================================================================
    # Test get_accuracy_trend
    # =========================================================================
    
    def test_get_accuracy_trend_success(self, service, mock_db_session):
        """Test successful accuracy trend retrieval."""
        # Arrange
        days = 7
        
        # Create predictions at different hours
        now = datetime.utcnow()
        predictions = []
        for i in range(24):
            p = Mock()
            p.timestamp = now - timedelta(hours=i)
            p.is_correct = (i % 2 == 0)  # Alternate correct/incorrect
            predictions.append(p)
        
        mock_query = Mock()
        mock_query.filter = Mock(return_value=mock_query)
        mock_query.order_by = Mock(return_value=mock_query)
        mock_query.all = Mock(return_value=predictions)
        mock_db_session.query = Mock(return_value=mock_query)
        
        # Act
        result = service.get_accuracy_trend(days=days)
        
        # Assert
        assert len(result) > 0
        for entry in result:
            assert "timestamp" in entry
            assert "accuracy" in entry
            assert "samples" in entry
            assert 0 <= entry["accuracy"] <= 1
    
    def test_get_accuracy_trend_specific_key(self, service, mock_db_session):
        """Test accuracy trend for a specific key."""
        # Arrange
        key = "test_key"
        days = 7
        
        mock_prediction = Mock()
        mock_prediction.timestamp = datetime.utcnow()
        mock_prediction.is_correct = True
        
        mock_query = Mock()
        mock_query.filter = Mock(return_value=mock_query)
        mock_query.order_by = Mock(return_value=mock_query)
        mock_query.all = Mock(return_value=[mock_prediction])
        mock_db_session.query = Mock(return_value=mock_query)
        
        # Act
        result = service.get_accuracy_trend(key=key, days=days)
        
        # Assert
        assert len(result) > 0
    
    def test_get_accuracy_trend_empty(self, service, mock_db_session):
        """Test accuracy trend when no predictions exist."""
        # Arrange
        mock_query = Mock()
        mock_query.filter = Mock(return_value=mock_query)
        mock_query.order_by = Mock(return_value=mock_query)
        mock_query.all = Mock(return_value=[])
        mock_db_session.query = Mock(return_value=mock_query)
        
        # Act
        result = service.get_accuracy_trend()
        
        # Assert
        assert result == []
    
    # =========================================================================
    # Test get_drift_summary
    # =========================================================================
    
    def test_get_drift_summary_success(self, service):
        """Test successful drift summary retrieval."""
        # Arrange
        version_id = 1
        
        service.get_per_key_metrics = Mock(return_value=[
            {"key": "key1", "drift_score": 0.1},
            {"key": "key2", "drift_score": 0.4},
            {"key": "key3", "drift_score": 0.2},
            {"key": "key4", "drift_score": 0.5}
        ])
        
        # Act
        result = service.get_drift_summary(version_id=version_id)
        
        # Assert
        assert result["version_id"] == version_id
        assert result["total_keys"] == 4
        assert result["keys_with_drift"] == 2  # key2 and key4 have drift > 0.3
        assert result["avg_drift_score"] == 0.3  # (0.1 + 0.4 + 0.2 + 0.5) / 4
        assert result["max_drift_score"] == 0.5
        assert result["min_drift_score"] == 0.1
    
    def test_get_drift_summary_no_data(self, service):
        """Test drift summary when no metrics exist."""
        # Arrange
        version_id = 1
        
        service.get_per_key_metrics = Mock(return_value=[])
        
        # Act
        result = service.get_drift_summary(version_id=version_id)
        
        # Assert
        assert result["version_id"] == version_id
        assert result["no_data"] is True
    
    def test_get_drift_summary_no_drift_scores(self, service):
        """Test drift summary when drift scores are None."""
        # Arrange
        version_id = 1
        
        service.get_per_key_metrics = Mock(return_value=[
            {"key": "key1", "drift_score": None},
            {"key": "key2", "drift_score": None}
        ])
        
        # Act
        result = service.get_drift_summary(version_id=version_id)
        
        # Assert
        assert result["version_id"] == version_id
        assert result["total_keys"] == 2
        assert result["keys_with_drift"] == 0
        assert result["avg_drift_score"] == 0
        assert result["max_drift_score"] == 0
        assert result["min_drift_score"] == 0
    
    # =========================================================================
    # Test initialization
    # =========================================================================
    
    def test_initialization(self, mock_db_session):
        """Test service initialization."""
        # Act
        service = EnhancedObservabilityService(db_session=mock_db_session)
        
        # Assert
        assert service.db == mock_db_session
        assert service.accuracy_ewma is not None
        assert service.drift_detector is not None
        assert isinstance(service.latency_buckets, defaultdict)
        assert isinstance(service.cache_stats, defaultdict)
        assert service.baseline_latency_ms is None
    
    # =========================================================================
    # Test edge cases
    # =========================================================================
    
    def test_latency_buckets_max_length(self, service):
        """Test that latency buckets respect max length."""
        # Arrange
        key = "test_key"
        max_length = 500
        
        # Act
        for i in range(max_length + 100):
            service.record_prediction(
                version_id=1,
                key=key,
                predicted_value="value",
                latency_ms=float(i)
            )
        
        # Assert
        assert len(service.latency_buckets[key]) == max_length
        # Oldest values should be removed
        assert service.latency_buckets[key][0] == 100.0
        assert service.latency_buckets[key][-1] == 599.0
    
    def test_multiple_keys_isolation(self, service):
        """Test that metrics are isolated between keys."""
        # Arrange
        key1 = "key1"
        key2 = "key2"
        
        # Act
        service.record_cache_operation(key=key1, is_hit=True)
        service.record_cache_operation(key=key2, is_hit=False)
        
        # Assert
        assert service.cache_stats[key1]["hits"] == 1
        assert service.cache_stats[key1]["misses"] == 0
        assert service.cache_stats[key2]["hits"] == 0
        assert service.cache_stats[key2]["misses"] == 1
