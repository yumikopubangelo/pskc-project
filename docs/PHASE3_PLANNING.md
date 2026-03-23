# PHASE 3: Simulation Learning Integration - Detailed Plan

## Overview

Phase 3 enables the ML model to learn from simulation events in real-time. When users run organic simulations, the system automatically captures simulation data, detects pattern changes (drift), and can trigger model retraining with the new patterns.

**Goal**: Close the feedback loop - simulations → learning → model improvement

## Current State (End of Phase 2)

✅ **Phase 1**: ML accuracy improved (7 enhancements implemented)
✅ **Phase 2**: Real-time frontend progress tracking (WebSocket + React components)
→ **Phase 3**: Auto-learning from simulations (next)

## Architecture Overview

```
Organic Simulation
       ↓
    [Runs for 60-300 seconds]
       ↓
  Capture Events
    (key access patterns)
       ↓
 Extract Features
  (frequency, timing, sequences)
       ↓
  Pattern Analyzer
   (detect drift)
       ↓
   IF drift > 0.3:
    AutoRetrainer
   (smart decision)
       ↓
   IF should_retrain:
   ╔═════════════════╗
   ║  RETRAIN MODEL  ║
   ║  with simulation║
   ║  + historical   ║
   ║  training data  ║
   ╚═════════════════╝
       ↓
  Track Improvement
   (compare accuracy)
       ↓
  Display on Dashboard
```

## Implementation Phases

### PHASE 3A: Simulation Event Capture & Feature Extraction (Days 1-2)

**Goal**: Collect simulation events and convert them to training features

#### Files to Create

##### 1. `src/ml/simulation_event_handler.py` (350 lines)

**Purpose**: Handle simulation events from organic simulations

**Classes**:

```python
class SimulationEvent:
    """Single event from a simulation"""
    simulation_id: str          # Which simulation this came from
    timestamp: float            # When it happened
    key_id: str                 # Which key was accessed
    service_id: str             # Which service accessed it
    access_type: str            # 'read', 'write', 'delete'
    latency_ms: float          # Latency in milliseconds
    cache_hit: bool            # Cache hit or miss
    metadata: Dict[str, Any]   # Additional data

class SimulationEventCollector:
    """Collect events from simulations during execution"""
    
    def __init__(self):
        self.events: List[SimulationEvent] = []
        self.simulation_id: Optional[str] = None
    
    def start_collection(self, simulation_id: str):
        """Begin collecting for a simulation"""
    
    def add_event(self, event: SimulationEvent):
        """Add event during simulation"""
    
    def finish_collection(self) -> List[SimulationEvent]:
        """Finish and return all collected events"""
    
    def get_stats(self) -> Dict[str, Any]:
        """Get collection stats (count, duration, etc)"""

class SimulationEventNormalizer:
    """Convert simulation events to training data format"""
    
    def normalize(self, event: SimulationEvent) -> Dict[str, float]:
        """Convert event to feature vector matching training format"""
        # Return dict with keys: 
        # - frequency, recency, temporal_entropy, 
        # - locality_score, cache_hit_rate, etc.
    
    def normalize_batch(self, events: List[SimulationEvent]) -> List[Dict]:
        """Normalize multiple events"""

class SimulationPatternExtractor:
    """Extract patterns from simulation events"""
    
    def extract_patterns(self, events: List[SimulationEvent]) -> Dict[str, Any]:
        """
        Extract high-level patterns:
        - Access frequency distribution
        - Sequence patterns (which keys accessed together)
        - Temporal patterns (time between accesses)
        - Service-specific patterns
        """
    
    def get_key_frequency_dist(self) -> Dict[str, int]:
        """Distribution of key accesses"""
    
    def get_temporal_patterns(self) -> Dict[str, Any]:
        """Timing patterns"""
    
    def get_sequence_patterns(self) -> List[Tuple[str, ...]]:
        """N-gram sequences of keys"""
```

**Key Methods**:
- `normalize_event()` - Convert simulation event to feature vector
- `extract_patterns()` - Find high-level patterns (frequencies, sequences, timing)
- `compare_with_training()` - Show how simulation patterns differ from training

#### Integration Points

1. **Hook into `live_simulation_service.py`**:
   ```python
   # In OrganicSimulationSession.__init__():
   self.event_collector = SimulationEventCollector()
   self.event_collector.start_collection(session_id)
   
   # During simulation event generation:
   self.event_collector.add_event(SimulationEvent(...))
   
   # In OrganicSimulationSession.__exit__():
   events = self.event_collector.finish_collection()
   # Send to pattern analyzer
   ```

2. **Background Job for Event Processing**:
   ```python
   # New job in src/api/ml_service.py
   async def process_simulation_events(events: List[SimulationEvent]):
       normalizer = SimulationEventNormalizer()
       features = [normalizer.normalize(e) for e in events]
       # Store or analyze
   ```

### PHASE 3B: Drift Detection & Pattern Analysis (Days 2-3)

**Goal**: Detect when simulation patterns differ from training patterns

#### Files to Create

##### 2. `src/ml/pattern_analyzer.py` (250 lines)

**Purpose**: Compare simulation patterns with training data patterns

**Classes**:

```python
class PatternAnalyzer:
    """Analyze patterns in simulation vs training data"""
    
    def __init__(self, training_patterns: Dict[str, Any]):
        self.training_patterns = training_patterns
    
    def analyze_drift(self, simulation_patterns: Dict[str, Any]) -> DriftReport:
        """
        Compare simulation patterns to training patterns
        
        Returns DriftReport with:
        - drift_score: 0-1 (0=same, 1=completely different)
        - changes: Dict of what changed
        - recommendation: "retrain" or "no_action"
        """
    
    def compare_distributions(self, 
                            sim_dist: Dict[str, float], 
                            train_dist: Dict[str, float]) -> float:
        """
        Compare two distributions using Jensen-Shannon divergence
        Returns score 0-1
        """
    
    def get_detailed_comparison(self) -> Dict[str, Any]:
        """
        Detailed breakdown:
        - Frequency distribution comparison
        - Temporal pattern changes
        - Sequence pattern changes
        - Service distribution changes
        """

class DriftReport:
    """Result of drift analysis"""
    drift_score: float              # 0-1, higher = more drift
    major_changes: List[str]        # What changed significantly
    recommendations: List[str]      # What to do
    details: Dict[str, Any]         # Detailed metrics
    timestamp: float                # When calculated
    
    def should_retrain(self, threshold: float = 0.3) -> bool:
        """Return True if drift > threshold"""

class DistributionAnalyzer:
    """Low-level distribution comparison"""
    
    @staticmethod
    def jensen_shannon_divergence(p: Dict, q: Dict) -> float:
        """JS divergence between two distributions, 0-1"""
    
    @staticmethod
    def kolmogorov_smirnov_test(sim: List[float], train: List[float]) -> float:
        """KS test for temporal data"""
    
    @staticmethod
    def compare_frequency_changes(sim: Dict[str, int], 
                                  train: Dict[str, int]) -> Dict[str, float]:
        """See which keys changed frequency"""
```

**Key Algorithms**:
- **Jensen-Shannon Divergence**: Compare key access frequency distributions
  - 0 = identical distributions
  - 1 = completely different
- **Temporal Analysis**: Check if access timing patterns changed
  - Use histogram comparison for latency
  - Analyze inter-arrival times
- **Sequence Analysis**: Check if key access sequences changed
  - Compare bigrams/trigrams
  - Use edit distance for sequence changes

**Drift Score Calculation**:
```
drift_score = 0.4 * frequency_divergence 
            + 0.3 * temporal_divergence 
            + 0.3 * sequence_divergence

If drift_score > 0.3 (30% different): "significant drift detected"
```

### PHASE 3C: Auto-Retraining Logic (Days 3-4)

**Goal**: Intelligently decide when to retrain

#### Files to Create

##### 3. `src/ml/auto_retrainer.py` (200 lines)

**Purpose**: Smart decisions about retraining

**Classes**:

```python
class RetrainingDecision:
    """Decision about whether to retrain"""
    should_retrain: bool
    reason: str
    confidence: float           # 0-1, how confident in decision
    recommended_data_size: int  # How many events to use
    cooldown_remaining_seconds: Optional[float]

class AutoRetrainer:
    """Make smart retraining decisions"""
    
    def __init__(self, 
                 drift_threshold: float = 0.3,
                 min_sample_count: int = 1000,
                 cooldown_hours: int = 24):
        self.drift_threshold = drift_threshold
        self.min_sample_count = min_sample_count
        self.cooldown_hours = cooldown_hours
        self.last_simulation_retraining: Optional[float] = None
    
    def decide(self, 
              drift_report: DriftReport,
              simulation_event_count: int,
              manual_override: bool = False) -> RetrainingDecision:
        """
        Decide whether to retrain
        
        Logic:
        1. If manual_override: retrain immediately
        2. If cooldown active: no (unless manual)
        3. If drift < threshold: no
        4. If events < min_count: no (wait for more)
        5. Otherwise: yes
        """
    
    def is_cooldown_active(self) -> bool:
        """Check if retraining cooldown is active"""
    
    def get_cooldown_remaining(self) -> Optional[float]:
        """Seconds until cooldown expires"""
    
    def mark_retraining_started(self):
        """Record when retraining was triggered"""
    
    def get_stats(self) -> Dict[str, Any]:
        """Statistics about auto-retraining"""
```

**Retraining Decision Logic**:

```
Input: drift_report, simulation_events, manual_override

if manual_override:
    return RetrainingDecision(should_retrain=True, reason="manual")

if cooldown_active and not manual:
    return RetrainingDecision(
        should_retrain=False, 
        reason=f"cooldown active, {hours_remaining} hours"
    )

if drift_report.drift_score < threshold:
    return RetrainingDecision(
        should_retrain=False,
        reason=f"drift {drift_score:.2f} < threshold {threshold}"
    )

if simulation_events < min_count:
    return RetrainingDecision(
        should_retrain=False,
        reason=f"need {min_count} events, have {simulation_events}"
    )

# All checks passed
return RetrainingDecision(
    should_retrain=True,
    reason="drift significant, events sufficient"
)
```

**Cooldown Strategy**:
- **Default**: 24 hours between simulation-based retrainings
- **Purpose**: Prevent constant retraining from noisy drift signals
- **Override**: Users can force retraining with `force=true` parameter
- **Tracking**: Store `last_simulation_retraining` timestamp in database

### PHASE 3D: Integration with Simulation Service (Days 4-5)

**Goal**: Hook into live simulations to capture events

#### Files to Modify

##### Modify: `src/api/live_simulation_service.py`

**Changes**:
1. Import `SimulationEventCollector`
2. Add to `OrganicSimulationSession`:
   ```python
   def __init__(self, ...):
       self.event_collector = SimulationEventCollector()
       self.event_collector.start_collection(session_id)
   
   async def run(self):
       try:
           # ... existing simulation code ...
           # For each simulated access:
           self.event_collector.add_event(SimulationEvent(
               simulation_id=session_id,
               timestamp=time.time(),
               key_id=key,
               service_id=service,
               access_type=access_type,
               latency_ms=latency,
               cache_hit=cache_hit
           ))
       finally:
           events = self.event_collector.finish_collection()
           await self._process_simulation_events(events)
   
   async def _process_simulation_events(self, events: List):
       """Background job to analyze and potentially retrain"""
   ```

##### Modify: `src/api/routes.py`

**Add Endpoints**:
```python
@app.post("/ml/training/simulation-events")
async def receive_simulation_events(request: SimulationEventsRequest) -> Dict:
    """Receive event batch from simulation"""
    # Process events
    # Store in database
    # Trigger drift analysis
    # Return status

@app.get("/ml/training/drift-status")
async def get_drift_status() -> DriftStatusResponse:
    """Get current drift score"""
    # Return: drift_score, changes, recommendation
    # Can call immediately or async

@app.post("/ml/training/retrain-from-simulation")
async def retrain_from_simulation(
    request: RetrainingRequest
) -> TrainingProgressUpdate:
    """Force retraining with simulation events"""
    # Validate request
    # Trigger async retraining
    # Return training started message
```

### PHASE 3E: Database Schema Updates (Day 5)

**Goal**: Store simulation events and retraining history

#### Files to Create

##### 4. `database/migrations/004_add_simulation_tables.sql`

```sql
-- Simulation events table
CREATE TABLE IF NOT EXISTS simulation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id TEXT NOT NULL,
    session_id TEXT,
    timestamp REAL NOT NULL,
    event_type TEXT,
    key_id TEXT,
    service_id TEXT,
    access_type TEXT,
    latency_ms REAL,
    cache_hit BOOLEAN,
    features JSON,
    created_at REAL DEFAULT (strftime('%s', 'now')),
    INDEX idx_simulation_id (simulation_id),
    INDEX idx_timestamp (timestamp),
    INDEX idx_created_at (created_at)
);

-- Retraining history from simulations
CREATE TABLE IF NOT EXISTS simulation_retraining_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id TEXT,
    drift_score REAL,
    event_count INTEGER,
    accuracy_before REAL,
    accuracy_after REAL,
    improvement_percent REAL,
    retraining_started_at REAL,
    retraining_completed_at REAL,
    status TEXT,  -- 'started', 'completed', 'failed'
    notes TEXT,
    created_at REAL DEFAULT (strftime('%s', 'now')),
    INDEX idx_created_at (created_at)
);

-- Drift analysis history
CREATE TABLE IF NOT EXISTS drift_analysis_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id TEXT,
    drift_score REAL,
    distribution_divergence REAL,
    temporal_divergence REAL,
    sequence_divergence REAL,
    major_changes JSON,
    analysis_timestamp REAL,
    created_at REAL DEFAULT (strftime('%s', 'now')),
    INDEX idx_created_at (created_at)
);
```

### PHASE 3F: API Schemas & Responses (Day 5)

**Goal**: Define data structures for new endpoints

#### Files to Modify

##### Modify: `src/api/schemas.py`

**Add Schemas**:
```python
class SimulationEventRequest(BaseModel):
    """Single simulation event"""
    simulation_id: str
    timestamp: float
    key_id: str
    service_id: str
    access_type: str = "read"
    latency_ms: float = 0.0
    cache_hit: bool = False

class SimulationEventsRequest(BaseModel):
    """Batch of simulation events"""
    events: List[SimulationEventRequest]
    metadata: Optional[Dict[str, Any]] = None

class DriftStatusResponse(BaseModel):
    """Drift analysis result"""
    drift_score: float              # 0-1
    last_analysis_timestamp: float
    should_retrain: bool
    major_changes: List[str]
    simulation_event_count: int
    recommendation: str
    next_retraining_available_at: Optional[float]

class RetrainingFromSimulationRequest(BaseModel):
    """Request to retrain from simulation data"""
    force: bool = False
    description: Optional[str] = None
    use_events_since: Optional[float] = None  # Timestamp

class RetrainingFromSimulationResponse(BaseModel):
    """Response for simulation retraining started"""
    success: bool
    message: str
    retraining_id: str
    expected_duration_seconds: int
    # Then use TrainingProgressUpdate for streaming
```

### PHASE 3G: Documentation (Day 6)

**Goal**: Comprehensive documentation

#### Files to Create

##### 5. `docs/PHASE3_SIMULATION_LEARNING.md`

- Architecture overview with diagrams
- How simulation events are captured
- Drift detection algorithm explanation
- Auto-retraining logic and cooldown
- API endpoint documentation
- Configuration options
- Example workflows

##### 6. `docs/SIMULATION_EVENT_FORMAT.md`

- Simulation event schema
- Feature extraction details
- Normalization rules
- Pattern extraction algorithms
- Drift score calculation

### PHASE 3H: Testing (Day 6-7)

**Goal**: Comprehensive test coverage

#### Unit Tests

```python
# test_simulation_event_handler.py
- test_event_collection()
- test_event_normalization()
- test_pattern_extraction()

# test_pattern_analyzer.py
- test_drift_calculation()
- test_distribution_comparison()
- test_drift_report_generation()

# test_auto_retrainer.py
- test_retraining_decision()
- test_cooldown_enforcement()
- test_edge_cases()
```

#### Integration Tests

```python
# test_simulation_learning_flow.py
- test_simulation_to_retraining_flow()
- test_drift_detection_triggers_retraining()
- test_manual_override_bypasses_cooldown()
- test_accuracy_improves_after_simulation_training()
```

#### Manual Testing

1. Run organic simulation
2. Check `drift_status` endpoint
3. Verify events stored in database
4. Trigger retraining manually if needed
5. Compare accuracy before/after

## Configuration

**Add to `config/settings.py`**:

```python
# Simulation Learning Configuration
ml_simulation_drift_threshold: float = 0.3          # 30% threshold
ml_simulation_min_samples: int = 1000               # Min events to retrain
ml_simulation_retraining_cooldown_hours: int = 24   # Cooldown period
ml_simulation_event_window_days: int = 7            # Use recent events only
ml_simulation_learning_enabled: bool = True         # Master toggle
ml_simulation_accuracy_improvement_threshold: float = 0.02  # 2% gain needed
ml_simulation_max_concurrent_retrainings: int = 1   # Prevent stacking
```

## Testing Checklist

- [ ] Event collection doesn't slow simulation
- [ ] Drift detection works for 3+ traffic profiles
- [ ] Auto-retrainer respects cooldown
- [ ] Manual override bypasses cooldown
- [ ] Retraining accuracy improves ≥2%
- [ ] Database stores all events correctly
- [ ] API responses match schemas
- [ ] No memory leaks with event collection

## Success Criteria

✅ **Functional**:
- Events captured from 100% of simulations
- Drift score calculated within 5 seconds of simulation end
- Retraining triggered automatically when drift > 0.3
- Model accuracy improves ≥2% from simulation training

✅ **Performance**:
- Event collection adds <5% overhead to simulation
- Drift analysis completes in <2 seconds
- Retraining starts within 10 seconds of decision

✅ **Operational**:
- Cooldown prevents excessive retraining
- Manual override works reliably
- Database queries fast even with 100K+ events
- No errors or data loss

✅ **User Experience**:
- Dashboard shows drift status
- Users can see simulation learning in progress
- Achievement badges for "simulation learning active"

## Timeline

- **Days 1-2**: Event capture & feature extraction
- **Days 2-3**: Drift detection & pattern analysis
- **Days 3-4**: Auto-retraining logic
- **Days 4-5**: Integration with simulation service
- **Day 5**: Database schema & API schemas
- **Day 6**: Documentation & test setup
- **Day 7**: Testing & bug fixes

**Total**: ~7 days of development

## Next Phase (Phase 4)

After Phase 3, Phase 4 will add:
- Achievement system for "simulation learning active"
- Dashboard display of best model metrics
- Historical tracking of improvements
- Achievement badges and leaderboard

## Risks & Mitigation

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Drift threshold too low | Constant retraining | Start at 0.3, adjust based on metrics |
| Cooldown too strict | Miss improvement opportunities | Make it configurable, allow manual override |
| Event collection slowdown | Simulation performance | Run collection in background task |
| Database grows too large | Storage issues | Implement event archival/cleanup |
| Model overfits to simulation | Performance degrades | Use regularization, monitor holdout accuracy |

## References

- Jensen-Shannon Divergence: https://en.wikipedia.org/wiki/Jensen%E2%80%93Shannon_divergence
- Kolmogorov-Smirnov Test: https://en.wikipedia.org/wiki/Kolmogorov%E2%80%93Smirnov_test
- Online Learning: https://en.wikipedia.org/wiki/Online_machine_learning
- Concept Drift: https://en.wikipedia.org/wiki/Concept_drift
