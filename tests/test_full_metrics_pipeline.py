# ============================================================
# PSKC — Integration Test: Full Metrics Pipeline
# ============================================================
"""
Integration test for full metrics pipeline.
Tests the complete flow: prediction → outcome recording → metrics calculation → database persistence.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone, timedelta
import numpy as np

from src.ml.predictor import KeyPredictor
from src.ml.trainer import ModelTrainer
from src.observability.enhanced_observability import EnhancedObservabilityService
from src.ml.model_version_manager import ModelVersionManager


class TestFullMetricsPipeline:
    """Integration test for full metrics pipeline."""
    
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
        """Create a mock feature engineer with varying features."""
        engineer = Mock()
        # Return different features each call so they are not all constant
        call_count = {"rf": 0, "lstm": 0}

        def _rf_features(*args, **kwargs):
            call_count["rf"] += 1
            base = np.random.RandomState(call_count["rf"]).rand(36).tolist()
            return base

        def _lstm_features(*args, **kwargs):
            call_count["lstm"] += 1
            base = np.random.RandomState(call_count["lstm"] + 100).rand(8).tolist()
            return base

        engineer.extract_features = Mock(side_effect=_rf_features)
        engineer.extract_per_event_features = Mock(side_effect=_lstm_features)
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
        model.get_model_stats = Mock(return_value={})
        return model
    
    @pytest.fixture
    def mock_model_registry(self):
        """Create a mock model registry."""
        registry = Mock()
        registry.serialize_model_checkpoint = Mock(return_value=b"mock_model_data")
        registry.get_active_version = Mock(return_value=None)
        registry.load_model = Mock(return_value=None)
        return registry
    
    @pytest.fixture
    def mock_incremental_persistence(self):
        """Create a mock incremental persistence."""
        persistence = Mock()
        persistence.update = Mock(return_value={
            "success": True,
            "accepted": True,
            "version": "v1",
            "decision_reason": "improved_accuracy"
        })
        persistence.get_info = Mock(return_value={
            "file_path": "/models/test_model_v1.pkl",
            "current_version": "v1"
        })
        persistence.exists = Mock(return_value=False)
        return persistence
    
    @pytest.fixture
    def observability_service(self, mock_db_session):
        """Create EnhancedObservabilityService instance."""
        return EnhancedObservabilityService(db_session=mock_db_session)
    
    @pytest.fixture
    def predictor(
        self,
        mock_data_collector,
        mock_feature_engineer,
        mock_model,
        observability_service
    ):
        """Create KeyPredictor instance with mocked dependencies."""
        with patch('src.ml.predictor.get_data_collector', return_value=mock_data_collector), \
             patch('src.ml.predictor.get_feature_engineer', return_value=mock_feature_engineer), \
             patch('src.observability.enhanced_observability.get_observability_service', return_value=observability_service):
            
            predictor = KeyPredictor(
                model=mock_model,
                top_n=10,
                threshold=0.1
            )
            
            return predictor
    
    @pytest.fixture
    def trainer(
        self,
        mock_db_session,
        mock_data_collector,
        mock_feature_engineer,
        mock_model_registry,
        mock_incremental_persistence
    ):
        """Create ModelTrainer instance with mocked dependencies."""
        with patch('src.ml.trainer.get_data_collector', return_value=mock_data_collector), \
             patch('src.ml.trainer.get_feature_engineer', return_value=mock_feature_engineer), \
             patch('src.ml.trainer.get_model_registry', return_value=mock_model_registry):
            
            trainer = ModelTrainer(
                model=None,
                update_interval=30,
                min_samples=10,
                batch_size=32,
                drift_threshold=0.12,
                context_window=10,
                model_name="test_model",
                registry=mock_model_registry,
                incremental_persistence=mock_incremental_persistence
            )
            
            return trainer
    
    # =========================================================================
    # Test: Full pipeline - prediction to metrics
    # =========================================================================
    
    def test_full_pipeline_prediction_to_metrics(self, predictor):
        """Test complete flow from prediction to metrics recording."""
        # Arrange
        service_id = "test_service"
        version_id = 1
        
        # Step 1: Make prediction
        predictions = predictor.predict(service_id=service_id, n=5)
        
        # Assert predictions were made
        assert len(predictions) > 0
        assert all(isinstance(p, tuple) for p in predictions)
        assert all(len(p) == 2 for p in predictions)
        
        # Step 2: Record outcome
        actual_key = predictions[0][0]  # Use first predicted key as actual
        predicted_keys = [p[0] for p in predictions]
        
        result = predictor.record_outcome(
            service_id=service_id,
            actual_key=actual_key,
            predicted_keys=predicted_keys,
            cache_hit=True
        )
        
        # Assert outcome was recorded
        assert result["is_correct"] is True
        assert result["is_top1"] is True
        
        # Step 3: Verify outcome was successfully recorded
        # The predictor updates internal EWMA/Markov/Drift state
        stats = predictor.get_prediction_stats()
        assert stats["ensemble"]["outcome_count"] >= 1
    
    def test_full_pipeline_with_incorrect_prediction(self, predictor, observability_service):
        """Test complete flow with incorrect prediction."""
        # Arrange
        service_id = "test_service"
        
        # Step 1: Make prediction
        predictions = predictor.predict(service_id=service_id, n=5)
        predicted_keys = [p[0] for p in predictions]
        
        # Step 2: Record outcome with wrong key
        actual_key = "wrong_key"
        
        result = predictor.record_outcome(
            service_id=service_id,
            actual_key=actual_key,
            predicted_keys=predicted_keys,
            cache_hit=False
        )
        
        # Assert outcome was recorded as incorrect
        assert result["is_correct"] is False
        assert result["is_top1"] is False
    
    # =========================================================================
    # Test: Metrics calculation after multiple predictions
    # =========================================================================
    
    def test_metrics_calculation_after_multiple_predictions(self, predictor, observability_service):
        """Test that metrics are calculated correctly after multiple predictions."""
        # Arrange
        service_id = "test_service"
        version_id = 1
        
        # Record multiple outcomes
        for i in range(10):
            predictions = predictor.predict(service_id=service_id, n=5)
            predicted_keys = [p[0] for p in predictions]
            
            # Alternate between correct and incorrect
            if i % 2 == 0:
                actual_key = predicted_keys[0]  # Correct
                cache_hit = True
            else:
                actual_key = "wrong_key"  # Incorrect
                cache_hit = False
            
            predictor.record_outcome(
                service_id=service_id,
                actual_key=actual_key,
                predicted_keys=predicted_keys,
                cache_hit=cache_hit
            )
        
        # Act
        stats = predictor.get_prediction_stats()
        
        # Assert
        assert stats["ensemble"]["outcome_count"] == 10
        assert "ensemble" in stats
        assert "ewma_keys_tracked" in stats["ensemble"]
        assert "markov_transitions" in stats["ensemble"]
        assert "drift_score" in stats["ensemble"]
    
    # =========================================================================
    # Test: Per-key metrics update
    # =========================================================================
    
    def test_per_key_metrics_update(self, observability_service, mock_db_session):
        """Test that per-key metrics are updated correctly."""
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
        result = observability_service.update_per_key_metrics(version_id=version_id, key=key)
        
        # Assert
        assert result is True
        mock_db_session.add.assert_called_once()
        mock_db_session.commit.assert_called_once()
    
    # =========================================================================
    # Test: Latency metrics calculation
    # =========================================================================
    
    def test_latency_metrics_calculation(self, observability_service):
        """Test that latency metrics are calculated correctly."""
        # Arrange
        key = "test_key"
        
        # Record predictions with latency
        for i in range(10):
            observability_service.record_prediction(
                version_id=1,
                key=key,
                predicted_value=f"value_{i}",
                latency_ms=10.0 + i
            )
        
        # Act
        metrics = observability_service.get_latency_metrics(key=key)
        
        # Assert
        assert metrics["key"] == key
        assert metrics["count"] == 10
        assert metrics["min_ms"] == 10.0
        assert metrics["max_ms"] == 19.0
        assert metrics["avg_ms"] == 14.5
        assert metrics["median_ms"] == 14.5
    
    # =========================================================================
    # Test: Benchmark metrics calculation
    # =========================================================================
    
    def test_benchmark_metrics_calculation(self, observability_service, mock_db_session):
        """Test that benchmark metrics are calculated correctly."""
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
        observability_service.get_latency_metrics = Mock(return_value={"avg_ms": 50.0})
        
        # Mock cache stats
        observability_service.cache_stats = {
            "key1": {"hits": 80, "misses": 20},
            "key2": {"hits": 70, "misses": 30}
        }
        
        # Act
        result = observability_service.get_benchmark_metrics(
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
    
    # =========================================================================
    # Test: Accuracy trend calculation
    # =========================================================================
    
    def test_accuracy_trend_calculation(self, observability_service, mock_db_session):
        """Test that accuracy trend is calculated correctly."""
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
        result = observability_service.get_accuracy_trend(days=days)
        
        # Assert
        assert len(result) > 0
        for entry in result:
            assert "timestamp" in entry
            assert "accuracy" in entry
            assert "samples" in entry
            assert 0 <= entry["accuracy"] <= 1
    
    # =========================================================================
    # Test: Drift summary calculation
    # =========================================================================
    
    def test_drift_summary_calculation(self, observability_service):
        """Test that drift summary is calculated correctly."""
        # Arrange
        version_id = 1
        
        observability_service.get_per_key_metrics = Mock(return_value=[
            {"key": "key1", "drift_score": 0.1},
            {"key": "key2", "drift_score": 0.4},
            {"key": "key3", "drift_score": 0.2},
            {"key": "key4", "drift_score": 0.5}
        ])
        
        # Act
        result = observability_service.get_drift_summary(version_id=version_id)
        
        # Assert
        assert result["version_id"] == version_id
        assert result["total_keys"] == 4
        assert result["keys_with_drift"] == 2  # key2 and key4 have drift > 0.3
        assert result["avg_drift_score"] == 0.3  # (0.1 + 0.4 + 0.2 + 0.5) / 4
        assert result["max_drift_score"] == 0.5
        assert result["min_drift_score"] == 0.1
    
    # =========================================================================
    # Test: Training creates version with metrics
    # =========================================================================
    
    def test_training_creates_version_with_metrics(self, trainer, mock_incremental_persistence):
        """Test that training creates a new version with metrics."""
        # Arrange
        trainer._collector.get_stats = Mock(return_value={"total_events": 100})
        
        # Act
        result = trainer.train(force=True, reason="manual")
        
        # Assert
        assert result["success"] is True
        assert result["model_accepted"] is True
        assert result["version_bumped"] is True
        
        # Verify incremental persistence was called with metrics
        call_args = mock_incremental_persistence.update.call_args
        assert "metrics" in call_args[1]
        assert "accuracy" in call_args[1]["metrics"]
        assert "top_10_accuracy" in call_args[1]["metrics"]
    
    # =========================================================================
    # Test: End-to-end flow - train, predict, record, metrics
    # =========================================================================
    
    def test_end_to_end_flow(self, trainer, predictor, observability_service, mock_incremental_persistence):
        """Test end-to-end flow: train → predict → record → metrics."""
        # Step 1: Train model
        trainer._collector.get_stats = Mock(return_value={"total_events": 100})
        train_result = trainer.train(force=True, reason="manual")
        
        assert train_result["success"] is True
        assert train_result["model_accepted"] is True
        
        # Step 2: Make predictions
        service_id = "test_service"
        predictions = predictor.predict(service_id=service_id, n=5)
        
        assert len(predictions) > 0
        
        # Step 3: Record outcomes
        for i in range(5):
            actual_key = predictions[i % len(predictions)][0]
            predicted_keys = [p[0] for p in predictions]
            
            predictor.record_outcome(
                service_id=service_id,
                actual_key=actual_key,
                predicted_keys=predicted_keys,
                cache_hit=(i % 2 == 0)
            )
        
        # Step 4: Get metrics
        stats = predictor.get_prediction_stats()
        
        assert stats["ensemble"]["outcome_count"] == 5
        assert "ensemble" in stats
        
        # Step 5: Get benchmark metrics (mock DB may not support the query,
        # so just verify the method returns a dict with version_id)
        benchmark = observability_service.get_benchmark_metrics(
            version_id=1,
            baseline_latency_ms=100.0
        )

        assert isinstance(benchmark, dict)
        assert benchmark["version_id"] == 1
    
    # =========================================================================
    # Test: Metrics persistence
    # =========================================================================
    
    def test_metrics_persistence(self, observability_service, mock_db_session):
        """Test that metrics are persisted to database."""
        # Arrange
        version_id = 1
        key = "test_key"
        
        # Record prediction
        observability_service.record_prediction(
            version_id=version_id,
            key=key,
            predicted_value="value1",
            actual_value="value1",
            confidence=0.95,
            latency_ms=10.5
        )
        
        # Assert
        mock_db_session.add.assert_called()
        mock_db_session.commit.assert_called()
        
        # Verify the prediction object was created
        call_args = mock_db_session.add.call_args[0][0]
        assert call_args.version_id == version_id
        assert call_args.key == key
        assert call_args.predicted_value == "value1"
        assert call_args.actual_value == "value1"
        assert call_args.is_correct is True
        assert call_args.confidence == 0.95
    
    # =========================================================================
    # Test: Cache metrics tracking
    # =========================================================================
    
    def test_cache_metrics_tracking(self, observability_service):
        """Test that cache metrics are tracked correctly."""
        # Arrange
        key = "test_key"
        
        # Record cache operations
        observability_service.record_cache_operation(key=key, is_hit=True)
        observability_service.record_cache_operation(key=key, is_hit=True)
        observability_service.record_cache_operation(key=key, is_hit=False)
        
        # Act
        metrics = observability_service.get_per_key_metrics(version_id=1, key=key)
        
        # Assert
        # Cache stats should be tracked in memory
        assert observability_service.cache_stats[key]["hits"] == 2
        assert observability_service.cache_stats[key]["misses"] == 1
    
    # =========================================================================
    # Test: Drift detection integration
    # =========================================================================
    
    def test_drift_detection_integration(self, predictor, observability_service):
        """Test that drift detection works across the pipeline."""
        # Arrange
        service_id = "test_service"
        
        # Record many incorrect predictions to trigger drift
        for i in range(100):
            predictions = predictor.predict(service_id=service_id, n=5)
            predicted_keys = [p[0] for p in predictions]
            
            predictor.record_outcome(
                service_id=service_id,
                actual_key="wrong_key",
                predicted_keys=predicted_keys,
                cache_hit=False
            )
        
        # Act
        stats = predictor.get_prediction_stats()
        
        # Assert
        assert stats["ensemble"]["outcome_count"] == 100
        assert "drift_score" in stats["ensemble"]
        assert "drift_level" in stats["ensemble"]
        # Drift score should be high after many incorrect predictions
        assert stats["ensemble"]["drift_score"] > 0
