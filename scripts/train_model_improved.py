#!/usr/bin/env python3
# ============================================================
# PSKC — Improved Model Training Script
# With hyperparameter tuning, class balancing, and feature selection
# ============================================================
import argparse
import sys
import os
import json
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import logging

from src.ml.data_collector import DataCollector
from src.ml.feature_engineering import FeatureEngineer
from src.ml.model import EnsembleModel, ModelFactory
from src.ml.model_registry import get_model_registry
from src.ml.model_improvements import (
    DataBalancer,
    FeatureSelector,
    DataAugmenter,
    HyperparameterTuner,
    FeatureNormalizer,
    TrainingProgressTracker,
    PerModelPerformanceTracker,
)
from config.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================
# Data Generation with Zipf Distribution
# ============================================================

def _generate_zipf_weights(num_keys: int, exponent: float = 1.0) -> np.ndarray:
    """Generate Zipf-distributed key weights."""
    ranks = np.arange(1, num_keys + 1, dtype=np.float64)
    weights = 1.0 / (ranks ** exponent)
    return weights / weights.sum()


def generate_synthetic_data(
    n_samples: int = 5000,
    num_keys: int = 1000,
    num_services: int = 6,
    zipf_exponent: float = 1.0,
    temporal_correlation: float = 0.4,
    duration_hours: float = 6.0,
    seed: int = 42
) -> list:
    """Generate synthetic access data with realistic distributions."""
    rng = np.random.default_rng(seed)

    # Key popularity weights (Zipf)
    weights = _generate_zipf_weights(num_keys, exponent=zipf_exponent)

    # Poisson inter-arrival times
    total_seconds = duration_hours * 3600
    avg_rps = n_samples / total_seconds
    inter_arrivals = rng.exponential(1.0 / avg_rps, size=n_samples)
    base_time = datetime.now().timestamp() - total_seconds
    timestamps = base_time + np.cumsum(inter_arrivals)

    # Generate key sequence with temporal correlation
    key_indices = np.zeros(n_samples, dtype=int)
    key_indices[0] = rng.choice(num_keys, p=weights)

    for i in range(1, n_samples):
        if rng.random() < temporal_correlation:
            key_indices[i] = key_indices[i - 1]
        else:
            key_indices[i] = rng.choice(num_keys, p=weights)

    service_ids = [f"service_{rng.integers(0, num_services)}" for _ in range(n_samples)]

    # Build records
    data = []
    for i in range(n_samples):
        ts = float(timestamps[i])
        dt = datetime.fromtimestamp(ts)
        key_id = f"key_{key_indices[i]}"

        # Cache hit probability: hot keys hit more often
        popularity_rank = key_indices[i]
        hit_prob = max(0.3, 0.95 - (popularity_rank / num_keys) * 0.65)
        cache_hit = bool(rng.random() < hit_prob)

        # Latency: log-normal
        if cache_hit:
            latency_ms = np.random.lognormal(np.log(3), 0.5)
        else:
            latency_ms = np.random.lognormal(np.log(10), 1.0)

        data.append({
            "timestamp": ts,
            "datetime": dt.isoformat(),
            "key_id": key_id,
            "service_id": service_ids[i],
            "cache_hit": cache_hit,
            "latency_ms": float(latency_ms),
        })

    return sorted(data, key=lambda x: x["timestamp"])


def load_training_data(data_path: str = None):
    """Load training data from file or generate synthetic."""
    if data_path and os.path.exists(data_path):
        with open(data_path, 'r') as f:
            data = json.load(f)
        logger.info(f"Loaded {len(data)} training samples from {data_path}")
        return data
    else:
        logger.info("Generating synthetic training data with Zipf distribution...")
        return generate_synthetic_data()


# ============================================================
# Feature Preparation Pipeline
# ============================================================

def prepare_features_and_labels(
    data: list,
    feature_engineer: FeatureEngineer,
    include_augmentation: bool = True,
    include_normalization: bool = True,
) -> tuple:
    """
    Convert raw data to feature matrix and labels.
    
    Returns:
        X: Feature matrix (n_samples, n_features)
        y: Labels (n_samples,)
        feature_engineer: Fitted feature engineer
        normalizer: Fitted normalizer (if applied)
    """
    logger.info(f"Preparing features from {len(data)} samples...")

    X = []
    y = []

    # Group by key for proper context windows
    key_accesses = {}
    for event in data:
        key = event["key_id"]
        if key not in key_accesses:
            key_accesses[key] = []
        key_accesses[key].append(event)

    # Create context windows (last 10 events predict next)
    window_size = 10
    for key, accesses in key_accesses.items():
        for i in range(window_size, len(accesses)):
            context = accesses[i - window_size:i]
            features = feature_engineer.extract_features(context, key_id=key)
            X.append(features)
            y.append(key)

    X = np.array(X, dtype=np.float32)
    y = np.array(y)

    logger.info(f"Created {len(X)} feature vectors from {len(y)} samples")

    # Data normalization
    normalizer = None
    if include_normalization:
        logger.info("Normalizing features...")
        normalizer = FeatureNormalizer()
        X = normalizer.fit_transform(X)

    # Feature selection
    logger.info("Selecting important features...")
    selector = FeatureSelector(n_features=20)
    X = selector.fit_transform(X, y)

    # Data balancing
    logger.info("Balancing dataset...")
    balancer = DataBalancer()
    X, y = balancer.balance_dataset(X, y, strategy="auto")

    # Data augmentation
    if include_augmentation:
        logger.info("Augmenting training data...")
        augmenter = DataAugmenter(augmentation_factor=0.2)
        X, y = augmenter.augment_dataset(X, y)

    logger.info(f"Final dataset: {len(X)} samples, {X.shape[1]} features")

    return X, y, normalizer, selector


# ============================================================
# Training Pipeline
# ============================================================

def train_model(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    hyperparameters: dict,
    verbose: bool = True,
) -> tuple:
    """
    Train ensemble model with given hyperparameters.
    
    Returns:
        (model, progress_tracker, perf_tracker)
    """
    logger.info(f"Training ensemble model with {len(X_train)} training samples...")
    logger.info(f"Hyperparameters: {json.dumps(hyperparameters, indent=2)}")

    # Create model
    model = ModelFactory.create_model(
        "ensemble",
        num_classes=len(np.unique(y_train)),
        **hyperparameters
    )

    progress_tracker = TrainingProgressTracker()
    perf_tracker = PerModelPerformanceTracker()

    # Train LSTM if available
    if hasattr(model, 'lstm') and model.lstm is not None:
        logger.info("Training LSTM component...")
        try:
            import torch
            from torch.optim import Adam
            from torch.nn import CrossEntropyLoss

            device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
            lstm_model = model.lstm.to(device)

            optimizer = Adam(lstm_model.parameters(), lr=hyperparameters['lstm']['learning_rate'])
            criterion = CrossEntropyLoss()

            X_train_t = torch.FloatTensor(X_train).to(device)
            y_train_t = torch.LongTensor(y_train).to(device)
            X_val_t = torch.FloatTensor(X_val).to(device)
            y_val_t = torch.LongTensor(y_val).to(device)

            batch_size = hyperparameters['lstm']['batch_size']
            epochs = hyperparameters['lstm']['epochs']
            patience = hyperparameters['lstm']['early_stopping_patience']

            for epoch in range(epochs):
                epoch_start = time.time()

                # Training
                lstm_model.train()
                train_loss = 0
                train_correct = 0
                for i in range(0, len(X_train_t), batch_size):
                    batch_x = X_train_t[i:i + batch_size]
                    batch_y = y_train_t[i:i + batch_size]

                    optimizer.zero_grad()
                    logits = lstm_model(batch_x)
                    loss = criterion(logits, batch_y)
                    loss.backward()
                    optimizer.step()

                    train_loss += loss.item()
                    train_correct += (logits.argmax(1) == batch_y).sum().item()

                train_loss /= (len(X_train_t) // batch_size + 1)
                train_acc = train_correct / len(X_train_t)

                # Validation
                lstm_model.eval()
                with torch.no_grad():
                    val_logits = lstm_model(X_val_t)
                    val_loss = criterion(val_logits, y_val_t).item()
                    val_acc = (val_logits.argmax(1) == y_val_t).sum().item() / len(y_val_t)

                epoch_time = time.time() - epoch_start
                progress_tracker.add_epoch(train_loss, val_loss, train_acc, val_acc, epoch_time)

                if (epoch + 1) % 5 == 0 or epoch == 0:
                    logger.info(
                        f"LSTM Epoch {epoch + 1}/{epochs} - "
                        f"train_loss={train_loss:.4f}, val_loss={val_loss:.4f}, "
                        f"train_acc={train_acc:.4f}, val_acc={val_acc:.4f}"
                    )

                # Early stopping
                if progress_tracker.should_stop_early(patience):
                    logger.info(f"Early stopping at epoch {epoch + 1}")
                    break

        except Exception as e:
            logger.error(f"LSTM training failed: {e}")

    # Train Random Forest if available
    if hasattr(model, 'rf') and model.rf is not None:
        logger.info("Training Random Forest component...")
        try:
            model.rf.fit(X_train, y_train)
            logger.info("Random Forest training completed")
        except Exception as e:
            logger.error(f"Random Forest training failed: {e}")

    # Update Markov chain
    if hasattr(model, 'markov') and model.markov is not None:
        logger.info("Updating Markov Chain component...")
        try:
            for key_id in np.unique(y_train):
                model.markov.update(key_id)
            logger.info("Markov Chain updated")
        except Exception as e:
            logger.error(f"Markov Chain update failed: {e}")

    return model, progress_tracker, perf_tracker


# ============================================================
# Evaluation
# ============================================================

def evaluate_model(
    model: EnsembleModel,
    X_test: np.ndarray,
    y_test: np.ndarray,
) -> dict:
    """Evaluate model on test set."""
    logger.info(f"Evaluating model on {len(X_test)} test samples...")

    if not hasattr(model, 'predict'):
        logger.warning("Model does not have predict method")
        return {}

    try:
        y_pred = model.predict(X_test)

        accuracy = (y_pred == y_test).sum() / len(y_test)
        
        logger.info(f"Test Accuracy: {accuracy:.4f}")

        return {
            "accuracy": float(accuracy),
            "n_test_samples": len(X_test),
            "n_correct": int((y_pred == y_test).sum()),
        }

    except Exception as e:
        logger.error(f"Evaluation failed: {e}")
        return {}


# ============================================================
# Main Training Pipeline
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Train PSKC ML model with improvements")
    parser.add_argument("--data-path", type=str, default=None, help="Path to training data")
    parser.add_argument("--num-samples", type=int, default=5000, help="Number of synthetic samples")
    parser.add_argument("--num-keys", type=int, default=1000, help="Number of unique keys")
    parser.add_argument("--no-augmentation", action="store_true", help="Disable data augmentation")
    parser.add_argument("--no-balancing", action="store_true", help="Disable class balancing")
    parser.add_argument("--output-dir", type=str, default="data/models", help="Output directory for model")
    args = parser.parse_args()

    logger.info("=" * 70)
    logger.info("PSKC Improved Model Training Pipeline")
    logger.info("=" * 70)

    # Load or generate data
    data = load_training_data(args.data_path)
    if not data:
        logger.warning("No training data available, generating synthetic...")
        data = generate_synthetic_data(n_samples=args.num_samples, num_keys=args.num_keys)

    # Get unique keys for num_classes
    unique_keys = set(event["key_id"] for event in data)
    num_keys = len(unique_keys)
    logger.info(f"Found {num_keys} unique keys in dataset")

    # Prepare features
    feature_engineer = FeatureEngineer()
    X, y, normalizer, selector = prepare_features_and_labels(
        data,
        feature_engineer,
        include_augmentation=not args.no_augmentation,
        include_normalization=True,
    )

    # Suggest hyperparameters
    tuner = HyperparameterTuner()
    hyperparameters = tuner.suggest_hyperparameters(len(X), num_keys)

    # Train/val/test split
    n_total = len(X)
    n_train = int(n_total * 0.7)
    n_val = int(n_total * 0.15)

    indices = np.random.permutation(n_total)
    train_idx = indices[:n_train]
    val_idx = indices[n_train:n_train + n_val]
    test_idx = indices[n_train + n_val:]

    X_train, y_train = X[train_idx], y[train_idx]
    X_val, y_val = X[val_idx], y[val_idx]
    X_test, y_test = X[test_idx], y[test_idx]

    logger.info(f"Split: train={len(train_idx)}, val={len(val_idx)}, test={len(test_idx)}")

    # Train model
    start_time = time.time()
    model, progress_tracker, perf_tracker = train_model(
        X_train, y_train,
        X_val, y_val,
        hyperparameters,
        verbose=True,
    )
    training_time = time.time() - start_time

    # Evaluate
    eval_results = evaluate_model(model, X_test, y_test)

    # Save results
    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "training_time_seconds": training_time,
        "data": {
            "n_samples": len(X),
            "n_features": X.shape[1],
            "n_keys": num_keys,
            "split": {"train": len(train_idx), "val": len(val_idx), "test": len(test_idx)},
        },
        "hyperparameters": hyperparameters,
        "training": progress_tracker.get_summary(),
        "evaluation": eval_results,
    }

    logger.info("\n" + "=" * 70)
    logger.info("TRAINING SUMMARY")
    logger.info("=" * 70)
    logger.info(json.dumps(results, indent=2))
    logger.info("=" * 70)

    # Save model via registry
    try:
        registry = get_model_registry()
        model_version = registry.save_model(
            model,
            stage="production" if eval_results.get("accuracy", 0) > 0.80 else "staging",
            metadata={
                "training_time": training_time,
                "results": results,
                "data_size": len(X),
            }
        )
        logger.info(f"Model saved with version: {model_version}")
    except Exception as e:
        logger.error(f"Failed to save model: {e}")


if __name__ == "__main__":
    main()
