# Phase 2: Frontend Progress Tracking - Planning Guide

## Overview

Phase 2 will integrate the backend progress tracking service with the React frontend to provide real-time visual feedback during training and data generation.

## Components to Update

### 1. MLTraining.jsx - Main Training Page

**Current State**: 
- Has training form
- Shows training results

**Changes Needed**:
- Add progress tracking UI component
- Show real-time metrics (accuracy, loss, data count)
- Add ETA for data generation
- Add cancel button for long-running ops
- Track per-model performance (LSTM, RF, Markov)

**New Elements**:
```jsx
// Progress bar with percentage
<ProgressBar value={progress.progress_percent} />

// Phase indicator
<PhaseIndicator phase={progress.current_phase} />

// Real-time metrics
<MetricsDisplay metrics={progress.metrics} />

// ETA display
<ETACounter elapsed={progress.elapsed_seconds} remaining={progress.estimated_remaining_seconds} />

// Per-model accuracy
<PerModelAccuracy 
  lstm={progress.metrics.lstm_accuracy}
  rf={progress.metrics.rf_accuracy}
  markov={progress.metrics.markov_accuracy}
/>

// Cancel button
<CancelButton onClick={handleCancelTraining} />
```

### 2. WebSocket Client - Real-Time Updates

**Create**: `frontend/src/utils/websocketClient.js`

```javascript
class TrainingWebSocketClient {
  constructor(url) {
    this.url = url;
    this.ws = null;
    this.callbacks = [];
  }
  
  connect() {
    this.ws = new WebSocket(this.url);
    this.ws.onmessage = (event) => {
      const update = JSON.parse(event.data);
      this.callbacks.forEach(cb => cb(update));
    };
  }
  
  subscribe(callback) {
    this.callbacks.push(callback);
  }
  
  disconnect() {
    if (this.ws) this.ws.close();
  }
}
```

### 3. TrainingProgress Component - Reusable

**Create**: `frontend/src/components/TrainingProgress.jsx`

```jsx
function TrainingProgress({ trainingSessionId, onComplete }) {
  const [progress, setProgress] = useState({
    current_phase: "idle",
    progress_percent: 0,
    metrics: {},
    elapsed_seconds: 0,
  });
  const [wsClient, setWsClient] = useState(null);
  
  useEffect(() => {
    // Fetch current progress
    fetch(`/ml/training/progress`)
      .then(r => r.json())
      .then(data => setProgress(data));
    
    // Connect WebSocket for updates
    const ws = new TrainingWebSocketClient(`ws://localhost:8000/ml/training/progress/stream`);
    ws.subscribe(setProgress);
    ws.connect();
    
    return () => ws.disconnect();
  }, []);
  
  return (
    <div className="training-progress">
      <ProgressBar value={progress.progress_percent} />
      <PhaseIndicator phase={progress.current_phase} />
      <MetricsDisplay metrics={progress.metrics} />
      <ETACounter seconds={progress.estimated_remaining_seconds} />
    </div>
  );
}
```

### 4. DataGenerationProgress Component

**Create**: `frontend/src/components/DataGenerationProgress.jsx`

```jsx
function DataGenerationProgress() {
  const [progress, setProgress] = useState({
    processed: 0,
    total: 0,
    percent: 0,
    eta_seconds: 0,
    events_per_second: 0,
  });
  
  useEffect(() => {
    const interval = setInterval(() => {
      fetch(`/ml/training/generate-progress`)
        .then(r => r.json())
        .then(data => setProgress(data));
    }, 1000);
    
    return () => clearInterval(interval);
  }, []);
  
  return (
    <div className="data-generation-progress">
      <div>{progress.processed} / {progress.total} events</div>
      <ProgressBar value={progress.percent} />
      <div>ETA: {formatSeconds(progress.eta_seconds)}</div>
      <div>Rate: {progress.events_per_second.toFixed(0)} events/sec</div>
    </div>
  );
}
```

## API Endpoints Needed

### 1. Progress Query (Already implemented)
```
GET /ml/training/progress
Response:
{
  "current_phase": "training_lstm",
  "progress_percent": 45.5,
  "metrics": {
    "train_accuracy": 0.78,
    "val_accuracy": 0.75,
    "train_loss": 0.45,
    "val_loss": 0.52,
    "epoch": 15,
    "total_epochs": 50,
    "samples_processed": 7500,
    "total_samples": 10000
  },
  "elapsed_seconds": 234.5,
  "estimated_remaining_seconds": 289.2
}
```

### 2. Data Generation Progress (Already implemented)
```
GET /ml/training/generate-progress
Response:
{
  "processed": 4500,
  "total": 10000,
  "percent": 45.0,
  "elapsed_seconds": 12.3,
  "eta_seconds": 14.8,
  "events_per_second": 365.8,
  "timestamp": "2024-01-02T12:00:00Z"
}
```

### 3. WebSocket Endpoint (To be implemented)
```
WS /ml/training/progress/stream

Sends TrainingProgressUpdate objects:
{
  "phase": "training_lstm",
  "progress_percent": 45.5,
  "current_step": 15,
  "total_steps": 50,
  "message": "Epoch 15/50",
  "timestamp": "2024-01-02T12:00:00Z",
  "details": {
    "train_accuracy": 0.78,
    "val_accuracy": 0.75
  }
}
```

### 4. Cancel Training (To be implemented)
```
POST /ml/training/cancel

Cancels the current training session
```

## Phase Indicators

Training phases in order:

1. **idle** - Waiting to start
2. **loading_data** - Loading/generating data
3. **preprocessing** - Data cleanup
4. **feature_engineering** - Feature extraction
5. **data_balancing** - Class balancing
6. **data_augmentation** - Data augmentation
7. **splitting** - Train/val/test split
8. **training_lstm** - LSTM training
9. **training_rf** - Random Forest training
10. **updating_markov** - Markov chain update
11. **evaluation** - Evaluation on test set
12. **saving_model** - Model persistence
13. **completed** - Training finished
14. **failed** - Training failed

## UI Design Mockup

```
╔════════════════════════════════════════════════╗
║ TRAINING PROGRESS                              ║
╠════════════════════════════════════════════════╣
║                                                 ║
║ Phase: Training LSTM Model                     ║
║ ████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░    ║
║ 45% Complete  |  Elapsed: 234s  |  ETA: 289s  ║
║                                                 ║
║ METRICS                                         ║
║ ├─ Epoch: 15 / 50                              ║
║ ├─ Train Accuracy: 78.0%                       ║
║ ├─ Val Accuracy: 75.0%                         ║
║ ├─ Train Loss: 0.45                            ║
║ └─ Val Loss: 0.52                              ║
║                                                 ║
║ DATA PROCESSED                                  ║
║ ├─ Samples: 7,500 / 10,000 (75%)               ║
║ └─ Features: 20 (selected from 30)             ║
║                                                 ║
║ PER-MODEL ACCURACY (Recent Window)             ║
║ ├─ LSTM: 78% ████████░                         ║
║ ├─ Random Forest: 72% ███████░                 ║
║ └─ Markov Chain: 65% ██████░                   ║
║                                                 ║
║ [  CANCEL TRAINING  ]  [  SHOW LOG  ]          ║
║                                                 ║
╚════════════════════════════════════════════════╝
```

## Implementation Steps

### Step 1: Add WebSocket Endpoint
- Create `/ml/training/progress/stream` WebSocket endpoint
- Send TrainingProgressUpdate objects periodically
- Handle client disconnection gracefully

### Step 2: Create React Components
- TrainingProgress.jsx (main component)
- DataGenerationProgress.jsx (data gen component)
- PhaseIndicator.jsx (phase display)
- ProgressBar.jsx (progress bar)
- MetricsDisplay.jsx (metrics table)
- ETACounter.jsx (ETA display)
- PerModelAccuracy.jsx (per-model bars)

### Step 3: Update MLTraining.jsx
- Import new components
- Add progress tracking state
- Handle WebSocket connection
- Add cancel functionality
- Update form to show progress when training

### Step 4: Add Utility Functions
- formatSeconds() - Format seconds to human readable
- formatBytes() - Format bytes
- phaseToLabel() - Convert phase enum to display label
- getPhaseIcon() - Get icon for phase
- getPhaseColor() - Get color for phase

### Step 5: Test & Polish
- Test with real training
- Handle edge cases (slow network, disconnects)
- Keyboard shortcuts (Esc to cancel)
- Mobile responsive

## Polling vs WebSocket

**Polling Approach** (Simpler, Less Real-time):
- Poll `/ml/training/progress` every 1-2 seconds
- Simpler to implement
- Higher latency
- More bandwidth

```javascript
useEffect(() => {
  const interval = setInterval(() => {
    fetch('/ml/training/progress').then(...);
  }, 1000);
  return () => clearInterval(interval);
}, []);
```

**WebSocket Approach** (More Real-time, Complex):
- Real-time updates as they happen
- Lower latency
- More server resources
- Better for live streaming

```javascript
useEffect(() => {
  const ws = new WebSocket('ws://localhost:8000/ml/training/progress/stream');
  ws.onmessage = (e) => setProgress(JSON.parse(e.data));
  return () => ws.close();
}, []);
```

**Recommendation**: Start with polling (simpler), migrate to WebSocket if needed.

## Summary of Work

| Item | Complexity | Est. Time |
|------|-----------|-----------|
| WebSocket Endpoint | Medium | 2-3 hours |
| TrainingProgress Component | Low | 1-2 hours |
| DataGenerationProgress | Low | 1 hour |
| Supporting Components | Low | 2-3 hours |
| MLTraining.jsx Integration | Medium | 2-3 hours |
| Testing & Polish | Low | 1-2 hours |
| **Total** | **Medium** | **~10 hours** |

## Success Criteria

- ✓ Progress bar updates in real-time
- ✓ ETA calculated and displayed accurately
- ✓ Metrics show training progress (accuracy improving)
- ✓ Per-model accuracy tracked
- ✓ Cancel button stops training gracefully
- ✓ Data generation shows events/second and ETA
- ✓ Mobile responsive
- ✓ Handles network interruptions
- ✓ Clear phase indicators
- ✓ Training results displayed after completion

## Next Steps

After Phase 2 completion:
1. Move to Phase 3: Simulation Learning Integration
2. Implement automatic retraining from simulation patterns
3. Track model improvements over time
