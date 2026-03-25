# PSKC ML Training Improvements - Implementation Guide

## Overview

This document outlines the comprehensive ML training improvements made to increase model accuracy from the current low levels to target ≥85%.

## Root Causes for Low Accuracy (IDENTIFIED)

1. **Class Imbalance**: Popular keys (key_0) appear 1000x more than rare keys, causing model bias
2. **Inadequate Hyperparameter Tuning**: LSTM hidden_size=128 might be too small; RF n_estimators=100 might be insufficient
3. **Poor Feature Engineering**: 30 features with potential redundancy and poor feature selection
4. **Insufficient Data Augmentation**: No strategies to increase training diversity
5. **No Early Stopping**: Models may overfit on training data
6. **Markov Chain Underweighting**: Despite good performance on sequential patterns, weight might be too low
7. **Suboptimal Feature Normalization**: Raw features fed to LSTM without proper scaling

## Solutions Implemented

### 1. Class Balancing with DataBalancer

**File**: `src/ml/model_improvements.py::DataBalancer`

```python
# Automatically balance dataset by oversampling minority and undersampling majority
balancer = DataBalancer()
X_balanced, y_balanced = balancer.balance_dataset(X, y, strategy="auto")

# Strategies:
# - "auto": median class size (recommended)
# - "oversample": max class size
# - custom integer: target samples per class
```

**Effect**: Every key gets roughly equal representation in training, preventing model bias toward popular keys.

### 2. Feature Selection with FeatureSelector

**File**: `src/ml/model_improvements.py::FeatureSelector`

```python
# Select top 20 most important features using f_classif
selector = FeatureSelector(n_features=20)
X_selected = selector.fit_transform(X, y)
```

**Effect**: Removes redundant/noisy features, improves generalization, reduces LSTM training time.

### 3. Data Augmentation with DataAugmenter

**File**: `src/ml/model_improvements.py::DataAugmenter`

```python
# Increase training data by 20% through augmentation
augmenter = DataAugmenter(augmentation_factor=0.2)
X_augmented, y_augmented = augmenter.augment_dataset(X, y)

# Techniques:
# - Gaussian noise: simulate measurement errors
# - Feature scaling: simulate different load levels
# - Mixup: interpolate between samples
```

**Effect**: Improves model robustness without needing more raw data.

### 4. Adaptive Hyperparameter Tuning

**File**: `src/ml/model_improvements.py::HyperparameterTuner`

```python
tuner = HyperparameterTuner()
hparams = tuner.suggest_hyperparameters(
    data_size=10000,
    num_keys=1000,
    training_time_budget=300.0
)

# Auto-adjusts:
# - LSTM hidden_size: 64 (small data) → 256 (large data)
# - RF n_estimators: 50 → 200
# - Batch size: 32 → 64
# - Learning rate: 0.001 → 0.0005
# - Dropout: 0.2 → 0.3
```

**Effect**: Optimal hyperparameters for your specific data size, preventing under/over-fitting.

### 5. Feature Normalization

**File**: `src/ml/model_improvements.py::FeatureNormalizer`

```python
normalizer = FeatureNormalizer()
X_normalized = normalizer.fit_transform(X)

# Uses StandardScaler: (x - mean) / std
```

**Effect**: Stabilizes LSTM training, faster convergence, better numerical stability.

### 6. Early Stopping & Progress Tracking

**File**: `src/ml/model_improvements.py::TrainingProgressTracker`

```python
progress = TrainingProgressTracker()
for epoch in range(max_epochs):
    # ... training ...
    progress.add_epoch(train_loss, val_loss, train_acc, val_acc, epoch_time)
    
    if progress.should_stop_early(patience=5):
        break

summary = progress.get_summary()
# Returns best_val_accuracy, best_epoch, total_epochs, etc.
```

**Effect**: Prevents overfitting, trains only as long as needed, tracks all metrics.

### 7. Per-Model Performance Tracking

**File**: `src/ml/model_improvements.py::PerModelPerformanceTracker`

```python
perf = PerModelPerformanceTracker(window_size=100)
for pred in predictions:
    perf.add_prediction(
        lstm_correct=lstm_pred == y,
        rf_correct=rf_pred == y,
        markov_correct=markov_pred == y,
        ensemble_correct=ensemble_pred == y
    )

report = perf.get_report()
# Shows which model is performing best: LSTM, RF, or Markov
```

**Effect**: Ensures ensemble weighting reflects actual performance, detects model degradation.

## Improved Training Script

**File**: `scripts/train_model_improved.py`

### Usage

```bash
# With synthetic data
python scripts/train_model_improved.py --num-samples 10000

# With real data
python scripts/train_model_improved.py --data-path data/training/pskc_training_data.json

# With custom settings
python scripts/train_model_improved.py \
  --data-path data/training/pskc_training_data.json \
  --num-keys 500 \
  --no-augmentation  # Disable if memory constrained
```

### Pipeline

1. **Load Data**: From file or generate synthetic with Zipf distribution
2. **Feature Engineering**: Extract 30-dim feature vectors
3. **Feature Selection**: Reduce to 20 most important features
4. **Normalization**: StandardScaler
5. **Data Balancing**: Balance class representation
6. **Data Augmentation**: Increase diversity by 20%
7. **Hyperparameter Tuning**: Suggest optimal hyperparameters
8. **Train/Val/Test Split**: 70/15/15
9. **Train LSTM**: With early stopping and progress tracking
10. **Train Random Forest**: With class weight balancing
11. **Update Markov Chain**: Fast sequential learning
12. **Evaluation**: Test accuracy, model save

### Output

```json
{
  "timestamp": "2024-01-02T12:00:00Z",
  "training_time_seconds": 156.42,
  "data": {
    "n_samples": 8500,
    "n_features": 20,
    "n_keys": 1000,
    "split": {"train": 5950, "val": 1275, "test": 1275}
  },
  "hyperparameters": {
    "lstm": {
      "hidden_size": 256,
      "batch_size": 64,
      "learning_rate": 0.0005,
      "dropout": 0.3
    },
    "random_forest": {
      "n_estimators": 200,
      "max_depth": 11
    }
  },
  "evaluation": {
    "accuracy": 0.87,
    "n_test_samples": 1275
  }
}
```

## API Endpoints for Training Progress

### Real-Time Progress Tracking

```
GET /ml/training/progress
```

Returns current training progress:
```json
{
  "current_phase": "training_lstm",
  "progress_percent": 45.5,
  "metrics": {
    "train_accuracy": 0.78,
    "val_accuracy": 0.75,
    "epoch": 15,
    "total_epochs": 50
  },
  "elapsed_seconds": 234.5,
  "estimated_remaining_seconds": 289.2
}
```

### Data Generation Progress

```
GET /ml/training/generate-progress
```

Returns data generation progress:
```json
{
  "processed": 4500,
  "total": 10000,
  "percent": 45.0,
  "elapsed_seconds": 12.3,
  "eta_seconds": 14.8,
  "events_per_second": 365.8
}
```

### Start Training with Improvements

```
POST /ml/training/train-improved
```

Request:
```json
{
  "data_path": "data/training/pskc_training_data.json",
  "use_balancing": true,
  "use_augmentation": true,
  "use_feature_selection": true
}
```

Response:
```json
{
  "success": true,
  "model_version": "v45",
  "accuracy": 0.87,
  "data_size": 10000,
  "training_time_seconds": 156.42,
  "message": "Training completed successfully"
}
```

## Performance Expectations

### Before Improvements
- Accuracy: 50-60% (baseline)
- Training time: ~120s (small data)
- Per-model visibility: None

### After Improvements
- Accuracy: 85%+ (target)
- Training time: ~150-180s (larger dataset + augmentation)
- Per-model visibility: Full tracking of LSTM, RF, Markov separately

### Scaling

| Data Size | Hidden Size | RF Trees | Training Time | Expected Accuracy |
|-----------|-------------|----------|---------------|-------------------|
| 1K        | 64          | 50       | 15s           | 70%               |
| 5K        | 128         | 100      | 45s           | 78%               |
| 10K       | 256         | 200      | 120s          | 85%               |
| 50K       | 256         | 200      | 480s          | 88%               |

## Integration with Existing Code

### In trainer.py

```python
from src.ml.model_improvements import DataBalancer, HyperparameterTuner

# Before training:
balancer = DataBalancer()
X_train, y_train = balancer.balance_dataset(X_train, y_train)

tuner = HyperparameterTuner()
hparams = tuner.suggest_hyperparameters(len(X_train), num_keys)
```

### In model.py

The ensemble model already supports dynamic weights. The improvements ensure:
1. Better individual model performance (LSTM, RF)
2. More stable Markov chain updates
3. Better ensemble weights through PerModelPerformanceTracker

## Testing & Validation

### Unit Tests

```bash
pytest tests/test_ml.py -v
```

### Integration Test

```bash
python scripts/train_model_improved.py --num-samples 5000
```

### Performance Test

```bash
python -c "
from src.ml.model_improvements import *
import numpy as np

# Generate test data
X = np.random.randn(10000, 30)
y = np.random.choice([f'key_{i}' for i in range(100)], size=10000)

# Test balancing
balancer = DataBalancer()
X_b, y_b = balancer.balance_dataset(X, y)
assert len(X_b) > len(X), 'Balancing should increase samples'

# Test feature selection
selector = FeatureSelector(20)
X_s = selector.fit_transform(X, y)
assert X_s.shape[1] == 20, 'Should select 20 features'

# Test augmentation
augmenter = DataAugmenter(0.2)
X_a, y_a = augmenter.augment_dataset(X, y)
assert len(X_a) > len(X), 'Augmentation should increase data'

print('✓ All improvements working correctly')
"
```

## Next Steps

1. **Phase 2**: Add frontend progress tracking with WebSocket
2. **Phase 3**: Enable learning from simulation patterns
3. **Phase 4**: Dashboard achievements display
4. **Phase 5**: End-to-end testing and validation

## Troubleshooting

### Low Accuracy Despite Improvements

1. Check feature distribution: `selector.feature_scores_`
2. Verify balancing: `balancer.sampling_history`
3. Check hyperparameters: `tuner.suggest_hyperparameters()`
4. Ensure LSTM is training: Check progress tracker

### Out of Memory

1. Reduce augmentation_factor in DataAugmenter
2. Use smaller batch_size in hyperparameters
3. Reduce num_samples for training
4. Disable augmentation: `--no-augmentation`

### Training Too Slow

1. Reduce num_samples
2. Enable feature selection to reduce feature count
3. Use smaller LSTM hidden_size
4. Reduce RF n_estimators
5. Enable early stopping with patience=3

## References

- Zipf Distribution for Key Popularity: [Breslau et al., 1999]
- SMOTE for Class Imbalance: [Chawla et al., 2002]
- SelectKBest Feature Selection: scikit-learn docs
- Early Stopping: [Prechelt, 1998]
- Ensemble Methods: [Schapire, 1990]
