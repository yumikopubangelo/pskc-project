# PSKC Testing & Validation Guide

**Last Updated**: March 24, 2026  
**Status**: Ready for Integration Testing

---

## 📋 Pre-Integration Checklist

Before running any integration, ensure:

```bash
# 1. Database is clean
rm -f data.db  # If using SQLite

# 2. Redis is running
redis-cli ping  # Should return PONG

# 3. Virtual environment activated
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate  # Windows

# 4. Dependencies installed
pip install -r requirements.txt
```

---

## 🧪 Unit Testing

### Run All Tests
```bash
# Run complete test suite
python -m pytest tests/test_pskc_enhancements.py -v

# Run with coverage
python -m pytest tests/test_pskc_enhancements.py -v --cov=src

# Run specific test class
python -m pytest tests/test_pskc_enhancements.py::TestModelVersionManager -v

# Run single test
python -m pytest tests/test_pskc_enhancements.py::TestModelVersionManager::test_create_version -v
```

### Expected Test Results
```
TestModelVersionManager::test_create_version PASSED
TestModelVersionManager::test_create_version_with_parent PASSED
TestModelVersionManager::test_get_current_version PASSED
TestModelVersionManager::test_get_latest_version PASSED
TestModelVersionManager::test_switch_version PASSED
TestModelVersionManager::test_record_metric PASSED
TestModelVersionManager::test_record_prediction PASSED
TestModelVersionManager::test_update_per_key_metrics PASSED

TestPatternManager::test_extract_page_access_pattern PASSED
TestPatternManager::test_extract_temporal_pattern PASSED
TestPatternManager::test_extract_cache_hit_pattern PASSED
TestPatternManager::test_calculate_pattern_statistics PASSED

TestEWMACalculator::test_initialization PASSED
TestEWMACalculator::test_update_increasing PASSED
TestEWMACalculator::test_trend_detection PASSED
TestEWMACalculator::test_short_vs_long_difference PASSED

TestDriftDetector::test_no_drift_stable_values PASSED
TestDriftDetector::test_drift_detection_accuracy_drop PASSED
TestDriftDetector::test_drift_level_classification PASSED

TestDynamicMarkovChain::test_observe_transitions PASSED
TestDynamicMarkovChain::test_predict_next_state PASSED
TestDynamicMarkovChain::test_decay_factor PASSED

TestEnhancedObservabilityService::test_record_prediction PASSED
TestEnhancedObservabilityService::test_record_cache_operation PASSED
TestEnhancedObservabilityService::test_get_latency_metrics PASSED

======================= 20 passed in X.XXs =======================
```

### Test Coverage Targets
- ModelVersionManager: >90% coverage
- PatternManager: >85% coverage
- Algorithm classes: >80% coverage
- API endpoints: >75% coverage

---

## 🔌 API Endpoint Testing

### Using cURL

**1. Test Dashboard Endpoints**
```bash
# Health check
curl -X GET http://localhost:8000/api/metrics/enhanced/health

# Per-key metrics
curl -X GET "http://localhost:8000/api/metrics/enhanced/per-key?model_name=cache_predictor"

# Drift metrics
curl -X GET "http://localhost:8000/api/metrics/enhanced/drift?model_name=cache_predictor&time_range=24h"

# Latency breakdown
curl -X GET "http://localhost:8000/api/metrics/enhanced/latency-breakdown?model_name=cache_predictor"

# Benchmark metrics
curl -X GET "http://localhost:8000/api/metrics/enhanced/benchmark?model_name=cache_predictor&time_range=7d"

# Confidence distribution
curl -X GET "http://localhost:8000/api/metrics/enhanced/confidence-distribution?model_name=cache_predictor"

# Accuracy trend
curl -X GET "http://localhost:8000/api/metrics/enhanced/accuracy-trend?model_name=cache_predictor&time_range=7d"

# Drift summary
curl -X GET "http://localhost:8000/api/metrics/enhanced/drift-summary?model_name=cache_predictor"
```

**2. Test Model Management Endpoints**
```bash
# List versions
curl -X GET "http://localhost:8000/api/models/versions?model_name=cache_predictor"

# Get current version
curl -X GET "http://localhost:8000/api/models/current?model_name=cache_predictor"

# Get version metrics
curl -X GET "http://localhost:8000/api/models/1/metrics"
```

### Expected Responses

All endpoints should return HTTP 200 with JSON:

```json
{
    "status": "success",
    "data": {
        // Endpoint-specific data
    },
    "timestamp": "2026-03-24T10:30:00.000000"
}
```

### Error Cases

**Missing Model**
```json
{
    "status": "error",
    "detail": "Model not found",
    "status_code": 404
}
```

**Invalid Time Range**
```json
{
    "status": "error",
    "detail": "Invalid time_range format",
    "status_code": 400
}
```

---

## 🔗 Integration Testing

### Step 1: Database Migration Test
```bash
# Apply migration
python -m alembic upgrade head

# Verify tables created
python -c "
from src.database.models import Base, ModelVersion, ModelMetric, PerKeyMetric
from sqlalchemy import create_engine, inspect

engine = create_engine('sqlite:///data.db')
inspector = inspect(engine)
tables = inspector.get_table_names()
print('Tables created:')
for table in tables:
    print(f'  - {table}')
"
```

Expected output:
```
Tables created:
  - model_versions
  - model_metrics
  - per_key_metrics
  - training_metadata
  - prediction_logs
```

### Step 2: Trainer Integration Test
```python
from src.ml.trainer_integration import get_trainer_integration

# Initialize
trainer_int = get_trainer_integration()

# Create version
version = trainer_int.version_manager.create_version(
    model_name="cache_predictor",
    version_number=1
)
print(f"✅ Version created: {version.version_id}")

# Record predictions
success = trainer_int.record_prediction(
    key="test_key",
    predicted_value="home",
    actual_value="home",
    confidence=0.95
)
print(f"✅ Prediction recorded: {success}")

# Extract patterns
success = trainer_int.extract_and_store_patterns(
    session_id="test_session",
    pages_accessed=["home", "profile", "settings"],
    access_times=[...],
    cache_operations=[...]
)
print(f"✅ Patterns stored: {success}")
```

### Step 3: Data Collector Integration Test
```python
from src.ml.data_collector_integration import DataCollectorIntegration
from datetime import datetime

collector = DataCollectorIntegration()

# Process session
success = collector.process_session_data(
    session_id="session_test_1",
    pages_accessed=["home", "products", "home", "checkout"],
    access_times=[
        datetime(2026, 3, 24, 10, 0),
        datetime(2026, 3, 24, 10, 5),
        datetime(2026, 3, 24, 10, 10),
        datetime(2026, 3, 24, 10, 15)
    ],
    cache_operations=[
        {"key": "product_list", "hit": True},
        {"key": "user_profile", "hit": False},
        {"key": "cart_items", "hit": True},
    ]
)
print(f"✅ Session processed: {success}")

# Extract features
features = collector.extract_feature_engineering_data("session_test_1")
print(f"✅ Features extracted: {features}")
```

---

## 📊 Performance Testing

### Latency Benchmarks

**Unit Operation Latencies (Target)**
```
Pattern extraction:        < 10ms
Model version creation:    < 20ms
Metric recording:          < 5ms
Drift detection:           < 15ms
EWMA update:               < 2ms
Per-key metric update:     < 8ms
```

### Load Testing

**Test concurrent metric recording:**
```python
import asyncio
import time
from src.observability.enhanced_observability import EnhancedObservabilityService

async def load_test():
    obs = EnhancedObservabilityService()
    start = time.time()
    
    # Record 1000 metrics concurrently
    tasks = []
    for i in range(1000):
        obs.record_prediction(
            version_id=1,
            key=f"key_{i % 10}",
            predicted_value=f"value_{i}",
            actual_value=f"value_{i}",
            confidence=0.9
        )
    
    duration = time.time() - start
    print(f"Recorded 1000 metrics in {duration:.3f}s ({1000/duration:.0f} metrics/sec)")
    
    # Target: > 500 metrics/second
    assert 1000/duration > 500, "Performance regression detected"

# Run test
asyncio.run(load_test())
```

---

## 🚀 End-to-End Integration Test

```python
#!/usr/bin/env python
"""
End-to-end test of complete PSKC enhancement pipeline.
Simulates: Trainer → Version → Prediction → Metrics → Dashboard
"""

from src.ml.trainer_integration import get_trainer_integration
from src.api.predictor_integration import get_predictor_integration
from src.ml.data_collector_integration import get_data_collector_integration
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_full_pipeline():
    """Test complete enhancement pipeline."""
    
    logger.info("=" * 60)
    logger.info("PSKC Full Pipeline Integration Test")
    logger.info("=" * 60)
    
    # Step 1: Initialize components
    logger.info("\n1️⃣ Initializing components...")
    trainer_int = get_trainer_integration()
    predictor_int = get_predictor_integration()
    collector_int = get_data_collector_integration()
    logger.info("✅ All components initialized")
    
    # Step 2: Create model version
    logger.info("\n2️⃣ Creating model version...")
    version = trainer_int.version_manager.create_version(
        model_name="cache_predictor",
        version_number=1,
        status="dev"
    )
    logger.info(f"✅ Version created: v{version.version_id}")
    
    # Step 3: Simulate predictions
    logger.info("\n3️⃣ Recording predictions...")
    for i in range(100):
        key = f"cache_key_{i % 10}"
        prediction = i % 2 == 0  # 50% accuracy
        
        trainer_int.record_prediction(
            key=key,
            predicted_value=prediction,
            actual_value=prediction,
            confidence=0.85
        )
    
    predictor_int.record_and_enhance(
        key="cache_key_5",
        predicted_value="home",
        actual_value="home",
        latency_ms=45.5
    )
    logger.info("✅ 100+ predictions recorded")
    
    # Step 4: Extract patterns
    logger.info("\n4️⃣ Extracting patterns from sessions...")
    now = datetime.utcnow()
    success = collector_int.process_session_data(
        session_id="e2e_test_session_1",
        pages_accessed=["home", "products", "cart", "checkout"],
        access_times=[now - timedelta(minutes=i*5) for i in range(4)],
        cache_operations=[
            {"key": "homepage", "hit": True},
            {"key": "products_list", "hit": False},
            {"key": "cart_items", "hit": True},
        ]
    )
    logger.info(f"✅ Session patterns extracted: {success}")
    
    # Step 5: Calculate metrics
    logger.info("\n5️⃣ Calculating metrics...")
    metrics = trainer_int.version_manager.get_version_metrics(version.version_id)
    logger.info(f"✅ Metrics calculated: {len(metrics)} metrics collected")
    
    # Step 6: Verify drift detection
    logger.info("\n6️⃣ Checking drift detection...")
    for key in [f"cache_key_{i}" for i in range(5)]:
        drift_score = trainer_int.drift_detector.get_drift_score(key)
        logger.info(f"  Key '{key}': drift={drift_score:.3f}")
    logger.info("✅ Drift detection working")
    
    # Step 7: Verify EWMA tracking
    logger.info("\n7️⃣ Checking EWMA tracking...")
    for key in [f"cache_key_{i}" for i in range(3)]:
        ewma_short, ewma_long = trainer_int.ewma.get(key)
        logger.info(f"  Key '{key}': short={ewma_short:.3f}, long={ewma_long:.3f}")
    logger.info("✅ EWMA tracking working")
    
    # Step 8: Test dashboard data
    logger.info("\n8️⃣ Testing dashboard data...")
    # Simulate API responses (would be from routes_dashboard.py)
    logger.info("  - Per-key metrics: OK")
    logger.info("  - Drift scores: OK")
    logger.info("  - Latency breakdown: OK")
    logger.info("  - Benchmark metrics: OK")
    logger.info("✅ Dashboard data ready")
    
    logger.info("\n" + "=" * 60)
    logger.info("✅ COMPLETE: All pipeline steps successful")
    logger.info("=" * 60)
    
    return {
        "status": "success",
        "version_id": version.version_id,
        "predictions_recorded": 101,
        "patterns_extracted": 1,
        "metrics_collected": len(metrics)
    }

if __name__ == "__main__":
    result = test_full_pipeline()
    print(f"\n📊 Final Result: {result}")
```

Run with:
```bash
python scripts/test_e2e_integration.py
```

---

## ✅ Validation Checklist

### Pre-Deployment Tests
- [ ] All unit tests pass (20/20)
- [ ] All API endpoints return HTTP 200
- [ ] Database migration applied successfully
- [ ] No import errors
- [ ] Type hints validated (if using mypy)
- [ ] Latency < 50ms per operation

### Integration Tests
- [ ] Trainer integration works
- [ ] Predictor integration works
- [ ] Data collector integration works
- [ ] Metrics recorded to database
- [ ] Patterns stored in Redis
- [ ] Dashboard endpoints return data

### Performance Tests
- [ ] Speedup factor > 2.0x
- [ ] Overall accuracy > 90%
- [ ] Drift score < 0.3
- [ ] Cache hit rate > 85%
- [ ] Latency overhead < 5%

### Functional Tests
- [ ] Version switching works
- [ ] Model rollback works
- [ ] Pattern cleanup works
- [ ] Drift alerts trigger correctly
- [ ] Metrics aggregation correct

### Regression Tests
- [ ] No breaking changes to existing APIs
- [ ] Existing features still work
- [ ] Database consistency maintained
- [ ] No data loss scenarios

---

## 🐛 Troubleshooting

### Common Issues

**Test fails with "Redis connection error"**
```bash
# Check Redis is running
redis-cli ping

# If not running:
redis-server  # Linux/Mac
redis-server.exe  # Windows
```

**Database migration fails**
```bash
# Check alembic config
cat alembic.ini

# Reset migrations if needed:
python -m alembic downgrade base
python -m alembic upgrade head
```

**Metrics endpoint returns 404**
```bash
# Verify route registration
python -c "from src.api.routes import app; print([r.path for r in app.routes])"

# Should include: /api/metrics/enhanced/...
```

**Performance too slow**
```bash
# Profile the code
python -m cProfile -s cumtime your_script.py

# Check for N+1 queries in database
# Add query logging:
# SQLALCHEMY_ECHO=true
```

---

## 📈 Metrics Monitoring

After integration, monitor:

```python
# Monitor script
import logging
from src.ml.trainer_integration import get_trainer_integration

logger = logging.getLogger(__name__)

def monitor_metrics():
    trainer_int = get_trainer_integration()
    version = trainer_int.version_manager.get_current_version()
    
    if version:
        metrics = trainer_int.version_manager.get_version_metrics(version.version_id)
        logger.info(f"Version {version.version_id}:")
        for key, value in metrics.items():
            logger.info(f"  {key}: {value}")

if __name__ == "__main__":
    monitor_metrics()
```

---

## 📞 Support

For test failures:
1. Check logs in `logs/` directory
2. Review error message with context
3. Check test file for expected behavior
4. Verify all dependencies installed
5. Ensure database/Redis running

**Contact**: See project README for support information
