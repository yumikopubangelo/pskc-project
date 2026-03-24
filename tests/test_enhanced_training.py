# ============================================================
# PSKC — Enhanced ML Training Pipeline Tests
# Tests for DataBalancer, FeatureSelector, DataAugmenter, 
# FeatureNormalizer, and HyperparameterTuner integration
# ============================================================
import pytest
import numpy as np
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ml.data_collector import DataCollector
from src.ml.feature_engineering import FeatureEngineer
from src.ml.model_improvements import (
    DataBalancer,
    FeatureSelector,
    DataAugmenter,
    HyperparameterTuner,
    FeatureNormalizer,
    PerModelPerformanceTracker,
)


class TestDataBalancer:
    """Test cases for DataBalancer"""
    
    def test_balance_dataset_auto(self):
        """Test auto balancing strategy"""
        balancer = DataBalancer()
        
        # Create imbalanced dataset
        X = np.random.randn(100, 10)
        y = np.array([0] * 80 + [1] * 15 + [2] * 5)  # Imbalanced
        
        X_balanced, y_balanced = balancer.balance_dataset(X, y, strategy="auto")
        
        # Check that dataset is balanced
        unique, counts = np.unique(y_balanced, return_counts=True)
        assert len(unique) == 3
        # All classes should have similar counts (median-based)
        assert np.std(counts) < np.mean(counts) * 0.5
    
    def test_balance_dataset_oversample(self):
        """Test oversample balancing strategy"""
        balancer = DataBalancer()
        
        X = np.random.randn(100, 10)
        y = np.array([0] * 80 + [1] * 15 + [2] * 5)
        
        X_balanced, y_balanced = balancer.balance_dataset(X, y, strategy="oversample")
        
        unique, counts = np.unique(y_balanced, return_counts=True)
        # All classes should have max count
        assert np.all(counts == counts[0])
    
    def test_balance_preserves_features(self):
        """Test that balancing preserves feature dimensions"""
        balancer = DataBalancer()
        
        X = np.random.randn(100, 15)
        y = np.array([0] * 70 + [1] * 30)
        
        X_balanced, y_balanced = balancer.balance_dataset(X, y, strategy="auto")
        
        assert X_balanced.shape[1] == 15
        assert len(X_balanced) == len(y_balanced)


class TestFeatureSelector:
    """Test cases for FeatureSelector"""
    
    def test_feature_selection(self):
        """Test feature selection reduces dimensions"""
        selector = FeatureSelector(n_features=10)
        
        X = np.random.randn(100, 30)
        y = np.random.randint(0, 5, 100)
        
        X_selected = selector.fit_transform(X, y)
        
        assert X_selected.shape[1] == 10
        assert X_selected.shape[0] == 100
    
    def test_feature_selection_preserves_samples(self):
        """Test that feature selection preserves sample count"""
        selector = FeatureSelector(n_features=5)
        
        X = np.random.randn(200, 20)
        y = np.random.randint(0, 3, 200)
        
        X_selected = selector.fit_transform(X, y)
        
        assert X_selected.shape[0] == 200
    
    def test_get_selected_features(self):
        """Test getting selected feature indices"""
        selector = FeatureSelector(n_features=5)
        
        X = np.random.randn(100, 20)
        y = np.random.randint(0, 3, 100)
        
        selector.fit(X, y)
        selected = selector.get_selected_features()
        
        assert len(selected) == 5
        assert all(0 <= idx < 20 for idx in selected)


class TestDataAugmenter:
    """Test cases for DataAugmenter"""
    
    def test_augmentation_increases_size(self):
        """Test that augmentation increases dataset size"""
        augmenter = DataAugmenter(augmentation_factor=0.3)
        
        X = np.random.randn(100, 10)
        y = np.random.randint(0, 3, 100)
        
        X_aug, y_aug = augmenter.augment_dataset(X, y)
        
        # Should have 130 samples (100 + 30% augmentation)
        assert len(X_aug) == 130
        assert len(y_aug) == 130
    
    def test_augmentation_preserves_features(self):
        """Test that augmentation preserves feature dimensions"""
        augmenter = DataAugmenter(augmentation_factor=0.2)
        
        X = np.random.randn(100, 15)
        y = np.random.randint(0, 3, 100)
        
        X_aug, y_aug = augmenter.augment_dataset(X, y)
        
        assert X_aug.shape[1] == 15
    
    def test_noise_augmentation(self):
        """Test noise augmentation method"""
        augmenter = DataAugmenter()
        
        x = np.random.randn(10)
        x_aug = augmenter._augment_with_noise(x, noise_std=0.1)
        
        assert x_aug.shape == x.shape
        # Augmented should be different from original
        assert not np.allclose(x, x_aug)
    
    def test_mixup_augmentation(self):
        """Test mixup augmentation method"""
        augmenter = DataAugmenter()
        
        x1 = np.random.randn(10)
        x2 = np.random.randn(10)
        x_mix = augmenter._augment_with_mixup(x1, x2, alpha=0.2)
        
        assert x_mix.shape == x1.shape
        # Mixup should be interpolation of x1 and x2
        assert np.all(x_mix >= np.minimum(x1, x2) - 0.1)
        assert np.all(x_mix <= np.maximum(x1, x2) + 0.1)


class TestFeatureNormalizer:
    """Test cases for FeatureNormalizer"""
    
    def test_normalization(self):
        """Test feature normalization"""
        normalizer = FeatureNormalizer()
        
        X = np.random.randn(100, 10) * 100  # Large scale
        X_norm = normalizer.fit_transform(X)
        
        # Normalized should have mean ~0 and std ~1
        assert np.abs(np.mean(X_norm)) < 0.1
        assert np.abs(np.std(X_norm) - 1.0) < 0.1
    
    def test_normalization_preserves_shape(self):
        """Test that normalization preserves shape"""
        normalizer = FeatureNormalizer()
        
        X = np.random.randn(50, 20)
        X_norm = normalizer.fit_transform(X)
        
        assert X_norm.shape == X.shape
    
    def test_transform_without_fit(self):
        """Test transform without fit returns original"""
        normalizer = FeatureNormalizer()
        
        X = np.random.randn(100, 10)
        X_transformed = normalizer.transform(X)
        
        np.testing.assert_array_equal(X, X_transformed)


class TestHyperparameterTuner:
    """Test cases for HyperparameterTuner"""
    
    def test_suggest_hyperparameters_small_data(self):
        """Test hyperparameter suggestion for small dataset"""
        tuner = HyperparameterTuner()
        
        hparams = tuner.suggest_hyperparameters(
            data_size=500,
            num_keys=50,
            training_time_budget=60.0
        )
        
        assert hparams["lstm"]["hidden_size"] == 64
        assert hparams["random_forest"]["n_estimators"] == 50
        assert hparams["training"]["data_balancing"] == "auto"
    
    def test_suggest_hyperparameters_large_data(self):
        """Test hyperparameter suggestion for large dataset"""
        tuner = HyperparameterTuner()
        
        hparams = tuner.suggest_hyperparameters(
            data_size=50000,
            num_keys=1000,
            training_time_budget=300.0
        )
        
        assert hparams["lstm"]["hidden_size"] == 256
        assert hparams["random_forest"]["n_estimators"] == 200
        assert hparams["training"]["augmentation_factor"] == 0.2
    
    def test_hyperparameters_structure(self):
        """Test hyperparameter structure完整性"""
        tuner = HyperparameterTuner()
        
        hparams = tuner.suggest_hyperparameters(
            data_size=10000,
            num_keys=100,
            training_time_budget=120.0
        )
        
        # Check all required sections exist
        assert "lstm" in hparams
        assert "random_forest" in hparams
        assert "markov" in hparams
        assert "ensemble" in hparams
        assert "training" in hparams
        
        # Check LSTM parameters
        assert "hidden_size" in hparams["lstm"]
        assert "learning_rate" in hparams["lstm"]
        assert "dropout" in hparams["lstm"]
        
        # Check RF parameters
        assert "n_estimators" in hparams["random_forest"]
        assert "max_depth" in hparams["random_forest"]


class TestPerModelPerformanceTracker:
    """Test cases for PerModelPerformanceTracker"""
    
    def test_record_predictions(self):
        """Test recording predictions"""
        tracker = PerModelPerformanceTracker(window_size=10)
        
        for i in range(15):
            tracker.add_prediction(
                lstm_correct=(i % 2 == 0),
                rf_correct=(i % 3 == 0),
                markov_correct=(i % 4 == 0),
                ensemble_correct=(i % 2 == 0)
            )
        
        # Should only keep last 10
        assert len(tracker.lstm_accuracies) == 10
    
    def test_get_window_accuracy(self):
        """Test getting window accuracy"""
        tracker = PerModelPerformanceTracker(window_size=5)
        
        # Add 5 predictions
        for i in range(5):
            tracker.add_prediction(
                lstm_correct=True,
                rf_correct=False,
                markov_correct=True,
                ensemble_correct=True
            )
        
        acc = tracker.get_window_accuracy()
        
        assert acc["lstm"] == 1.0
        assert acc["random_forest"] == 0.0
        assert acc["markov"] == 1.0
        assert acc["ensemble"] == 1.0
    
    def test_get_report(self):
        """Test getting performance report"""
        tracker = PerModelPerformanceTracker(window_size=10)
        
        for i in range(10):
            tracker.add_prediction(
                lstm_correct=(i < 8),
                rf_correct=(i < 5),
                markov_correct=(i < 7),
                ensemble_correct=(i < 9)
            )
        
        report = tracker.get_report()
        
        assert "window_accuracy" in report
        assert "predictions_evaluated" in report
        assert report["predictions_evaluated"] == 10


class TestIntegration:
    """Integration tests for enhanced training pipeline"""
    
    def test_full_pipeline(self):
        """Test full enhanced training pipeline"""
        # Create synthetic data
        collector = DataCollector(max_events=1000)
        
        # Generate diverse access patterns
        for i in range(500):
            collector.record_access(
                key_id=f"key_{i % 10}",
                service_id=f"service_{i % 3}",
                cache_hit=(i % 2 == 0),
                latency_ms=float(i % 100)
            )
        
        # Get access sequence
        access_data = collector.get_access_sequence(max_events=500)
        
        # Extract features
        engineer = FeatureEngineer()
        X = []
        y = []
        
        for event in access_data:
            features = engineer.extract_features([event])
            X.append(features)
            y.append(event["key_id"])
        
        X = np.array(X)
        y = np.array(y)
        
        # Apply enhancements
        normalizer = FeatureNormalizer()
        X = normalizer.fit_transform(X)
        
        selector = FeatureSelector(n_features=min(10, X.shape[1]))
        X = selector.fit_transform(X, y)
        
        augmenter = DataAugmenter(augmentation_factor=0.2)
        X, y = augmenter.augment_dataset(X, y)
        
        balancer = DataBalancer()
        X, y = balancer.balance_dataset(X, y, strategy="auto")
        
        # Verify pipeline完整性
        assert len(X) > 500  # Augmentation increased size
        assert X.shape[1] <= 10  # Feature selection applied
        
        # Check class balance
        unique, counts = np.unique(y, return_counts=True)
        assert np.std(counts) < np.mean(counts) * 0.5  # Balanced
    
    def test_hyperparameter_adaptation(self):
        """Test hyperparameter adaptation for different data sizes"""
        tuner = HyperparameterTuner()
        
        # Small dataset
        hparams_small = tuner.suggest_hyperparameters(
            data_size=500,
            num_keys=50,
            training_time_budget=60.0
        )
        
        # Large dataset
        hparams_large = tuner.suggest_hyperparameters(
            data_size=50000,
            num_keys=1000,
            training_time_budget=300.0
        )
        
        # Small should have smaller models
        assert hparams_small["lstm"]["hidden_size"] < hparams_large["lstm"]["hidden_size"]
        assert hparams_small["random_forest"]["n_estimators"] < hparams_large["random_forest"]["n_estimators"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
