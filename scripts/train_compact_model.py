#!/usr/bin/env python3
"""
Train a compact model using simulation scenarios.
This creates a small, efficient model suitable for incremental learning.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import logging
import random
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Import simulation scenarios
from simulation.scenarios.pddikti_auth import simulate_pddikti_request
from simulation.scenarios.sevima_cloud import simulate_sevima_request
from simulation.scenarios.siakad_sso import simulate_request as simulate_siakad_request
from simulation.scenarios.dynamic_production import simulate_dynamic_request


def generate_scenario_data(n_samples=1000, scenario="mixed"):
    """
    Generate training data from simulation scenarios.
    Uses fewer samples for compact model.
    """
    data = []
    base_time = datetime.now().timestamp() - 86400
    
    if scenario == "mixed":
        samples_per = n_samples // 4
    else:
        samples_per = n_samples
    
    # PDDikti scenario
    if scenario in ("pddikti", "mixed"):
        modes = ["normal", "pre_deadline", "deadline_week"]
        for i in range(samples_per):
            mode = random.choice(modes)
            result = simulate_pddikti_request(use_pskc=True, mode=mode)
            user_type = result.get("user_type", "operator_feeder")
            key_id = f"pddikti_{user_type}_{random.randint(1, 20)}"
            ts = base_time + (i * 3600 / max(samples_per, 1))
            dt = datetime.fromtimestamp(ts)
            data.append({
                "key_id": key_id,
                "service_id": "pddikti_auth",
                "timestamp": ts,
                "hour": dt.hour,
                "day_of_week": dt.weekday(),
                "cache_hit": int(result.get("cache_hit", False)),
                "latency_ms": result.get("latency_ms", 0),
            })
    
    # SEVIMA scenario
    if scenario in ("sevima", "mixed"):
        rps_values = [200, 500, 1000]
        tenant_counts = [50, 100, 200]
        for i in range(samples_per):
            rps = random.choice(rps_values)
            tenants = random.choice(tenant_counts)
            result = simulate_sevima_request(use_pskc=True, rps_load=rps, tenant_count=tenants)
            key_id = f"sevima_tenant_{random.randint(1, 50)}"
            ts = base_time + ((samples_per + i) * 3600 / max(samples_per, 1))
            dt = datetime.fromtimestamp(ts)
            data.append({
                "key_id": key_id,
                "service_id": "sevima_cloud",
                "timestamp": ts,
                "hour": dt.hour,
                "day_of_week": dt.weekday(),
                "cache_hit": int(result.get("cache_hit", False)),
                "latency_ms": result.get("latency_ms", 0),
            })
    
    # SIAKAD SSO scenario
    if scenario in ("siakad", "mixed"):
        periods = ["normal", "krs_online", "uts", "uas"]
        for i in range(samples_per):
            period = random.choice(periods)
            cache_warm = random.random() > 0.2
            result = simulate_siakad_request(use_pskc=True, period=period, cache_warm=cache_warm)
            service = result.get("service", "portal_nilai")
            key_id = f"siakad_{service}_{random.randint(1, 40)}"
            ts = base_time + ((2*samples_per + i) * 3600 / max(samples_per, 1))
            dt = datetime.fromtimestamp(ts)
            data.append({
                "key_id": key_id,
                "service_id": "siakad_sso",
                "timestamp": ts,
                "hour": dt.hour,
                "day_of_week": dt.weekday(),
                "cache_hit": int(result.get("cache_hit", False)),
                "latency_ms": result.get("latency_ms", 0),
            })
    
    # Dynamic Production scenario
    if scenario in ("dynamic", "mixed"):
        for i in range(samples_per):
            iteration = i
            total = samples_per
            result = simulate_dynamic_request(use_pskc=True, iteration=iteration, total_requests=total, kms_available=True)
            if iteration < total * 0.3:
                phase = "cold_start"
            elif iteration < total * 0.7:
                phase = "stable"
            else:
                phase = "variable"
            key_id = f"dynamic_{phase}_{random.randint(1, 20)}"
            ts = base_time + ((3*samples_per + i) * 3600 / max(samples_per, 1))
            dt = datetime.fromtimestamp(ts)
            data.append({
                "key_id": key_id,
                "service_id": "dynamic_prod",
                "timestamp": ts,
                "hour": dt.hour,
                "day_of_week": dt.weekday(),
                "cache_hit": int(result.get("cache_hit", False)),
                "latency_ms": result.get("total_ms", 0),
            })
    
    random.shuffle(data)
    return data


def extract_features(data_list):
    """Extract simple features for training"""
    X = []
    for d in data_list:
        features = [
            d.get("hour", 12) / 24.0,
            d.get("day_of_week", 0) / 7.0,
            float(d.get("cache_hit", 0)),
            float(d.get("latency_ms", 0)) / 1000.0,
        ]
        # Add service encoding
        service = d.get("service_id", "")
        if "pddikti" in service:
            features.extend([1, 0, 0, 0])
        elif "sevima" in service:
            features.extend([0, 1, 0, 0])
        elif "siakad" in service:
            features.extend([0, 0, 1, 0])
        else:
            features.extend([0, 0, 0, 1])
        X.append(features)
    return X


def main():
    logger.info("=" * 60)
    logger.info("TRAINING COMPACT MODEL FROM SCENARIOS")
    logger.info("=" * 60)
    
    # Generate training data - use fewer samples for compact model
    logger.info("\n[1] Generating training data...")
    n_samples = 1000  # Keep it small for compact model
    training_data = generate_scenario_data(n_samples=n_samples, scenario="mixed")
    
    # Analyze
    unique_keys = len(set(d["key_id"] for d in training_data))
    cache_hits = sum(1 for d in training_data if d["cache_hit"])
    hit_rate = cache_hits / len(training_data)
    
    logger.info(f"    Total samples: {len(training_data)}")
    logger.info(f"    Unique keys: {unique_keys}")
    logger.info(f"    Cache hit rate: {hit_rate:.1%}")
    
    # Train model
    logger.info("\n[2] Training compact model...")
    
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import LabelEncoder
    
    # Extract features
    X_train = extract_features(training_data)
    y_train = [d["key_id"] for d in training_data]
    
    # Encode labels
    le = LabelEncoder()
    le.fit(y_train)
    y_enc = le.transform(y_train)
    
    # Train compact model (fewer trees, smaller depth)
    clf = RandomForestClassifier(
        n_estimators=50,      # Reduced from 200
        max_depth=10,         # Reduced from 25
        min_samples_split=5,
        min_samples_leaf=2,
        max_features='sqrt',
        random_state=42,
        n_jobs=-1,
    )
    clf.fit(X_train, y_enc)
    
    # Evaluate on training data (simple check)
    train_acc = (clf.predict(X_train) == y_enc).mean()
    logger.info(f"    Training accuracy: {train_acc:.2%}")
    logger.info(f"    Number of trees: {clf.n_estimators}")
    logger.info(f"    Max tree depth: {clf.max_depth}")
    
    # Save model
    logger.info("\n[3] Saving compact model...")
    
    from src.ml.incremental_model import get_incremental_model
    from src.ml.model_registry import get_model_registry
    from src.ml.model import EnsembleModel, MarkovChainPredictor
    
    # Create ensemble model
    ensemble = EnsembleModel(
        lstm_weight=0.3,
        rf_weight=0.5,
        markov_weight=0.2,
        num_classes=len(le.classes_),
        dynamic_weights=True
    )
    
    # Create a simple wrapper for the RF
    class RFWrapper:
        def __init__(self, clf, le):
            self.model = clf
            self.label_encoder = le
            self.is_trained = True
            self.n_estimators = clf.n_estimators
            self.max_depth = clf.max_depth
    
    ensemble.rf = RFWrapper(clf, le)
    
    # Create simple Markov chain
    markov = MarkovChainPredictor(num_classes=len(le.classes_))
    key_sequence = y_train
    for key in key_sequence:
        markov.update(key)
    ensemble.markov = markov
    ensemble.is_trained = True
    
    # Serialize and save
    registry = get_model_registry()
    model_data = registry.serialize_model_checkpoint(ensemble)
    
    incremental = get_incremental_model()
    result = incremental.update(
        model_data=model_data,
        reason='compact_scenario_training',
        metrics={
            'accuracy': train_acc,
            'train_samples': len(training_data),
        },
        training_info={
            'sample_count': len(training_data),
            'unique_keys': unique_keys,
            'cache_hit_rate': hit_rate,
            'n_estimators': clf.n_estimators,
            'max_depth': clf.max_depth,
        }
    )
    
    logger.info("\n" + "=" * 60)
    logger.info("COMPACT MODEL TRAINING COMPLETE!")
    logger.info("=" * 60)
    logger.info(f"Model version: {result.get('version')}")
    logger.info(f"Training accuracy: {train_acc:.2%}")
    logger.info(f"Total updates: {result.get('update_count')}")
    
    # Check file size
    import os
    model_path = incremental._file_path
    if os.path.exists(model_path):
        size_mb = os.path.getsize(model_path) / (1024 * 1024)
        logger.info(f"Model file size: {size_mb:.2f} MB")
    
    logger.info("\nThe model is now ready for incremental learning.")
    logger.info("To train with more data, increase n_samples in this script.")


if __name__ == '__main__':
    main()
