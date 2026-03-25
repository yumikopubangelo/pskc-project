# Phase 3D Quick Reference - API Endpoints

## Three New Endpoints Implemented

### 1. POST /ml/training/simulation-events
**Send simulation events for drift analysis**
```bash
curl -X POST http://localhost:8000/ml/training/simulation-events \
  -H "Content-Type: application/json" \
  -d '{
    "events": [{
      "simulation_id": "sim_1",
      "timestamp": 1707996000.0,
      "key_id": "key_1",
      "service_id": "service_1",
      "latency_ms": 45.5,
      "cache_hit": true
    }]
  }'
```

Returns: `{success, message, events_processed, drift_detected, drift_score}`

---

### 2. GET /ml/training/drift-status
**Check current drift and cooldown status**
```bash
curl http://localhost:8000/ml/training/drift-status
```

Returns: `{drift_score, should_retrain, major_changes, cooldown_remaining_seconds}`

---

### 3. POST /ml/training/retrain-from-simulation
**Trigger retraining from simulation events**
```bash
curl -X POST http://localhost:8000/ml/training/retrain-from-simulation \
  -H "Content-Type: application/json" \
  -d '{
    "force": false,
    "description": "Retraining triggered"
  }'
```

Returns: `{success, retraining_id, drift_score, events_used, expected_duration_seconds}`

Then monitor via: `WS /ml/training/progress/stream`

---

## Files Modified
- `src/api/schemas.py` - Added 5 new Pydantic models
- `src/api/routes.py` - Added 3 new endpoints + imports
- `src/ml/trainer.py` - Added `get_training_patterns()` method

---

## What Each Endpoint Does

| Endpoint | Purpose | When to Use |
|----------|---------|------------|
| POST simulation-events | Analyze drift from events | After each simulation |
| GET drift-status | Check current status | Before deciding to retrain |
| POST retrain-sim | Trigger retraining | When drift > threshold |

---

## Full Workflow

```
1. Organic Simulation Runs
   ↓
2. POST /ml/training/simulation-events
   (sends events, gets drift_score)
   ↓
3. GET /ml/training/drift-status
   (checks if should_retrain)
   ↓
4. POST /ml/training/retrain-from-simulation
   (if should_retrain=true)
   ↓
5. WS /ml/training/progress/stream
   (monitor progress)
   ↓
6. Accuracy improves ✓
   24-hour cooldown activates
```

---

## Key Integration Points

```python
# From routes.py
from src.ml.simulation_event_handler import SimulationEvent, SimulationPatternExtractor
from src.ml.pattern_analyzer import PatternAnalyzer
from src.ml.auto_retrainer import get_auto_retrainer
from src.ml.trainer import get_model_trainer

# Usage flow in endpoints:
trainer = get_model_trainer()
patterns = trainer.get_training_patterns()  # New method!
analyzer = PatternAnalyzer(patterns)
drift = analyzer.analyze_drift(sim_patterns)
retrainer = get_auto_retrainer()
decision = retrainer.decide(drift.drift_score, event_count)
```

---

## Configuration (Already Ready)

```python
# From config/settings.py
ml_simulation_drift_threshold = 0.3              # 30%
ml_simulation_min_samples = 1000                 # Min events
ml_simulation_retraining_cooldown_hours = 24     # 24-hour cooldown
ml_simulation_learning_enabled = True            # Master toggle
```

---

## Status: ✅ PHASE 3D COMPLETE

All three endpoints:
- ✅ Fully implemented
- ✅ Error handling complete
- ✅ Logging comprehensive
- ✅ Ready for testing
- ✅ Integrated with Phase 3A/3B/3C

**Next Phase**: Phase 3E - Database Support
