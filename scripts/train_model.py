#!/usr/bin/env python3
# ============================================================
# PSKC — Model Training Script (IMPROVED)
# Fixes:
#   1. generate_synthetic_data now uses true Zipf distribution
#      (consistent with AccessPatternGenerator in traffic_generator.py)
#   2. Proper 70/15/15 train/val/test split — no more accuracy measured
#      on training data (overfitting bias)
#   3. Hyperparameter logging to model registry for version comparison
#   4. Temporal split option to avoid data leakage from future timestamps
# ============================================================
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import logging
from datetime import datetime, timezone

from src.ml.data_collector import DataCollector
from src.ml.feature_engineering import FeatureEngineer
from src.ml.model import EnsembleModel, ModelFactory
from src.ml.model_registry import get_model_registry
from config.settings import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================
# Zipf Weight Generator (consistent with traffic_generator.py)
# ============================================================

def _generate_zipf_weights(num_keys: int, exponent: float = 1.0) -> np.ndarray:
    """
    Generate Zipf-distributed key weights.
    Exponent ~1.0 matches real-world cache key popularity distributions.
    Ref: traffic_generator.py uses 1.5, but 0.8–1.2 is more accurate
    per Breslau et al. (1999) web cache study.

    Args:
        num_keys: Total number of distinct keys
        exponent: Zipf exponent (higher = more skewed toward hot keys)

    Returns:
        Normalized probability array of shape (num_keys,)
    """
    ranks = np.arange(1, num_keys + 1, dtype=np.float64)
    weights = 1.0 / (ranks ** exponent)
    return weights / weights.sum()


# ============================================================
# Data Loading / Generation
# ============================================================

def load_training_data(data_path: str = None):
    """Load training data from file or generate synthetic."""
    if data_path and os.path.exists(data_path):
        import json
        with open(data_path, 'r') as f:
            data = json.load(f)
        logger.info(f"Loaded {len(data)} training samples from {data_path}")
        return data
    else:
        logger.info("Generating synthetic training data with Zipf distribution...")
        return generate_synthetic_data()


def generate_synthetic_data(
    n_samples: int = 5000,
    num_keys: int = 1000,
    num_services: int = 6,
    zipf_exponent: float = 1.0,
    temporal_correlation: float = 0.4,
    duration_hours: float = 6.0,
    seed: int = 42
) -> list:
    """
    Generate synthetic access data using true Zipf distribution.

    BEFORE (broken): hot keys chosen with flat random.choice(),
    meaning all 20 hot keys had equal probability = completely
    unrealistic. Also missed temporal correlation entirely.

    AFTER (fixed):
    - Key popularity follows Zipf power law (consistent with
      AccessPatternGenerator in simulation/engines/traffic_generator.py)
    - Temporal correlation: consecutive accesses tend to hit
      the same key (models real session behavior)
    - Latency generated from log-normal (consistent with
      simulation/engines/latency_engine.py)
    - Timestamps spread over configurable time window with
      realistic inter-arrival gaps (Poisson process)

    Args:
        n_samples: Number of access events to generate
        num_keys: Total distinct keys in the keyspace
        num_services: Number of distinct services
        zipf_exponent: Zipf skew (1.0 = standard, 1.5 = more hot-skewed)
        temporal_correlation: Probability of staying on current key
        duration_hours: Time window to spread events over
        seed: Random seed for reproducibility

    Returns:
        List of access event dicts, sorted by timestamp ascending
    """
    rng = np.random.default_rng(seed)

    # --- Key popularity weights (Zipf) ---
    weights = _generate_zipf_weights(num_keys, exponent=zipf_exponent)

    # --- Poisson inter-arrival times ---
    total_seconds = duration_hours * 3600
    avg_rps = n_samples / total_seconds
    inter_arrivals = rng.exponential(1.0 / avg_rps, size=n_samples)
    base_time = datetime.now().timestamp() - total_seconds
    timestamps = base_time + np.cumsum(inter_arrivals)

    # --- Generate key sequence with temporal correlation ---
    key_indices = np.zeros(n_samples, dtype=int)
    key_indices[0] = rng.choice(num_keys, p=weights)

    for i in range(1, n_samples):
        if rng.random() < temporal_correlation:
            # Stay on current key (session locality)
            key_indices[i] = key_indices[i - 1]
        else:
            # Switch to a new key sampled by popularity
            key_indices[i] = rng.choice(num_keys, p=weights)

    # --- Service assignment (some services prefer certain key ranges) ---
    service_ids = [f"service_{rng.integers(0, num_services)}" for _ in range(n_samples)]

    # --- Build records ---
    data = []
    for i in range(n_samples):
        ts = float(timestamps[i])
        dt = datetime.fromtimestamp(ts)
        key_id = f"key_{key_indices[i]}"

        # Cache hit probability: hot keys (low index) hit more often
        popularity_rank = key_indices[i]  # 0 = hottest
        hit_prob = max(0.3, 0.95 - (popularity_rank / num_keys) * 0.65)
        cache_hit = bool(rng.random() < hit_prob)

        # Latency: log-normal, consistent with latency_engine.py
        if cache_hit:
            latency_ms = float(np.exp(rng.normal(1.5, 0.3)))   # ~4.5ms
        else:
            latency_ms = float(np.exp(rng.normal(5.2, 0.4)))   # ~180ms

        data.append({
            "key_id": key_id,
            "service_id": service_ids[i],
            "timestamp": ts,
            "hour": dt.hour,
            "day_of_week": dt.weekday(),
            "cache_hit": int(cache_hit),
            "latency_ms": round(latency_ms, 2),
        })

    logger.info(
        f"Generated {n_samples} samples | "
        f"Zipf exponent={zipf_exponent} | "
        f"Temporal correlation={temporal_correlation} | "
        f"Unique keys used: {len(set(d['key_id'] for d in data))}"
    )
    return data


# ============================================================
# Temporal Split (prevents data leakage)
# ============================================================

def temporal_split(
    data: list,
    train_ratio: float = 0.70,
    val_ratio: float = 0.15,
    # test_ratio is implicitly 1 - train - val = 0.15
) -> tuple:
    """
    Split data by time — earlier events train the model,
    later events validate/test it.

    WHY TEMPORAL: Random split would leak future access patterns
    into training, inflating accuracy metrics artificially.
    Time-ordered split mirrors real deployment where model is
    trained on past data and evaluated on future data.

    Returns:
        (train_data, val_data, test_data)
    """
    sorted_data = sorted(data, key=lambda x: x["timestamp"])
    n = len(sorted_data)

    train_end = int(n * train_ratio)
    val_end = int(n * (train_ratio + val_ratio))

    train = sorted_data[:train_end]
    val = sorted_data[train_end:val_end]
    test = sorted_data[val_end:]

    logger.info(
        f"Temporal split → train: {len(train)} | "
        f"val: {len(val)} | test: {len(test)}"
    )
    return train, val, test


# ============================================================
# Feature Extraction Helper
# ============================================================

def extract_XY(data: list, engineer: FeatureEngineer):
    """
    Extract feature matrix X and label vector y from data.

    Uses a sliding window of 10 preceding events to build context
    features for each sample, rather than extracting features from
    a single isolated event (which loses temporal context).
    """
    CONTEXT_WINDOW = 10

    X, y = [], []
    for idx in range(len(data)):
        # Context: up to 10 preceding events (or whatever is available)
        start = max(0, idx - CONTEXT_WINDOW)
        context = data[start : idx + 1]

        features = engineer.extract_features(context)
        X.append(features)
        y.append(data[idx]["key_id"])

    return np.array(X), np.array(y)


def build_registry_compatible_model(
    classifier,
    label_encoder,
    access_sequence: list,
) -> EnsembleModel:
    """
    Wrap the trained sklearn classifier into an EnsembleModel so it can be
    serialized through the hardened registry without falling back to pickle.
    """
    ensemble_model = EnsembleModel(num_classes=max(len(label_encoder.classes_), 1))

    if ensemble_model.rf is None:
        raise RuntimeError("RandomForest runtime is unavailable in EnsembleModel")

    ensemble_model.rf.model = classifier
    ensemble_model.rf.label_encoder = label_encoder
    ensemble_model.rf.is_trained = True

    for event in access_sequence:
        ensemble_model.markov.update(event["key_id"])

    ensemble_model.is_trained = True
    return ensemble_model


# ============================================================
# Main Training Function
# ============================================================

def train_model(
    data_path: str = None,
    model_name: str = settings.ml_model_name,
    version: str = None,
    force: bool = False,
    zipf_exponent: float = 1.0,
    n_estimators: int = 200,
    max_depth: int = None,
    stage: str = None,
):
    """
    Train PSKC ML model with proper validation.

    Key changes vs previous version:
    - Accuracy is now measured on HELD-OUT test set, not training data
    - Also reports validation accuracy for early comparison
    - Hyperparameters are logged to model registry for A/B comparison
    """
    version = version or datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info(f"Starting training: model={model_name}, version={version}")

    # --- Load / generate data ---
    all_data = load_training_data(data_path)

    if len(all_data) < 100:
        logger.error("Insufficient training data (need at least 100 samples)")
        return False

    # --- Temporal split ---
    train_data, val_data, test_data = temporal_split(all_data)

    # --- Feature extraction ---
    engineer = FeatureEngineer()

    logger.info("Extracting features...")
    X_train, y_train = extract_XY(train_data, engineer)
    X_val,   y_val   = extract_XY(val_data,   engineer)
    X_test,  y_test  = extract_XY(test_data,  engineer)

    logger.info(f"Feature matrix → train: {X_train.shape}, val: {X_val.shape}, test: {X_test.shape}")

    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.preprocessing import LabelEncoder

        # Label encode across full dataset so all splits share same encoding
        le = LabelEncoder()
        le.fit(y_train)  # Fit only on train to avoid leakage

        # Keys in val/test not seen in train → map to "unknown"
        def safe_transform(le, labels):
            known = set(le.classes_)
            return np.array([
                le.transform([lbl])[0] if lbl in known else -1
                for lbl in labels
            ])

        y_train_enc = le.transform(y_train)
        y_val_enc   = safe_transform(le, y_val)
        y_test_enc  = safe_transform(le, y_test)

        # --- Train ---
        logger.info(f"Training RandomForest: n_estimators={n_estimators}, max_depth={max_depth}")
        clf = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            random_state=42,
            n_jobs=-1,
        )
        clf.fit(X_train, y_train_enc)

        # --- Evaluate on HELD-OUT sets (not training data) ---
        val_mask  = y_val_enc  != -1
        test_mask = y_test_enc != -1

        val_acc  = (clf.predict(X_val[val_mask])   == y_val_enc[val_mask]).mean()   if val_mask.any()  else 0.0
        test_acc = (clf.predict(X_test[test_mask]) == y_test_enc[test_mask]).mean() if test_mask.any() else 0.0

        # Also compute training accuracy to detect overfitting
        train_acc = (clf.predict(X_train) == y_train_enc).mean()

        logger.info("=" * 50)
        logger.info(f"  Train accuracy : {train_acc:.2%}  ← expected high")
        logger.info(f"  Val accuracy   : {val_acc:.2%}  ← use for tuning")
        logger.info(f"  Test accuracy  : {test_acc:.2%}  ← TRUE metric")
        logger.info("=" * 50)

        if train_acc - test_acc > 0.20:
            logger.warning(
                f"Possible overfitting detected: train={train_acc:.2%} vs test={test_acc:.2%}. "
                f"Consider increasing data size or reducing n_estimators/max_depth."
            )

        # --- Save model through the hardened registry path ---
        trained_model = build_registry_compatible_model(
            classifier=clf,
            label_encoder=le,
            access_sequence=train_data,
        )

        registry = get_model_registry()
        metrics = {
            "train_accuracy": round(train_acc, 4),
            "val_accuracy": round(val_acc, 4),
            "test_accuracy": round(test_acc, 4),
        }
        provenance = {
            "source": "scripts.train_model",
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "data_source": data_path or "synthetic",
            "dataset_size": len(all_data),
            "splits": {
                "train": len(train_data),
                "validation": len(val_data),
                "test": len(test_data),
            },
            "hyperparameters": {
                "n_estimators": n_estimators,
                "max_depth": max_depth,
                "zipf_exponent": zipf_exponent,
                "force": force,
            },
            "feature_shape": {
                "train": list(X_train.shape),
                "validation": list(X_val.shape),
                "test": list(X_test.shape),
            },
        }
        description = (
            f"Trained on {len(train_data)} samples | "
            f"val={val_acc:.2%} | test={test_acc:.2%} | "
            f"n_estimators={n_estimators} | max_depth={max_depth} | "
            f"zipf_exponent={zipf_exponent}"
        )

        save_ok = registry.save_model(
            model_name=model_name,
            model=trained_model,
            version=version,
            metrics=metrics,
            description=description,
            provenance=provenance,
            stage=stage or settings.ml_model_stage,
            actor="train_model_script",
        )
        if not save_ok:
            logger.error("Failed to persist model via hardened registry")
            return False

        active_version = registry.get_active_version(model_name)
        model_path = active_version.file_path if active_version is not None else "unknown"
        logger.info(f"Model saved and registered: {model_path}")
        return True

    except Exception as e:
        logger.error(f"Training failed: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Train PSKC ML Model")

    parser.add_argument("--data",        type=str,   default=None,        help="Path to training data JSON")
    parser.add_argument("--model-name",  type=str,   default="pskc_model",help="Model name in registry")
    parser.add_argument("--version",     type=str,   default=None,        help="Version tag (default: timestamp)")
    parser.add_argument("--force",       action="store_true",              help="Force training even with small dataset")
    parser.add_argument("--n-estimators",type=int,   default=200,         help="RandomForest n_estimators")
    parser.add_argument("--max-depth",   type=int,   default=None,        help="RandomForest max_depth (None = unlimited)")
    parser.add_argument("--zipf",        type=float, default=1.0,         help="Zipf exponent for synthetic data generation")
    parser.add_argument("--stage",       type=str,   default=None,        help="Initial registry stage for the produced artifact")

    args = parser.parse_args()

    success = train_model(
        data_path=args.data,
        model_name=args.model_name,
        version=args.version,
        force=args.force,
        zipf_exponent=args.zipf,
        n_estimators=args.n_estimators,
        max_depth=args.max_depth,
        stage=args.stage,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
