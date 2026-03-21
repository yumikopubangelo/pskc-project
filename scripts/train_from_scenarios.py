#!/usr/bin/env python3
"""
Train model using real simulation scenarios from simulation/scenarios folder
This produces more realistic and accurate models for production use
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import logging
import random
import math
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Import simulation scenarios
from simulation.scenarios.pddikti_auth import simulate_pddikti_request, get_user_type, get_pddikti_traffic_pattern
from simulation.scenarios.sevima_cloud import simulate_sevima_request
from simulation.scenarios.siakad_sso import simulate_request as simulate_siakad_request, get_service_type, get_academic_period_multiplier
from simulation.scenarios.dynamic_production import simulate_dynamic_request

def generate_scenario_data(n_samples=2500, scenario="mixed"):
    """
    Generate training data from real simulation scenarios.
    
    Args:
        n_samples: Total samples to generate
        scenario: Which scenario to use (pddikti, sevima, siakad, dynamic, mixed)
    """
    data = []
    base_time = datetime.now().timestamp() - 86400  # 24 hours ago
    
    # For mixed scenario, distribute samples across scenarios
    if scenario == "mixed":
        samples_per = n_samples // 4
    else:
        samples_per = n_samples
    
    # PDDikti scenario
    if scenario in ("pddikti", "mixed"):
        modes = ["normal", "pre_deadline", "deadline_week", "post_deadline", "publik_peak"]
        for i in range(samples_per):
            mode = random.choice(modes)
            result = simulate_pddikti_request(use_pskc=True, mode=mode)
            
            # Generate key_id based on user type (for ML training)
            user_type = result.get("user_type", "operator_feeder")
            key_id = f"pddikti_{user_type}_{random.randint(1, 50)}"
            
            ts = base_time + (i * 3600 / samples_per)  # Spread over 1 hour
            dt = datetime.fromtimestamp(ts)
            
            data.append({
                "key_id": key_id,
                "service_id": "pddikti_auth",
                "timestamp": ts,
                "hour": dt.hour,
                "day_of_week": dt.weekday(),
                "cache_hit": int(result.get("cache_hit", False)),
                "latency_ms": result.get("latency_ms", 0),
                "user_type": user_type,
                "mode": mode,
                "traffic_multiplier": result.get("traffic_mul", 1.0),
            })
    
    # SEVIMA scenario
    if scenario in ("sevima", "mixed"):
        rps_values = [200, 500, 800, 1000, 2000, 5000]
        tenant_counts = [50, 100, 200, 300]
        
        for i in range(samples_per):
            rps = random.choice(rps_values)
            tenants = random.choice(tenant_counts)
            result = simulate_sevima_request(use_pskc=True, rps_load=rps, tenant_count=tenants)
            
            key_id = f"sevima_tenant_{random.randint(1, 100)}"
            
            ts = base_time + ((samples_per + i) * 3600 / samples_per)
            dt = datetime.fromtimestamp(ts)
            
            data.append({
                "key_id": key_id,
                "service_id": "sevima_cloud",
                "timestamp": ts,
                "hour": dt.hour,
                "day_of_week": dt.weekday(),
                "cache_hit": int(result.get("cache_hit", False)),
                "latency_ms": result.get("latency_ms", 0),
                "rps_load": rps,
                "tenant_count": tenants,
                "load_ratio": result.get("load_ratio", 0),
            })
    
    # SIAKAD SSO scenario
    if scenario in ("siakad", "mixed"):
        periods = ["normal", "krs_online", "uts", "uas", "liburan", "wisuda"]
        
        for i in range(samples_per):
            period = random.choice(periods)
            cache_warm = random.random() > 0.2  # 80% cache warm
            result = simulate_siakad_request(use_pskc=True, period=period, cache_warm=cache_warm)
            
            service = result.get("service", "portal_nilai")
            key_id = f"siakad_{service}_{random.randint(1, 80)}"
            
            ts = base_time + ((2*samples_per + i) * 3600 / samples_per)
            dt = datetime.fromtimestamp(ts)
            
            data.append({
                "key_id": key_id,
                "service_id": "siakad_sso",
                "timestamp": ts,
                "hour": dt.hour,
                "day_of_week": dt.weekday(),
                "cache_hit": int(result.get("cache_hit", False)),
                "latency_ms": result.get("latency_ms", 0),
                "service": service,
                "period": period,
                "traffic_multiplier": result.get("traffic_mul", 1.0),
                "cache_warm": cache_warm,
            })
    
    # Dynamic Production scenario
    if scenario in ("dynamic", "mixed"):
        for i in range(samples_per):
            iteration = i
            total = samples_per
            result = simulate_dynamic_request(use_pskc=True, iteration=iteration, total_requests=total, kms_available=True)
            
            # Determine key based on phase
            if iteration < 20:
                phase = "cold_start"
            elif total * 0.3 < iteration < total * 0.6:
                phase = "stable"
            else:
                phase = "variable"
            
            key_id = f"dynamic_{phase}_{random.randint(1, 30)}"
            
            ts = base_time + ((3*samples_per + i) * 3600 / samples_per)
            dt = datetime.fromtimestamp(ts)
            
            data.append({
                "key_id": key_id,
                "service_id": "dynamic_prod",
                "timestamp": ts,
                "hour": dt.hour,
                "day_of_week": dt.weekday(),
                "cache_hit": int(result.get("cache_hit", False)),
                "latency_ms": result.get("total_ms", 0),
                "phase": phase,
                "status": result.get("status", "ok"),
            })
    
    # Shuffle data
    random.shuffle(data)
    
    return data


def main():
    logger.info("=" * 60)
    logger.info("TRAINING MODEL FROM REAL SCENARIOS")
    logger.info("=" * 60)
    
    # Generate training data from scenarios
    logger.info("\n[1] Generating training data from real scenarios...")
    n_samples = 10000
    training_data = generate_scenario_data(n_samples=n_samples, scenario="mixed")
    
    # Analyze data
    services = set(d["service_id"] for d in training_data)
    unique_keys = len(set(d["key_id"] for d in training_data))
    cache_hits = sum(1 for d in training_data if d["cache_hit"])
    hit_rate = cache_hits / len(training_data)
    
    logger.info(f"    Total samples: {len(training_data)}")
    logger.info(f"    Unique services: {len(services)}")
    logger.info(f"    Unique keys: {unique_keys}")
    logger.info(f"    Cache hit rate: {hit_rate:.1%}")
    
    # Save training data
    output_path = "data/training/scenario_training_data.json"
    with open(output_path, 'w') as f:
        json.dump(training_data, f, indent=2)
    logger.info(f"    Saved to: {output_path}")
    
    # Now train the model
    logger.info("\n[2] Training model...")
    
    from scripts.train_model import temporal_split, extract_XY, build_registry_compatible_model
    from src.ml.feature_engineering import FeatureEngineer
    from src.ml.incremental_model import get_incremental_model
    from src.ml.model_registry import get_model_registry
    
    # Split data
    train_data, val_data, test_data = temporal_split(training_data, train_ratio=0.7, val_ratio=0.15)
    logger.info(f"    Split: train={len(train_data)}, val={len(val_data)}, test={len(test_data)}")
    
    # Extract features
    engineer = FeatureEngineer()
    X_train, y_train = extract_XY(train_data, engineer)
    X_val, y_val = extract_XY(val_data, engineer)
    X_test, y_test = extract_XY(test_data, engineer)
    logger.info(f"    Features: X_train={X_train.shape}")
    
    # Train model with better hyperparameters
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import LabelEncoder
    
    le = LabelEncoder()
    le.fit(y_train)
    y_train_enc = le.transform(y_train)
    
    logger.info("    Training RandomForest (optimized)...")
    clf = RandomForestClassifier(
        n_estimators=200,
        max_depth=25,
        min_samples_split=5,
        min_samples_leaf=2,
        max_features='sqrt',
        random_state=42,
        n_jobs=-1,
        class_weight='balanced'  # Handle imbalanced classes
    )
    clf.fit(X_train, y_train_enc)
    
    # Evaluate
    known_labels = set(le.classes_)
    
    # Validation
    val_mask = [y in known_labels for y in y_val]
    X_val_filtered = X_val[val_mask]
    y_val_filtered = [y for y, m in zip(y_val, val_mask) if m]
    
    if len(y_val_filtered) > 0:
        y_val_enc = le.transform(y_val_filtered)
        val_acc = (clf.predict(X_val_filtered) == y_val_enc).mean()
    else:
        val_acc = 0.0
    
    # Test
    test_mask = [y in known_labels for y in y_test]
    X_test_filtered = X_test[test_mask]
    y_test_filtered = [y for y, m in zip(y_test, test_mask) if m]
    
    if len(y_test_filtered) > 0:
        y_test_enc = le.transform(y_test_filtered)
        test_acc = (clf.predict(X_test_filtered) == y_test_enc).mean()
    else:
        test_acc = 0.0
    
    logger.info(f"    Validation accuracy: {val_acc:.2%}")
    logger.info(f"    Test accuracy: {test_acc:.2%}")
    
    # Build and save model
    logger.info("\n[3] Saving model to incremental storage...")
    model = build_registry_compatible_model(clf, le, train_data)
    
    incremental = get_incremental_model()
    registry = get_model_registry()
    model_data = registry.serialize_model_checkpoint(model)
    
    result = incremental.update(
        model_data=model_data,
        reason='scenario_training',
        metrics={
            'accuracy': val_acc,
            'test_accuracy': test_acc,
            'train_samples': len(train_data),
            'val_samples': len(val_data),
            'test_samples': len(test_data),
        },
        training_info={
            'sample_count': len(training_data),
            'unique_keys': unique_keys,
            'cache_hit_rate': hit_rate,
            'scenario': 'mixed_real_scenarios',
        }
    )
    
    logger.info("\n" + "=" * 60)
    logger.info("TRAINING COMPLETE!")
    logger.info("=" * 60)
    logger.info(f"Model version: {result.get('version')}")
    logger.info(f"Validation accuracy: {val_acc:.2%}")
    logger.info(f"Test accuracy: {test_acc:.2%}")
    logger.info(f"Total updates: {result.get('update_count')}")
    logger.info("\nTo improve accuracy further:")
    logger.info("  1. Train with more samples (--samples 50000)")
    logger.info("  2. Use real production data instead of simulation")
    logger.info("  3. Retrain periodically with fresh data")
    logger.info("  4. Enable auto-training for continuous learning")


if __name__ == '__main__':
    main()
