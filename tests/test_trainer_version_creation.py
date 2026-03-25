# ============================================================
# PSKC — Integration Test: Trainer → Version Creation
# ============================================================
"""
Integration test for trainer → version creation workflow.
Tests that training creates a new model version and sets it as active.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone
import numpy as np

from src.ml.trainer import ModelTrainer
from src.ml.model_version_manager import ModelVersionManager
from src.database.models import ModelVersion


class TestTrainerVersionCreation:
    """Integration test for trainer → version creation workflow."""
    
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
        """Create a mock data collector with sample data."""
        collector = Mock()
        
        # Create sample training data
        sample_data = []
        for i in range(100):
            sample_data.append({
                "key_id": f"key_{i % 10}",
                "timestamp": datetime.now(timezone.utc).timestamp() - (100 - i),
                "cache_hit": i % 3 == 0,  # ~33% hit rate
                "latency_ms": 10.0 + (i % 5),
                "service_id": "test_service"
            })
        
        collector.get_stats = Mock(return_value={"total_events": 100})
        collector.get_access_sequence = Mock(return_value=sample_data)
        
        return collector
    
    @pytest.fixture
    def mock_feature_engineer(self):
        """Create a mock feature engineer."""
        engineer = Mock()
        
        # Mock feature extraction
        def extract_features(context):
            # Return random features for each context
            return np.random.rand(20)
        
        def extract_per_event_features(event, base_ts):
            # Return random features for each event
            return np.random.rand(8)
        
        engineer.extract_features = Mock(side_effect=extract_features)
        engineer.extract_per_event_features = Mock(side_effect=extract_per_event_features)
        
        return engineer
    
    @pytest.fixture
    def mock_model_registry(self):
        """Create a mock model registry."""
        registry = Mock()
        
        # Mock serialize_model_checkpoint
        def serialize_model_checkpoint(model):
            return b"mock_model_data"
        
        registry.serialize_model_checkpoint = Mock(side_effect=serialize_model_checkpoint)
        
        # Mock get_active_version
        registry.get_active_version = Mock(return_value=None)
        
        # Mock load_model
        registry.load_model = Mock(return_value=None)
        
        return registry
    
    @pytest.fixture
    def mock_incremental_persistence(self):
        """Create a mock incremental persistence."""
        persistence = Mock()
        
        # Mock update method
        def update(model_data, reason, metrics, training_info):
            return {
                "success": True,
                "accepted": True,
                "version": "v1",
                "decision_reason": "improved_accuracy"
            }
        
        persistence.update = Mock(side_effect=update)
        persistence.get_info = Mock(return_value={
            "file_path": "/models/test_model_v1.pkl",
            "current_version": "v1"
        })
        persistence.exists = Mock(return_value=False)
        
        return persistence
    
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
    # Test: Training creates new version
    # =========================================================================
    
    def test_training_creates_new_version(self, trainer, mock_incremental_persistence):
        """Test that training creates a new model version."""
        # Arrange
        trainer._collector.get_stats = Mock(return_value={"total_events": 100})
        
        # Act
        result = trainer.train(force=True, reason="manual")
        
        # Assert
        assert result["success"] is True
        assert result["model_accepted"] is True
        assert result["version_bumped"] is True
        assert result["registry_version"] == "v1"
        
        # Verify incremental persistence was called
        mock_incremental_persistence.update.assert_called_once()
        
        # Verify the call arguments
        call_args = mock_incremental_persistence.update.call_args
        assert call_args[1]["reason"] == "manual"
        assert "accuracy" in call_args[1]["metrics"]
        assert "sample_count" in call_args[1]["training_info"]
    
    def test_training_records_metrics(self, trainer, mock_incremental_persistence):
        """Test that training records metrics for the new version."""
        # Arrange
        trainer._collector.get_stats = Mock(return_value={"total_events": 100})
        
        # Act
        result = trainer.train(force=True, reason="manual")
        
        # Assert
        assert result["success"] is True
        
        # Verify metrics were recorded
        call_args = mock_incremental_persistence.update.call_args
        metrics = call_args[1]["metrics"]
        
        assert "accuracy" in metrics
        assert "top_10_accuracy" in metrics
        assert isinstance(metrics["accuracy"], float)
        assert isinstance(metrics["top_10_accuracy"], float)
        assert 0 <= metrics["accuracy"] <= 1
        assert 0 <= metrics["top_10_accuracy"] <= 1
    
    def test_training_sets_active_version(self, trainer):
        """Test that training sets the new version as active."""
        # Arrange
        trainer._collector.get_stats = Mock(return_value={"total_events": 100})
        
        # Act
        result = trainer.train(force=True, reason="manual")
        
        # Assert
        assert result["success"] is True
        assert result["model_accepted"] is True
        
        # Verify active version was updated
        assert trainer._active_model_version == "v1"
        assert trainer._active_artifact_path == "/models/test_model_v1.pkl"
        assert trainer._model_source == "incremental"
    
    def test_training_with_different_reasons(self, trainer, mock_incremental_persistence):
        """Test training with different reasons (scheduled, drift, manual)."""
        # Arrange
        trainer._collector.get_stats = Mock(return_value={"total_events": 100})
        
        # Test scheduled training
        result_scheduled = trainer.train(force=True, reason="scheduled")
        assert result_scheduled["success"] is True
        assert result_scheduled["reason"] == "scheduled"
        
        # Test drift-based online training (separate path, no version bump)
        fake_predictor = Mock()
        fake_predictor.run_online_learning = Mock(return_value={
            "success": True,
            "reason": "drift_detected",
            "training_path": "online",
            "sample_count": 25,
        })
        with patch('src.ml.predictor.get_key_predictor', return_value=fake_predictor):
            result_drift = trainer.train(force=True, reason="drift_detected")
        assert result_drift["success"] is True
        assert result_drift["reason"] == "drift_detected"
        assert result_drift["training_path"] == "online"
        
        # Test manual training
        result_manual = trainer.train(force=True, reason="manual")
        assert result_manual["success"] is True
        assert result_manual["reason"] == "manual"
        
        # Only scheduled/manual go through persisted full retraining
        assert mock_incremental_persistence.update.call_count == 2
    
    # =========================================================================
    # Test: Training with insufficient samples
    # =========================================================================
    
    def test_training_with_insufficient_samples(self, trainer):
        """Test that training fails with insufficient samples."""
        # Arrange
        trainer._collector.get_stats = Mock(return_value={"total_events": 5})
        trainer._min_samples = 10
        
        # Act
        result = trainer.train(force=False, reason="manual")
        
        # Assert
        assert result["success"] is False
        assert result["reason"] == "insufficient_samples"
        assert result["sample_count"] == 5
        assert result["required"] == 10
    
    def test_training_forced_with_insufficient_samples(self, trainer, mock_incremental_persistence):
        """Test that forced training succeeds even with insufficient samples."""
        # Arrange
        trainer._collector.get_stats = Mock(return_value={"total_events": 5})
        trainer._min_samples = 10
        
        # Act
        result = trainer.train(force=True, reason="manual")
        
        # Assert
        assert result["success"] is True
        assert result["model_accepted"] is True
    
    # =========================================================================
    # Test: Training with no data
    # =========================================================================
    
    def test_training_with_no_data(self, trainer):
        """Test that training fails when no data is available."""
        # Arrange
        trainer._collector.get_stats = Mock(return_value={"total_events": 100})
        trainer._collector.get_access_sequence = Mock(return_value=[])
        
        # Act
        result = trainer.train(force=True, reason="manual")
        
        # Assert
        assert result["success"] is False
        assert result["reason"] == "no_data"
    
    # =========================================================================
    # Test: Training history
    # =========================================================================
    
    def test_training_history_updated(self, trainer, mock_incremental_persistence):
        """Test that training history is updated after successful training."""
        # Arrange
        trainer._collector.get_stats = Mock(return_value={"total_events": 100})
        
        # Act
        result = trainer.train(force=True, reason="manual")
        
        # Assert
        assert result["success"] is True
        
        # Verify training history was updated
        history = trainer.get_training_history()
        assert len(history) > 0
        
        # Verify the latest entry
        latest = history[-1]
        assert latest["success"] is True
        assert latest["reason"] == "manual"
        assert "val_accuracy" in latest
        assert "sample_count" in latest
    
    # =========================================================================
    # Test: Model stats
    # =========================================================================
    
    def test_model_stats_updated(self, trainer):
        """Test that model stats are updated after training."""
        # Arrange
        trainer._collector.get_stats = Mock(return_value={"total_events": 100})
        
        # Act
        result = trainer.train(force=True, reason="manual")
        
        # Assert
        assert result["success"] is True
        
        # Verify model stats
        stats = trainer.get_stats()
        assert stats["training_count"] == 1
        assert stats["active_version"] == "v1"
        assert stats["artifact_path"] == "/models/test_model_v1.pkl"
        assert stats["model_source"] == "incremental"
    
    # =========================================================================
    # Test: Drift detector reset
    # =========================================================================
    
    def test_drift_detector_reset_after_training(self, trainer):
        """Test that drift detector is reset after training."""
        # Arrange
        trainer._collector.get_stats = Mock(return_value={"total_events": 100})
        
        # Record some cache outcomes to build up drift detector state
        for i in range(50):
            trainer.record_cache_outcome(f"key_{i}", i % 2 == 0)
        
        # Get initial drift stats
        initial_stats = trainer._drift_detector.get_stats()
        initial_short_hits = len(trainer._drift_detector._short_hits)
        
        # Act
        result = trainer.train(force=True, reason="manual")
        
        # Assert
        assert result["success"] is True
        
        # Verify drift detector was reset
        final_stats = trainer._drift_detector.get_stats()
        assert len(trainer._drift_detector._short_hits) == 0
        assert len(trainer._drift_detector._adaptive_window) == 0
    
    # =========================================================================
    # Test: Training with accuracy below threshold
    # =========================================================================
    
    def test_training_with_accuracy_below_threshold(self, trainer, mock_incremental_persistence):
        """Test that model is rejected if accuracy is below threshold."""
        # Arrange
        trainer._collector.get_stats = Mock(return_value={"total_events": 100})
        trainer._min_accuracy_for_active = 0.9  # Set very high threshold
        
        # Mock model to return low accuracy
        mock_model = Mock()
        mock_model.is_trained = True
        mock_model.predict_top_n = Mock(return_value=(
            ["key_0"],  # Always predict wrong
            [0.1]
        ))
        mock_model.get_model_stats = Mock(return_value={})
        trainer._model = mock_model
        
        # Act
        result = trainer.train(force=True, reason="manual")
        
        # Assert
        assert result["success"] is True
        assert result["reason"] == "accuracy_below_threshold"
        assert result["model_accepted"] is False
        assert result["version_bumped"] is False
    
    # =========================================================================
    # Test: Concurrent training prevention
    # =========================================================================
    
    def test_concurrent_training_prevented(self, trainer):
        """Test that concurrent training is prevented."""
        # Arrange
        trainer._collector.get_stats = Mock(return_value={"total_events": 100})
        trainer._is_training_scheduled = True
        
        # Act
        result = trainer.train(force=True, reason="manual")
        
        # Assert
        assert result["success"] is False
        assert result["reason"] == "already_training"
        assert result["training_type"] == "scheduled"
    
    # =========================================================================
    # Test: Training metrics recording
    # =========================================================================
    
    def test_training_metrics_recorded(self, trainer):
        """Test that training metrics are recorded to persistence."""
        # Arrange
        trainer._collector.get_stats = Mock(return_value={"total_events": 100})
        
        # Mock metrics persistence
        mock_metrics_persistence = Mock()
        mock_metrics_persistence.ping = Mock(return_value=True)
        mock_metrics_persistence.record_ml_training = Mock()
        
        with patch('src.ml.trainer.get_metrics_persistence', return_value=mock_metrics_persistence):
            # Act
            result = trainer.train(force=True, reason="manual")
        
        # Assert
        assert result["success"] is True
        
        # Verify metrics were recorded
        mock_metrics_persistence.record_ml_training.assert_called_once()
        call_args = mock_metrics_persistence.record_ml_training.call_args
        
        assert call_args[1]["model_name"] == "test_model"
        assert "accuracy" in call_args[1]
        assert "loss" in call_args[1]
        assert "samples" in call_args[1]
        assert "duration_seconds" in call_args[1]
        assert "status" in call_args[1]
