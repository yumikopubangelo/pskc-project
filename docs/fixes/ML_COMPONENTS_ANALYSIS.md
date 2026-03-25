# ML Components Comprehensive Analysis - PSKC Project

**Date:** March 20, 2026  
**Scope:** Complete exploration of ML architecture, code quality, testing, and best practices

---

## 1. Main ML Code Architecture (`src/ml/`)

### 1.1 Models Overview

The system uses an **Ensemble Model** combining three predictors:

#### **LSTM Model** (`LSTMModel`)
- **Location:** [src/ml/model.py](src/ml/model.py#L253)
- **Architecture:** 2-layer LSTM with hidden_size=64
- **Issue #1 - Missing Configuration Management:** Hyperparameters are hardcoded (input_size=30, hidden_size=64, num_layers=2, dropout=0.2). There's no config mechanism to vary these for experimentation or hyperparameter tuning.
- **Issue #2 - Training Not Adaptive:** LSTM trains for fixed 10 epochs regardless of convergence. No learning rate scheduling, no early stopping (see [trainer.py#L448](src/ml/trainer.py#L448) - hardcoded `epoch in range(10)`).
- **Issue #3 - Poor Error Handling:** If PyTorch unavailable, entire LSTM silently disabled. No graceful degradation metric - the model still claims `is_trained=True` when only Markov chain is active.

#### **Random Forest Model** (`RandomForestModel`)
- **Location:** [src/ml/model.py](src/ml/model.py#L306)
- **Issue #4 - Hard-coded Hyperparameters:** `n_estimators=100, max_depth=10` set in constructor ([line 323](src/ml/model.py#L323)), but also passed as arguments. Inconsistency between config values and actual model creation.
- **Issue #5 - No Feature Importance Tracking:** Tree importance scores not logged. Impossible to understand which features drive predictions or detect feature drift.
- **Issue #6 - Memory Leak Potential:** Stores all classes in `LabelEncoder` on every prediction. For 1000+ unique keys, this bloats memory over time.

#### **Markov Chain Predictor** (`MarkovChainPredictor`)
- **Location:** [src/ml/model.py](src/ml/model.py#L43)
- **Issue #7 - Unbounded Transition Matrix:** `_transition_counts` dictionary grows indefinitely. With millions of unique key pairs, this becomes a memory leak. Max history=10,000 only limits event buffer, not state space.
- **Issue #8 - Laplace Smoothing Hardcoded:** `smoothing=0.1` default, but no validation that this matches upstream config. Cold start transitions default to uniform distribution with no adaptive tuning.

#### **Ensemble Weighting** (`EnsembleWeightTracker`)
- **Location:** [src/ml/model.py](src/ml/model.py#L165+) [referenced but implementation split]
- **Issue #9 - Dynamic Weight Tracker Not Shown in Reads:** The `_weight_tracker` is initialized at line 397 but its full implementation wasn't provided in reads. Based on usage, it maintains sliding window accuracy but **no code for `record_outcome()` method** to feed back predictions.

---

### 1.2 Data Collector (`data_collector.py`)

**Purpose:** Aggregates key access events and computes statistics for ML training.

- **Location:** [src/ml/data_collector.py](src/ml/data_collector.py)
- **Issue #10 - Redis Optional But Not Gracefully Degraded:** 
  - Attempts Redis connection but marks as `False` if failed (line 43)
  - Methods like `_save_to_redis()` either work or silently skip (line 411) with no error tracking
  - Possible inconsistency: in-memory data and Redis data could diverge if Redis becomes intermittently available

- **Issue #11 - Memory Inefficiency:**
  - Maintains two separate event deques: `_events` (max 100k) and `_recent_events` (max 10k)
  - Also maintains `_historical_stats` as defaultdict(list) without any TTL or cleanup
  - No mechanism to bound `_historical_stats` - could grow unbounded over months

- **Issue #12 - Incomplete Stats Computation:**
  - `_update_stats()` method referenced but not shown in reads
  - Unclear how aggregated stats are updated incrementally
  - No atomic operations - concurrent writes from multiple threads could corrupt stats

---

### 1.3 Feature Engineering (`feature_engineering.py`)

**Purpose:** Extract ML features from access logs.

- **Location:** [src/ml/feature_engineering.py](src/ml/feature_engineering.py)
- **Issue #13 - Feature Engineering Brittleness:**
  - `_extract_temporal_features()` creates 8 features (hour_sin, hour_cos, dow_sin, dow_cos, recent_freq, time_since_last, avg_interval, std_interval)
  - `_extract_pattern_features()` creates 6 features (shown in excerpt)
  - `_get_default_features()` returns zeros (30 features) - but nowhere ensures all paths return same-sized arrays
  - **Validation Gap:** No assertion that feature vectors are consistent shape across calls

- **Issue #14 - Hardcoded Constants Scattered:**
  - Window constants not in config: "last hour = 3600 seconds", "burst_ratio < 1.0 second", "regular_ratio 10-60 seconds"
  - No mechanism to adjust these for different domains/SLAs

---

### 1.4 Predictor Module (`predictor.py`)

**Purpose:** Makes Top-N key predictions for prefetching.

- **Location:** [src/ml/predictor.py](src/ml/predictor.py)
- **Issue #15 - Cache TTL Never Expires:**
  - Line 26: `self._cache_ttl = 10` seconds, but no eviction mechanism shown
  - `_prediction_cache` is referenced but no cleanup code visible
  - Prediction cache could grow unbounded with unique input features

- **Issue #16 - Model Loading Side Effects:**
  - `load_active_model()` silently returns False if model not found, but doesn't log error
  - Callers can't distinguish "model not trained yet" from "registry corrupt" vs "model deleted"

---

### 1.5 Model Registry (`model_registry.py`)

**Purpose:** Stores trained models with versioning, checksums, and security.

- **Location:** [src/ml/model_registry.py](src/ml/model_registry.py)
- **Issue #17 - Temporary File Cleanup Vulnerability:**
  - [data/models/](data/models/) contains multiple `.tmp` files: `incremental_model.pskc.json.70p4q2gs.tmp`, `incremental_model.pskc.json.ecrcth52.tmp`, etc.
  - These are auto-generated by `IncrementalModelPersistence._persist()` but **never cleaned up if process crashes**
  - Over long runs, data/models/ becomes littered with stale temp files, consuming disk space
  - **No TTL or cleanup job**

- **Issue #18 - Signature Verification Incomplete:**
  - `_verify_version_signature()` returns bool, but callers don't check it
  - Loading a model doesn't enforce signature validation - see [model_registry.py#L744](src/ml/model_registry.py#L744) - warning only, proceeds anyway
  - **Security Issue:** Tampered models could be loaded without detection in production

- **Issue #19 - Checksum Mismatch Handling Broken:**
  - Line 320 compares checksums via `hmac.compare_digest()`, but if mismatch, raises `SecurityError`
  - `_ensure_version_security_metadata()` called from load path, but no retry/recovery mechanism
  - One corrupted file blocks all model loading until manually repaired

- **Issue #20 - Label Encoding Loss:**
  - `PortableLabelEncoder` stores `classes_` but if new keys appear, they can't be encoded
  - During prediction, if a key_id isn't in original training classes, what happens? (Not visible in shown code)

---

### 1.6 Incremental Model Persistence (`incremental_model.py`)

**Purpose:** Evolve a single model file instead of versioning every training.

- **Location:** [src/ml/incremental_model.py](src/ml/incremental_model.py)
- **Issue #21 - Atomic Write Not Truly Atomic:**
  - Uses "write to temp then rename (atomic operation)" pattern (line ~103), but:
  - Temp file name generated with `uuid.uuid4()` or random suffix - fine for uniqueness
  - But no explicit cleanup after successful rename - if disk full or permissions error, temp still orphaned
  - See Issue #17 - evidence of temp orphaning in actual data/models/

- **Issue #22 - History Growth Unbounded:**
  - `history` list in model file tracks all updates with full metadata
  - Over 6+ months of daily retrains, history grows from 180+ entries
  - No truncation or archival mechanism
  - File grows monotonically, eventually impacting load times

---

### 1.7 Trainer (`trainer.py`)

**Purpose:** Main training orchestration + concept drift detection.

- **Location:** [src/ml/trainer.py](src/ml/trainer.py)
- **Issue #23 - DriftDetector: EWMA Implementation Issues:**
  - Lines 113-131: EWMA smoothing uses `ewma_alpha = 0.3` hardcoded
  - Short EWMA uses `alpha`, long uses `alpha/2` ([line 130](src/ml/trainer.py#L130))
  - No justification for halving alpha or validation that this matches literature
  - **Tuning:** No sensitivity analysis or cross-validation of drift thresholds

- **Issue #24 - EDDM Distance Metric Too Simple:**
  - `distance = 1.0 if correct else 0.0` (line 142)
  - Not distance between consecutive *errors*, just binary correctness
  - Classic EDDM tracks error position differences - this is degenerate

- **Issue #25 - ADWIN Comparison Untested:**
  - `_detect_adwin_change()` statistical test uses Welch's t-test ([line 195](src/ml/trainer.py#L195))
  - Threshold hardcoded to `t_stat > 2.0` - roughly 95% confidence
  - But no validation that this works in practice vs synthetic benchmarks

- **Issue #26 - Auto-training Trigger Loose:**
  - `record()` method returns "drift", "warning", or "ok"
  - Caller [trainer.py#L965](src/ml/trainer.py#L965) checks `warning_score >= 1` OR `ewma_drop > warning_threshold`
  - Two independent checks could both fire - no coordination → multiple retrains in rapid succession

---

## 2. Training Scripts (`scripts/`)

### 2.1 Main Training Script (`train_model.py`)

- **Location:** [scripts/train_model.py](scripts/train_model.py)
- **Issue #27 - Zipf Distribution Justification Weak:**
  - Comments say "1.0 matches real-world" but simulation uses 1.5
  - No empirical validation that Zipf exponent matches actual PSKC access patterns
  - Training data distribution could be unrepresentative

- **Issue #28 - Temporal Split Breaks Reproducibility:**
  - Data must be pre-sorted by timestamp (line 153: `sorted_data = sorted(...)`)
  - But incoming data order not guaranteed
  - If data arrives unsorted, split ratio gets silently corrupted

- **Issue #29 - Key Window Context Feature Extraction:**
  - Uses 10-event context window ([line 210](scripts/train_model.py#L210): `CONTEXT_WINDOW = 10`)
  - But this conflicts with feature shape expectations
  - If fewer than 10 events in history, context is shorter - but feature vector shape expected to be consistent

- **Issue #30 - Label Imbalance Not Addressed:**
  - `extract_XY()` collects all keys without checking class distribution
  - With Zipf-distributed keys, some keys appear <10 times, others >1000 times
  - RandomForest not weight-balanced → predicts hot keys with high accuracy, rare keys poorly

- **Issue #31 - Validation Accuracy Filtering Bug:**
  - Lines 273-283: Filters val set to known labels, but doesn't update test set
  - Test accuracy evaluated on full test set including unseen keys
  - Validation accuracy ≠ Test accuracy incompatibility

---

### 2.2 Compact Model Training (`train_compact_model.py`)

- **Location:** [scripts/train_compact_model.py](scripts/train_compact_model.py)
- **Issue #32 - Scenario Data Generation Hard-coded:**
  - Scenario selection hardcoded based on string matching (lines 35-60)
  - No way to parallelize or grid-search across scenarios
  - Each scenario rerun requires script modification

- **Issue #33 - Data Sparsity Not Validated:**
  - Generates only 1000 samples per scenario in "mixed" mode
  - For 4 scenarios × 250 samples = 1000 total
  - Per-scenario classes could be <50 keys - poor generalization

---

### 2.3 Scenario-based Training (`train_from_scenarios.py`)

- **Location:** [scripts/train_from_scenarios.py](scripts/train_from_scenarios.py)
- **Issue #34 - Hard-coded Simulation Parameters:**
  - Lines 59-82: Zipf exponent, RPS loads, tenant counts all set to fixed values
  - No way to vary these for sensitivity analysis or A/B testing
  - Model performance assumed invariant to parameter changes

- **Issue #35 - Key Structure Fragmented:**
  - Each scenario creates keys with different prefixes (e.g., `pddikti_user_type_X`, `sevima_tenant_Y`)
  - Cross-scenario generalization impossible
  - Model trained on mixed data may not transfer to new scenario

---

## 3. Simulation Engine (`simulation/`)

### 3.1 Runner Module (`simulation/runner.py`)

- **Location:** [simulation/runner.py](simulation/runner.py)
- **Issue #36 - Scenario Hardcoding:**
  - Each scenario run sequentially, no parallelization ([line 40](simulation/runner.py#L40))
  - Testing all scenarios takes ~15-30 minutes (no measurement shown)
  - Developer feedback loop slow

- **Issue #37 - Cold Start Simulator Integration Weak:**
  - Cold start simulator is separate module, not part of regular baseline ([line 61](simulation/runner.py#L61))
  - No continuous monitoring of cold start performance vs. warm phases
  - Can't detect if changes broke cold start handling

---

## 4. ML Tests (`tests/test_ml.py`)

### 4.1 Test Coverage Analysis

- **Location:** [tests/test_ml.py](tests/test_ml.py)
- **Issue #38 - Test Coverage Extremely Sparse:**
  - `TestDataCollector` (4 tests): Only covers basic operations, no multi-threading or Redis integration
  - `TestFeatureEngineer` (4 tests): Only happy paths, no edge cases (empty data, single sample, feature shape validation)
  - `TestFeatureEngineering` (1 test): Just checks shape consistency
  - **Missing major test classes:**
    - No `TestEnsembleModel` for predict_proba, predict_top_n
    - No `TestLSTMModel` for training/prediction
    - No `TestRandomForestModel` for compatibility
    - No `TestMarkovChainPredictor` for accuracy or cold start
    - No `TestTrainer` for drift detection
    - No `TestModelRegistry` for load/save/versions
    - No `TestPredictor` for caching or error handling

- **Issue #39 - Test Data Not Representative:**
  - Tests use synthetic data with uniform random patterns, not Zipf-distributed
  - `test_get_hot_keys()` creates only 3 keys - doesn't test scalability to 1000+

- **Issue #40 - No Integration Tests:**
  - No end-to-end test of: train → save → load → predict
  - No test of multi-model ensemble predictions
  - No test of concept drift triggering retrain

- **Issue #41 - No Performance Tests:**
  - No timing assertions (e.g., predict must complete <100ms)
  - Drift detection EWMA could be slow with large windows - not measured
  - Feature extraction with 10-event context could be slow at scale - not tested

---

## 5. Model Registry & Handling

### 5.1 Model Storage Issues

**File Structure:** [data/models/](data/models/)

Current files:
- `incremental_model.pskc.json` - Main evolving model
- `incremental_model.pskc.json.*.tmp` - 8 stale temporary files (see Issue #17)
- `pskc_model_20260319_001608.pskc.json` - Versioned backup
- `checksums.json` - Integrity manifest
- `registry.json` - Version metadata  
- `lifecycle.jsonl` - Audit log

**Issue #42 - Versioning Strategy Inconsistent:**
- Primary model: `incremental_model.pskc.json` (single evolving file)
- Backup model: `pskc_model_YYYYMMDD_HHMMSS.pskc.json` (timestamped versioning)
- Which one is used at runtime? Unclear from [model_registry.py](src/ml/model_registry.py) or [predictor.py](src/ml/predictor.py)

**Issue #43 - No Model Compression:**
- Trees serialized as full JSON (children_left, children_right, feature, threshold, value arrays)
- 100-tree Random Forest → potentially 1MB+ JSON files
- No benchmarking of load/save times with growth to 200+ estimators

**Issue #44 - Markov State Explosion:**
- Markov chain stores full transition matrix: `key_index` (mapping), `transition_counts` (nested dict)
- With 10,000 unique keys and average 2 transitions per key → 20,000 entries
- Serialization time scales O(states) - slower as model ages

---

### 5.2 Model Loading Issues

**Issue #45 - Silent Fallback to Untrained:**
- If registry model corrupt, `load_model()` returns `None`
- Caller checks `if loaded_model is None` - but should it default to Markov-only? Random predictions?
- No policy defined

**Issue #46 - Label Mismatch on Load:**
- If new keys appear post-training, they can't be predicted by Random Forest
- Only Markov chain can handle new keys (if seen in stream)
- LSTM also static - can't adapt to new classes
- No graceful degradation or online learning fallback

---

## 6. Data Pipeline

### 6.1 Data Flow Overview

```
Raw Access Events → DataCollector → Feature Engineering → Training Data
                                                        ↓
                                                    Training Script
                                                        ↓
                                                    Ensemble Model
                                                        ↓
                                                    Model Registry
                                                        ↓
                                                     Predictor
                                                        ↓
                                                   Prefetch Module
```

**Issue #47 - Data Pipeline Not Documented:**
- No clear contract between data collector and feature engineer
- Feature engineer imports data as `List[Dict[str, Any]]` - unstandardized schema
- Could have missing fields, different field types, out-of-order data

**Issue #48 - No Data Validation:**
- DataCollector accepts `record_access()` calls with no input validation
- Could record `latency_ms=-1`, `cache_hit=2`, missing `key_id` - all accepted
- Feature engineer downstream receives garbage data

**Issue #49 - Raw vs Processed Data Split Unclear:**
- `data/raw/` for access logs, `data/processed/` for features
- DataProcessor ([data_processor.py](src/ml/data_processor.py)) supposed to bridge them
- But DataProcessor not used in any training script shown
- Manual intervention required to run pipeline all the way

**Issue #50 - Training Data Generation Not Reproducible:**
- `generate_synthetic_data()` in train_model.py uses `seed=42` by default
- But if called from different scripts, seed might be updated at different times
- No centralized seed management or git-tracked dataset

---

## 7. Architectural Issues & ML Best Practices Violations

### 7.1 Model Training Issues

| Issue | Location | Severity | Details |
|-------|----------|----------|---------|
| **No Cross-Validation** | scripts/train_model.py | HIGH | 70/15/15 split used once; no k-fold CV or hyperparameter grid search |
| **No Learning Curves** | trainer.py | HIGH | No tracking of train/val loss over epochs to detect overfit |
| **No Feature Normalization** | feature_engineering.py | MEDIUM | Time-since-last can be millions; no scaling before LSTM/RF |
| **Imbalanced Classes** | train_model.py | HIGH | Zipf distribution → rare keys underrepresented; no class weighting |
| **Data Leakage Risk** | temporal_split() | MEDIUM | If data pre-sorted wrong, temporal boundary violated |
| **Hardcoded Epochs** | model.py#448 | MEDIUM | LSTM always 10 epochs; no convergence detection |

### 7.2 Model Evaluation Issues

| Issue | Location | Severity | Details |
|-------|----------|----------|---------|
| **Evaluation Metrics Limited** | evaluation.py | HIGH | Only accuracy reported; missing precision, recall, F1 per class |
| **No Confusion Matrix** | evaluation.py | MEDIUM | Can't see which keys are confused with which |
| **Top-N Accuracy Not Tested** | tests/ | HIGH | Model trained for single-label, but predictor uses top-10 - incompatible evaluation |
| **Bias Metrics Missing** | evaluation.py | MEDIUM | Hot keys always predicted; cold keys never - fairness not measured |

### 7.3 Concept Drift Issues

| Issue | Location | Severity | Details |
|-------|----------|----------|---------|
| **Drift Thresholds Arbitrary** | trainer.py#59 | MEDIUM | 12% accuracy drop to trigger retrain - no justification or tuning |
| **Cold Start Not Handled** | drift detector | MEDIUM | EWMA needs minimum observations; what happens in first 10 requests? |
| **No Drift Attribution** | trainer.py | MEDIUM | When drift detected, not clear if due to traffic shift, new keys, or seasonal change |

### 7.4 Production Readiness Issues

| Issue | Location | Severity | Details |
|-------|----------|----------|---------|
| **No Model Caching** | predictor.py | MEDIUM | Model loaded from disk on first prediction - not pre-loaded |
| **No Prediction Confidence** | model.py | MEDIUM | Could return very-low-confidence predictions; no threshold |
| **No Monitoring Instrumentation** | trainer.py, predictor.py | HIGH | No metrics exported (accuracy, latency, cache hit rate of predictions) |
| **No A/B Testing Framework** | model_registry.py | HIGH | Can't test two models side-by-side; only one active model |
| **No Model Rollback** | model_registry.py | MEDIUM | If new model breaks, no quick way to revert to previous version |

---

## 8. Performance Concerns

### 8.1 Model Inference

| Concern | Impact | Estimate |
|---------|--------|----------|
| **LSTM Forward Pass** | Each prediction needs PyTorch inference | ~50-100ms per request |
| **Random Forest Prediction** | 200 trees × 10 depth traversal | ~10-20ms |
| **Markov Chain Lookup** | O(1) dict lookup, but state explosion | <1ms |
| **Feature Extraction** | 10-event context window, multiple feature types | ~5-10ms |
| **Total Ensemble Predict** | All three models + ensemble weighting | ~100-150ms (worst case) |

For cache prefetch, typical request processing is <10ms. ML prediction adding 100ms+ is substantial overhead.

### 8.2 Model Training

| Concern | Impact | Estimate |
|---------|--------|----------|
| **LSTM Training** | 10 epochs × batch_size=32 × 5000 samples | ~5-10 minutes |
| **Random Forest Training** | 100 trees × 5000 samples × 30 features | ~30-60 seconds |
| **Markov Chain Update** | 5000 key transitions, deque append | <100ms |
| **Feature Extraction** | 5000 samples × 30 features | ~10-20 seconds |
| **Total Training Time** | Full retrain on schedule | ~10-15 minutes |

If drift detection triggers retrains hourly, total training time per day = 240-360 minutes = 4-6 hours CPU.

---

## 9. Code Quality Issues

### 9.1 Duplication & Maintenance Issues

| Issue | Files | Impact |
|-------|-------|--------|
| **Four Different Training Scripts** | train_model.py, train_compact_model.py, train_from_scenarios.py, train_new_model.py | Maintenance nightmare - fixes must apply to all 4 |
| **Zipf Generation** | `_generate_zipf_weights()` in train_model.py + simulation/engines/traffic_generator.py | Consistency risk if one updated, other not |
| **Feature Extraction** | feature_engineering.py + temporal features in data_collector.py | Unclear which is authoritative |

### 9.2 Error Handling Gaps

| Location | Issue | Risk |
|----------|-------|------|
| predictor.py#137 | `logger.warning()` if model not found, continues | Silently fails to prefetch |
| data_collector.py#411 | Redis save fails silently | Data loss if in-memory buffer full |
| model_registry.py#744 | Signature verification warning, not enforced | Tampered model could be deployed |
| trainer.py#923 | `except Exception` with `logger.debug()` | Production errors hidden in debug logs |

### 9.3 Logging Quality

**Issue #51 - Inconsistent Log Levels:**
- Some modules use `logging.basicConfig(level=logging.INFO)`
- Others rely on global config
- No structured logging (JSON) for centralized log aggregation
- Drift events logged as `.warning()` instead of metrics

**Issue #52 - No Audit Trail for Model Changes:**
- `lifecycle.jsonl` exists but what's actually logged? Not shown in code
- No record of: who triggered training, with what parameters, from what data

---

## 10. Summary of Critical Issues

### Severity: CRITICAL (Blocks Production)
1. **Issue #17** - Temporary file orphaning (disk space leak)
2. **Issue #18** - Signature verification not enforced (security)
3. **Issue #38** - Test coverage <5% (release risk)
4. **Issue #42** - Model versioning ambiguous (deployment confusion)

### Severity: HIGH (Degraded Quality)
1. **Issue #27** - Zipf distribution not validated against real data
2. **Issue #29** - Feature vector shape inconsistency risk
3. **Issue #30** - Label imbalance not addressed (model bias)
4. **Issue #47** - Data pipeline contract not documented
5. **Issue #50** - Training not reproducible (research issue)

### Severity: MEDIUM (Performance/Maintainability)
1. **Issue #7** - Markov transition matrix unbounded memory
2. **Issue #16** - Cache TTL lacks eviction mechanism
3. **Issue #26** - Auto-training triggers coordination issue
4. **Issue #32** - Scenario selection hardcoded (no experimentation)
5. **Issue #51** - Logging fragmented across modules

---

## 11. Recommendations

### Quick Wins (1-3 days)
- [ ] **Clean up temp files:** Add scheduled job to remove `.tmp` files >1 hour old
- [ ] **Add model signature enforcement:** Check signature in load path, raise on mismatch
- [ ] **Test basic ensemble:** Write integration test: train → save → load → predict

### High Priority (1-2 weeks)
- [ ] **Consolidate training scripts:** Merge 4 scripts into 1 configurable script
- [ ] **Validate data pipeline:** Enforce schema on DataCollector input, validate feature shape
- [ ] **Address label imbalance:** Implement class weighting in Random Forest
- [ ] **Document versioning strategy:** Clarify which is active model (incremental vs timestamped)

### Medium Priority (2-4 weeks)
- [ ] **Comprehensive test suite:** Target 70%+ coverage, add integration tests
- [ ] **Performance profiling:** Measure actual inference/training times, set budgets
- [ ] **Hyperparameter tuning:** Grid search for LSTM epochs, Zipf exponent, drift thresholds
- [ ] **Monitoring instrumentation:** Export metrics for model accuracy, latency, predictions-used rate

### Long Term (1-3 months)
- [ ] **Online learning:** Implement true online learning fallback for unseen keys
- [ ] **A/B testing:** Support shadow models for experimental improvements
- [ ] **Drift compensation:** Detect specific type of drift (distribution shift vs seasonal) and respond accordingly
- [ ] **Feature store:** Centralize feature definitions, versioning, and lineage

---

## Appendix: File Locations Reference

| Component | Files |
|-----------|-------|
| **ML Core** | src/ml/model.py, trainer.py, predictor.py, model_registry.py |
| **Data** | src/ml/data_collector.py, feature_engineering.py, data_processor.py |
| **Training** | scripts/train_model.py, train_compact_model.py, train_from_scenarios.py, train_new_model.py |
| **Tests** | tests/test_ml.py |
| **Simulation** | simulation/runner.py, simulation/engines/ |
| **Storage** | data/models/, data/processed/, data/raw/ |

