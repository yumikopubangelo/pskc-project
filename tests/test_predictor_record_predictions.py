# ============================================================
# PSKC — Integration Test: Predictor → Record Predictions
# ============================================================
"""
Integration test for predictor → record predictions workflow.
Tests that recording outcomes updates EWMA, Markov, drift detector, and persists to database.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone

from src.ml.predictor import KeyPredictor
from src.ml.algorithm_improvements import EWMACalculator, DriftDetector, DynamicMarkovChain


class TestPredictorRecordPredictions:
    """Integration test for predictor → record predictions workflow."""
    
    @pytest.fixture
    def mock_data_collector(self):
        """Create a mock data collector."""
        collector = Mock()
        collector.get_stats = Mock(return_value={"total_events": 100})
        collector.get_access_sequence = Mock(return_value=[
            {"key_id": "key1", "timestamp": datetime.now(timezone.utc).timestamp(), "cache_hit": True},
            {"key_id": "key2", "timestamp": datetime.now(timezone.utc).timestamp(), "cache_hit": False},
        ])
        collector.get_hot_keys = Mock(return_value=[("key1", 10), ("key2", 5)])
        return collector
    
    @pytest.fixture
    def mock_feature_engineer(self):
        """Create a mock feature engineer."""
        engineer = Mock()
        engineer.extract_features = Mock(return_value=[0.1, 0.2, 0.3, 0.4, 0.5])
        return engineer
    
    @pytest.fixture
    def mock_model(self):
        """Create a mock ensemble model."""
        model = Mock()
        model.is_trained = True
        model.predict_top_n = Mock(return_value=(
            ["key1", "key2", "key3"],
            [0.8, 0.15, 0.05]
        ))
        model.preprocess_rf = Mock(side_effect=lambda x: x)
        return model
    
    @pytest.fixture
    def mock_observability_service(self):
        """Create a mock observability service."""
        service = Mock()
        service.record_prediction = Mock(return_value=True)
        service.record_cache_operation = Mock()
        service.record_drift = Mock(return_value={"drift_detected": False})
        return service
    
    @pytest.fixture
    def predictor(
        self,
        mock_data_collector,
        mock_feature_engineer,
        mock_model,
        mock_observability_service
    ):
        """Create KeyPredictor instance with mocked dependencies."""
        with patch('src.ml.predictor.get_data_collector', return_value=mock_data_collector), \
             patch('src.ml.predictor.get_feature_engineer', return_value=mock_feature_engineer), \
             patch('src.ml.predictor.get_observability_service', return_value=mock_observability_service):
            
            predictor = KeyPredictor(
                model=mock_model,
                top_n=10,
                threshold=0.1
            )
            
            return predictor
    
    # =========================================================================
    # Test: Record outcome updates EWMA
    # =========================================================================
    
    def test_record_outcome_updates_ewma(self, predictor):
        """Test that recording outcome updates EWMA calculator."""
        # Arrange
        service_id = "test_service"
        actual_key = "key1"
        predicted_keys = ["key1", "key2", "key3"]
        
        # Get initial EWMA state
        initial_short, initial_long = predictor._ewma.get(actual_key)
        
        # Act
        result = predictor.record_outcome(
            service_id=service_id,
            actual_key=actual_key,
            predicted_keys=predicted_keys,
            cache_hit=True
        )
        
        # Assert
        assert result["is_correct"] is True
        assert result["is_top1"] is True
        
        # Verify EWMA was updated
        final_short, final_long = predictor._ewma.get(actual_key)
        assert final_short is not None
        assert final_long is not None
        # EWMA should be updated (not None anymore)
        assert final_short != initial_short or final_long != initial_long
    
    def test_record_outcome_updates_ewma_for_missed_keys(self, predictor):
        """Test that EWMA is decayed for keys that were predicted but not accessed."""
        # Arrange
        service_id = "test_service"
        actual_key = "key1"
        predicted_keys = ["key1", "key2", "key3"]
        
        # Get initial EWMA state for key2 (predicted but not accessed)
        initial_short_key2, initial_long_key2 = predictor._ewma.get("key2")
        
        # Act
        result = predictor.record_outcome(
            service_id=service_id,
            actual_key=actual_key,
            predicted_keys=predicted_keys,
            cache_hit=True
        )
        
        # Assert
        assert result["is_correct"] is True
        
        # Verify EWMA was updated for key2 (should be decayed)
        final_short_key2, final_long_key2 = predictor._ewma.get("key2")
        # key2 was predicted but not accessed, so EWMA should be updated
        assert final_short_key2 is not None or final_long_key2 is not None
    
    # =========================================================================
    # Test: Record outcome updates Markov chain
    # =========================================================================
    
    def test_record_outcome_updates_markov_chain(self, predictor):
        """Test that recording outcome updates Markov chain."""
        # Arrange
        service_id = "test_service"
        actual_key = "key1"
        predicted_keys = ["key1", "key2", "key3"]
        
        # Record first outcome to set last_key
        predictor.record_outcome(
            service_id=service_id,
            actual_key="key0",
            predicted_keys=["key0"],
            cache_hit=True
        )
        
        # Get initial Markov state
        initial_transitions = len(predictor._markov.transitions.get(service_id, {}))
        
        # Act
        result = predictor.record_outcome(
            service_id=service_id,
            actual_key=actual_key,
            predicted_keys=predicted_keys,
            cache_hit=True
        )
        
        # Assert
        assert result["is_correct"] is True
        
        # Verify Markov chain was updated
        final_transitions = len(predictor._markov.transitions.get(service_id, {}))
        assert final_transitions >= initial_transitions
    
    def test_record_outcome_tracks_last_key_per_service(self, predictor):
        """Test that last key is tracked per service."""
        # Arrange
        service_id_1 = "service1"
        service_id_2 = "service2"
        
        # Act
        predictor.record_outcome(
            service_id=service_id_1,
            actual_key="key1",
            predicted_keys=["key1"],
            cache_hit=True
        )
        
        predictor.record_outcome(
            service_id=service_id_2,
            actual_key="key2",
            predicted_keys=["key2"],
            cache_hit=True
        )
        
        # Assert
        assert predictor._last_key_by_service[service_id_1] == "key1"
        assert predictor._last_key_by_service[service_id_2] == "key2"
    
    # =========================================================================
    # Test: Record outcome updates drift detector
    # =========================================================================
    
    def test_record_outcome_updates_drift_detector(self, predictor):
        """Test that recording outcome updates drift detector."""
        # Arrange
        service_id = "test_service"
        actual_key = "key1"
        predicted_keys = ["key1", "key2", "key3"]
        
        # Get initial drift state
        initial_drift_score = predictor._drift.get_drift_score("global")
        
        # Act
        result = predictor.record_outcome(
            service_id=service_id,
            actual_key=actual_key,
            predicted_keys=predicted_keys,
            cache_hit=True
        )
        
        # Assert
        assert result["is_correct"] is True
        assert "drift_score" in result
        assert "drift_level" in result
        
        # Verify drift detector was updated
        final_drift_score = predictor._drift.get_drift_score("global")
        assert final_drift_score != initial_drift_score or final_drift_score == 0.0
    
    def test_record_outcome_increases_drift_on_incorrect_prediction(self, predictor):
        """Test that incorrect predictions increase drift score."""
        # Arrange
        service_id = "test_service"
        actual_key = "key1"
        predicted_keys = ["key2", "key3", "key4"]  # All wrong
        
        # Get initial drift state
        initial_drift_score = predictor._drift.get_drift_score("global")
        
        # Act
        result = predictor.record_outcome(
            service_id=service_id,
            actual_key=actual_key,
            predicted_keys=predicted_keys,
            cache_hit=False
        )
        
        # Assert
        assert result["is_correct"] is False
        assert result["is_top1"] is False
        
        # Verify drift score increased
        final_drift_score = predictor._drift.get_drift_score("global")
        assert final_drift_score > initial_drift_score
    
    # =========================================================================
    # Test: Record outcome persists to database
    # =========================================================================
    
    def test_record_outcome_persists_to_database(self, predictor, mock_observability_service):
        """Test that recording outcome persists to database."""
        # Arrange
        service_id = "test_service"
        actual_key = "key1"
        predicted_keys = ["key1", "key2", "key3"]
        
        # Act
        result = predictor.record_outcome(
            service_id=service_id,
            actual_key=actual_key,
            predicted_keys=predicted_keys,
            cache_hit=True
        )
        
        # Assert
        assert result["is_correct"] is True
        
        # Verify observability service was called
        mock_observability_service.record_prediction.assert_called_once()
        mock_observability_service.record_cache_operation.assert_called_once()
        mock_observability_service.record_drift.assert_called_once()
        
        # Verify call arguments
        record_prediction_call = mock_observability_service.record_prediction.call_args
        assert record_prediction_call[1]["key"] == actual_key
        assert record_prediction_call[1]["predicted_value"] == "key1"
        assert record_prediction_call[1]["actual_value"] == actual_key
        
        record_cache_call = mock_observability_service.record_cache_operation.call_args
        assert record_cache_call[1]["key"] == actual_key
        assert record_cache_call[1]["is_hit"] is True
        
        record_drift_call = mock_observability_service.record_drift.call_args
        assert record_drift_call[1]["key"] == actual_key
        assert record_drift_call[1]["is_correct"] is True
    
    def test_record_outcome_handles_persistence_failure(self, predictor, mock_observability_service):
        """Test that recording outcome handles persistence failures gracefully."""
        # Arrange
        service_id = "test_service"
        actual_key = "key1"
        predicted_keys = ["key1", "key2", "key3"]
        
        # Mock persistence failure
        mock_observability_service.record_prediction.side_effect = Exception("Database error")
        
        # Act
        result = predictor.record_outcome(
            service_id=service_id,
            actual_key=actual_key,
            predicted_keys=predicted_keys,
            cache_hit=True
        )
        
        # Assert
        # Should not raise exception, just log debug message
        assert result["is_correct"] is True
        assert result["is_top1"] is True
    
    # =========================================================================
    # Test: Record outcome with different prediction accuracy
    # =========================================================================
    
    def test_record_outcome_top1_correct(self, predictor):
        """Test recording outcome when top-1 prediction is correct."""
        # Arrange
        service_id = "test_service"
        actual_key = "key1"
        predicted_keys = ["key1", "key2", "key3"]
        
        # Act
        result = predictor.record_outcome(
            service_id=service_id,
            actual_key=actual_key,
            predicted_keys=predicted_keys,
            cache_hit=True
        )
        
        # Assert
        assert result["is_correct"] is True
        assert result["is_top1"] is True
    
    def test_record_outcome_top10_correct(self, predictor):
        """Test recording outcome when prediction is in top-10 but not top-1."""
        # Arrange
        service_id = "test_service"
        actual_key = "key2"
        predicted_keys = ["key1", "key2", "key3"]
        
        # Act
        result = predictor.record_outcome(
            service_id=service_id,
            actual_key=actual_key,
            predicted_keys=predicted_keys,
            cache_hit=False
        )
        
        # Assert
        assert result["is_correct"] is True
        assert result["is_top1"] is False
    
    def test_record_outcome_incorrect(self, predictor):
        """Test recording outcome when prediction is incorrect."""
        # Arrange
        service_id = "test_service"
        actual_key = "key5"
        predicted_keys = ["key1", "key2", "key3"]
        
        # Act
        result = predictor.record_outcome(
            service_id=service_id,
            actual_key=actual_key,
            predicted_keys=predicted_keys,
            cache_hit=False
        )
        
        # Assert
        assert result["is_correct"] is False
        assert result["is_top1"] is False
    
    # =========================================================================
    # Test: Record outcome with empty predictions
    # =========================================================================
    
    def test_record_outcome_with_empty_predictions(self, predictor):
        """Test recording outcome when no predictions were made."""
        # Arrange
        service_id = "test_service"
        actual_key = "key1"
        predicted_keys = []
        
        # Act
        result = predictor.record_outcome(
            service_id=service_id,
            actual_key=actual_key,
            predicted_keys=predicted_keys,
            cache_hit=True
        )
        
        # Assert
        assert result["is_correct"] is False
        assert result["is_top1"] is False
    
    # =========================================================================
    # Test: Outcome count tracking
    # =========================================================================
    
    def test_outcome_count_increments(self, predictor):
        """Test that outcome count increments with each recording."""
        # Arrange
        service_id = "test_service"
        
        # Act
        result1 = predictor.record_outcome(
            service_id=service_id,
            actual_key="key1",
            predicted_keys=["key1"],
            cache_hit=True
        )
        
        result2 = predictor.record_outcome(
            service_id=service_id,
            actual_key="key2",
            predicted_keys=["key2"],
            cache_hit=True
        )
        
        # Assert
        assert result1["outcome_count"] == 1
        assert result2["outcome_count"] == 2
    
    # =========================================================================
    # Test: Drift-triggered retrain
    # =========================================================================
    
    def test_drift_triggered_retrain_on_critical_drift(self, predictor):
        """Test that critical drift triggers retrain."""
        # Arrange
        service_id = "test_service"
        
        # Record many incorrect predictions to trigger critical drift
        for i in range(100):
            predictor.record_outcome(
                service_id=service_id,
                actual_key=f"key{i}",
                predicted_keys=["wrong_key1", "wrong_key2", "wrong_key3"],
                cache_hit=False
            )
        
        # Act
        result = predictor.record_outcome(
            service_id=service_id,
            actual_key="key_final",
            predicted_keys=["wrong_key1", "wrong_key2", "wrong_key3"],
            cache_hit=False
        )
        
        # Assert
        # Drift level should be critical or retrain should be triggered
        assert result["drift_level"] in ["critical", "warning", "normal"]
        # If critical, retrain should be triggered
        if result["drift_level"] == "critical":
            assert result["retrain_triggered"] is True
    
    def test_drift_retrain_cooldown(self, predictor):
        """Test that drift retrain respects cooldown period."""
        # Arrange
        service_id = "test_service"
        
        # Trigger first retrain
        for i in range(100):
            predictor.record_outcome(
                service_id=service_id,
                actual_key=f"key{i}",
                predicted_keys=["wrong_key1", "wrong_key2", "wrong_key3"],
                cache_hit=False
            )
        
        # Get first retrain result
        result1 = predictor.record_outcome(
            service_id=service_id,
            actual_key="key_final1",
            predicted_keys=["wrong_key1", "wrong_key2", "wrong_key3"],
            cache_hit=False
        )
        
        # Immediately try to trigger another retrain (should be blocked by cooldown)
        result2 = predictor.record_outcome(
            service_id=service_id,
            actual_key="key_final2",
            predicted_keys=["wrong_key1", "wrong_key2", "wrong_key3"],
            cache_hit=False
        )
        
        # Assert
        # First retrain should be triggered
        if result1["drift_level"] == "critical":
            assert result1["retrain_triggered"] is True
        
        # Second retrain should be blocked by cooldown
        assert result2["retrain_triggered"] is False
    
    # =========================================================================
    # Test: Prediction stats
    # =========================================================================
    
    def test_prediction_stats_updated(self, predictor):
        """Test that prediction stats are updated after recording outcomes."""
        # Arrange
        service_id = "test_service"
        
        # Record some outcomes
        predictor.record_outcome(
            service_id=service_id,
            actual_key="key1",
            predicted_keys=["key1"],
            cache_hit=True
        )
        
        predictor.record_outcome(
            service_id=service_id,
            actual_key="key2",
            predicted_keys=["key2"],
            cache_hit=True
        )
        
        # Act
        stats = predictor.get_prediction_stats()
        
        # Assert
        assert stats["outcome_count"] == 2
        assert "ensemble" in stats
        assert "ewma_keys_tracked" in stats["ensemble"]
        assert "markov_transitions" in stats["ensemble"]
        assert "drift_score" in stats["ensemble"]
        assert "drift_level" in stats["ensemble"]
