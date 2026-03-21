#!/usr/bin/env python3
"""Train a new model and save to incremental model"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Import required modules
from scripts.train_model import load_training_data, temporal_split, extract_XY, build_registry_compatible_model
from src.ml.feature_engineering import FeatureEngineer
from src.ml.incremental_model import get_incremental_model
from src.ml.model_registry import get_model_registry

def main():
    # Load data
    logger.info('Loading training data...')
    all_data = load_training_data('data/training/pskc_training_data.json')
    logger.info(f'Loaded {len(all_data)} samples')

    # Split
    train_data, val_data, test_data = temporal_split(all_data)
    logger.info(f'Split: train={len(train_data)}, val={len(val_data)}, test={len(test_data)}')

    # Extract features
    engineer = FeatureEngineer()
    X_train, y_train = extract_XY(train_data, engineer)
    X_val, y_val = extract_XY(val_data, engineer)
    logger.info(f'Features extracted: X_train={X_train.shape}')

    # Train
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import LabelEncoder

    le = LabelEncoder()
    le.fit(y_train)
    y_train_enc = le.transform(y_train)

    logger.info('Training RandomForest...')
    clf = RandomForestClassifier(n_estimators=100, max_depth=20, random_state=42, n_jobs=-1)
    clf.fit(X_train, y_train_enc)

    # Evaluate
    known_labels = set(le.classes_)
    val_mask = [y in known_labels for y in y_val]
    X_val_filtered = X_val[val_mask]
    y_val_filtered = [y for y, m in zip(y_val, val_mask) if m]
    
    if len(y_val_filtered) > 0:
        y_val_enc = le.transform(y_val_filtered)
        val_acc = (clf.predict(X_val_filtered) == y_val_enc).mean()
    else:
        val_acc = 0.0
    
    logger.info(f'Validation accuracy: {val_acc:.2%}')

    # Build model
    logger.info('Building ensemble model...')
    model = build_registry_compatible_model(clf, le, train_data)

    # Save to incremental model
    logger.info('Saving to incremental model...')
    incremental = get_incremental_model()

    # Serialize
    registry = get_model_registry()
    model_data = registry.serialize_model_checkpoint(model)

    result = incremental.update(
        model_data=model_data,
        reason='manual',
        metrics={'accuracy': val_acc},
        training_info={
            'sample_count': len(all_data), 
            'train_samples': len(train_data), 
            'val_samples': len(val_data)
        }
    )

    logger.info(f'Result: {result}')
    logger.info('=== MODEL SAVED SUCCESSFULLY ===')
    logger.info(f'Version: {result.get("version")}')
    logger.info(f'Update count: {result.get("update_count")}')

if __name__ == '__main__':
    main()
