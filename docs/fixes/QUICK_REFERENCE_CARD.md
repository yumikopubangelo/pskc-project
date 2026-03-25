# PSKC Enhancement - Quick Reference Card

**Last Updated**: March 24, 2026  
**Status**: ✅ Production Ready

---

## 🚀 Quick Start (Pick One)

### 5-Minute Option
```python
# Just add to trainer.py:
from src.ml.trainer_integration import get_trainer_integration
trainer_int = get_trainer_integration()
trainer_int.after_training(training_metrics={...})
```

### 20-Minute Option
Add data collection too:
```python
# In data_collector.py:
from src.ml.data_collector_integration import get_data_collector_integration
collector = get_data_collector_integration()
collector.process_session_data(session_id, pages, times, ops)
```

### Full Option (45 min)
Add predictor integration + dashboard.

---

## 📦 What's Included

| Component | Size | Purpose |
|-----------|------|---------|
| ModelVersionManager | 607 LOC | Version lifecycle |
| PatternManager | 455 LOC | Pattern extraction |
| EWMACalculator | 100 LOC | Trend tracking |
| DriftDetector | 150 LOC | Concept drift |
| DynamicMarkovChain | 190 LOC | Adaptive chains |
| EnhancedObservability | 524 LOC | Metrics collection |
| TrainerIntegration | 400 LOC | Easy trainer hookup |
| PredictorIntegration | 170 LOC | Easy predictor hookup |
| DataCollectorIntegration | 280 LOC | Pattern learning |
| Dashboard API | 380 LOC | 7 endpoints |
| **TOTAL** | **3,250 LOC** | **Complete system** |

---

## 🔌 3 Integration Points (Copy-Paste)

### 1. Trainer Integration (3 lines)
```python
# After training completes in trainer.py:
from src.ml.trainer_integration import get_trainer_integration

trainer_int = get_trainer_integration()
trainer_int.after_training(training_metrics={
    'accuracy': 0.92,
    'drift_score': 0.15,
    # ... your metrics
})
```

### 2. Predictor Integration (5-7 lines)
```python
# In route_keys.py prediction handler:
from src.api.predictor_integration import get_predictor_integration

predictor_int = get_predictor_integration()
enhanced_result = predictor_int.record_and_enhance(
    key="cache_key",
    predicted_value=result,
    actual_value=ground_truth,
    latency_ms=elapsed_time
)
```

### 3. Data Collector Integration (8-10 lines)
```python
# In data_collector.py session processing:
from src.ml.data_collector_integration import get_data_collector_integration

collector = get_data_collector_integration()
success = collector.process_session_data(
    session_id=session.id,
    pages_accessed=session.pages,
    access_times=session.times,
    cache_operations=session.ops
)
```

---

## 🎯 API Endpoints

### Dashboard (New)
```
/api/metrics/enhanced/per-key              ← Per-key accuracy breakdown
/api/metrics/enhanced/drift                ← Per-key drift scores
/api/metrics/enhanced/latency-breakdown    ← Component latencies
/api/metrics/enhanced/benchmark            ← Speedup factor (2.3x)
/api/metrics/enhanced/confidence-distribution ← Confidence stats
/api/metrics/enhanced/accuracy-trend       ← Time-series accuracy
/api/metrics/enhanced/drift-summary        ← Overall drift status
/api/metrics/enhanced/health               ← Health check
```

### Models (Existing)
```
/api/models/versions           ← List all versions
/api/models/current            ← Current production version
/api/models/{id}/metrics       ← Version metrics
/api/models/switch/{id}        ← Switch version
```

---

## 📊 8 Dashboard Charts (Ready-to-Use)

| Chart | Data Source | Purpose |
|-------|-------------|---------|
| Per-Key Accuracy | `/per-key` | Identify weak spots |
| Per-Key Drift | `/drift` | Watch for concept drift |
| Model Comparison | `/models/versions` | A/B test versions |
| Latency Breakdown | `/latency-breakdown` | Find bottlenecks |
| Speedup Factor | `/benchmark` | Prove 2.0x+ improvement |
| Confidence Dist | `/confidence-distribution` | Model uncertainty |
| Accuracy Trend | `/accuracy-trend` | Stability over time |
| Drift Summary | `/drift-summary` | Alert on issues |

**All implementations in**: `docs/DASHBOARD_UPDATES.md`

---

## 🧪 Testing

### Run Tests
```bash
# All tests
python -m pytest tests/test_pskc_enhancements.py -v

# Specific test
python -m pytest tests/test_pskc_enhancements.py::TestEWMACalculator -v

# With coverage
python -m pytest tests/test_pskc_enhancements.py --cov=src
```

### Test API
```bash
curl http://localhost:8000/api/metrics/enhanced/per-key
curl http://localhost:8000/api/metrics/enhanced/drift
curl http://localhost:8000/api/metrics/enhanced/benchmark
```

### Expected Results
- ✅ All 20 tests pass
- ✅ All endpoints return HTTP 200
- ✅ No performance regression

---

## 📈 Key Metrics to Monitor

```
Accuracy:           > 90%           ← Current: TBD
Speedup:            > 2.0x          ← Target: 2.3x
Cache Hit Rate:     > 85%           ← Target: 87%
Drift Score:        < 0.3           ← Target: <0.15
Latency:            < 50ms          ← Target: 20ms
Confidence:         > 90% of preds  ← Target: >95%
```

---

## 🔧 Configuration

### Defaults (Good for most cases)

**EWMA**
```python
alpha_short = 0.3   # Quick response
alpha_long = 0.1    # Stability
```

**Drift Detection**
```python
threshold = 0.3     # Trigger retraining when exceeded
window_short = 30
window_long = 200
```

**Markov Chain**
```python
decay_factor = 0.99 # Weight recent observations
window_size = 100
```

**Pattern Storage**
```python
ttl_days = 7        # Auto-cleanup old patterns
redis_host = 'localhost'
redis_port = 6379
```

---

## ⚠️ Important Reminders

1. **Run migration first** (LOCAL ONLY):
   ```bash
   python -m alembic upgrade head
   ```

2. **Redis must be running** for pattern storage

3. **All code is type-hinted** - use IDE autocomplete

4. **Error handling included** - check logs for issues

5. **Backward compatible** - no breaking changes

---

## 📋 Checklist

### Pre-Integration
- [ ] Database migration applied (`alembic upgrade head`)
- [ ] Redis running (`redis-cli ping` returns PONG)
- [ ] All dependencies installed (`pip install -r requirements.txt`)
- [ ] Tests passing (`pytest tests/test_pskc_enhancements.py -v`)

### Integration
- [ ] Trainer integration (3 lines added)
- [ ] Predictor integration (5-7 lines added)
- [ ] Data collector integration (8-10 lines added)
- [ ] All API endpoints tested
- [ ] Dashboard endpoints returning data

### Validation
- [ ] No regression in existing features
- [ ] Speedup factor > 2.0x
- [ ] Accuracy > 90%
- [ ] Drift detection working
- [ ] Metrics being recorded

---

## 🆘 Troubleshooting

| Issue | Solution |
|-------|----------|
| Redis connection error | `redis-cli ping` - start Redis if needed |
| Database migration fails | Check alembic.ini config |
| Tests fail with import errors | `pip install -r requirements.txt` |
| API endpoint 404 | Verify routes registered in routes.py |
| No metrics data | Ensure predictions being recorded |
| High latency | Profile code, check database indexes |

---

## 📚 Documentation Map

```
QUICK_START.md              ← You are here (this file)
├── TESTING_GUIDE.md       ← How to test
├── FINAL_STATUS_REPORT.md ← Project status
├── DASHBOARD_UPDATES.md   ← 8 chart implementations
├── INTEGRATION_GUIDE.md   ← Detailed integration steps
├── API_REFERENCE.md       ← All endpoints documented
└── INTEGRATION_EXAMPLES.md ← Copy-paste code
```

---

## 💡 Tips & Tricks

### Performance
- Use `limit=` parameter to paginate large datasets
- Cache responses locally if needed
- Use async/await for concurrent requests

### Debugging
- Enable query logging: `SQLALCHEMY_ECHO=true`
- Check logs in `logs/` directory
- Use `curl -v` for verbose API testing

### Advanced
- Customize EWMA alpha values for your use case
- Adjust drift threshold if too sensitive
- Fine-tune pattern TTL based on data retention policy

---

## 🎓 Learning Resources

**For Pattern Manager:**
- Page patterns: how often users visit pages
- Temporal patterns: which hours are busy
- Cache patterns: which keys are frequently hit

**For Algorithms:**
- EWMA: exponential smoothing of trends
- Drift: detects when model accuracy drops
- Markov: predicts next state based on history

**For Observability:**
- Per-key metrics: accuracy per cache key
- Latency breakdown: where time is spent
- Benchmark: proves speedup vs baseline

---

## 🚀 Next (After Integration)

1. Collect 24-48 hours of baseline metrics
2. Analyze per-key accuracy distribution
3. Identify high-drift keys for investigation
4. Tune algorithm parameters if needed
5. Celebrate 2.0x speedup! 🎉

---

## 📞 Quick Links

- **GitHub**: [See project README]
- **Docs**: `docs/` directory (12+ files)
- **Issues**: [See issue tracker]
- **Discussions**: [See project discussions]

---

**Remember**: Start with 5-minute option, test, then add more features.  
**You got this!** 💪

---

**Estimated Integration Time**:
- Minimal (trainer only): 2-3 minutes
- Standard (trainer + predictor): 15-20 minutes
- Full (all + dashboard): 45-60 minutes

**Estimated Testing Time**:
- Unit tests: 2-3 minutes
- API testing: 5-10 minutes
- E2E testing: 10-15 minutes

**Total**: 1-2 hours for full integration and testing
