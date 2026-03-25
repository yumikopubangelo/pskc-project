# Progress Persistence Usage Guide

## Overview

This guide shows how to use the new progress persistence features for auto-resume capability.

## Backend Endpoints

### 1. GET `/ml/training/state`

Retrieve the last saved training state from Redis.

**Request:**
```bash
curl http://localhost:8000/ml/training/state
```

**Response (Training in progress):**
```json
{
  "state": {
    "phase": "training_lstm",
    "progress_percent": 45.5,
    "current_step": 15,
    "total_steps": 50,
    "message": "Epoch 15/50 - Accuracy improving",
    "timestamp": "2024-03-23T15:43:11Z",
    "details": {
      "train_accuracy": 0.78,
      "val_accuracy": 0.75,
      "train_loss": 0.23,
      "val_loss": 0.25,
      "epoch": 15,
      "total_epochs": 50,
      "samples_processed": 7500,
      "total_samples": 10000
    },
    "elapsed_seconds": 120.5,
    "start_time": "2024-03-23T15:41:11Z"
  },
  "source": "redis",
  "timestamp": "2024-03-23T15:43:11Z"
}
```

**Response (No saved state):**
```json
{
  "state": null,
  "source": "none",
  "message": "No prior training state found",
  "timestamp": "2024-03-23T15:43:11Z"
}
```

**Use Case:**
- Fetch on page load to check if training is in progress
- Display saved progress before WebSocket connects
- Enable instant UI update without waiting for WebSocket

### 2. WebSocket `/ml/training/progress/stream`

WebSocket endpoint for real-time progress updates with auto-resume.

**Connection:**
```javascript
const ws = new WebSocket('ws://localhost:8000/ml/training/progress/stream');

ws.onopen = () => {
  console.log('Connected to training progress stream');
  // If training is in progress, server will immediately send saved state
};

ws.onmessage = (event) => {
  const update = JSON.parse(event.data);
  
  if (update._source === 'saved_state') {
    console.log('Resuming from saved state:', update);
  } else {
    console.log('Live update:', update);
  }
};

ws.onclose = () => {
  console.log('Connection closed - progress is saved in Redis for resume');
};
```

**Message Format (Saved State on Connect):**
```json
{
  "phase": "training_lstm",
  "progress_percent": 45.5,
  "message": "Resuming from saved state...",
  "_source": "saved_state",
  "details": {
    "train_accuracy": 0.78,
    "val_accuracy": 0.75,
    ...
  },
  "elapsed_seconds": 120.5
}
```

**Message Format (Live Updates):**
```json
{
  "phase": "training_lstm",
  "progress_percent": 46.2,
  "current_step": 16,
  "total_steps": 50,
  "message": "Epoch 16/50 - Training...",
  "timestamp": "2024-03-23T15:43:12Z",
  "details": {
    "train_accuracy": 0.785,
    "val_accuracy": 0.751,
    ...
  },
  "elapsed_seconds": 121.0
}
```

## Frontend Usage

### Example 1: Auto-Resume on Page Load

```javascript
import React, { useState, useEffect } from 'react';
import apiClient from '../utils/apiClient';
import TrainingProgress from '../components/TrainingProgress';

export default function TrainingPage() {
  const [showProgress, setShowProgress] = useState(false);
  const [savedState, setSavedState] = useState(null);

  useEffect(() => {
    // Check for saved progress on mount
    checkForSavedProgress();
  }, []);

  const checkForSavedProgress = async () => {
    try {
      const response = await apiClient.get('/ml/training/state');
      if (response.state) {
        setSavedState(response.state);
        
        // Auto-show progress if training is ongoing
        const phase = response.state.phase;
        if (phase !== 'idle' && phase !== 'completed' && phase !== 'failed') {
          setShowProgress(true);
        }
      }
    } catch (err) {
      console.debug('No saved state:', err);
    }
  };

  return (
    <div>
      <h1>ML Training</h1>
      
      {savedState && (
        <div className="saved-state-info">
          <p>Resuming training from phase: {savedState.phase}</p>
          <p>Progress: {savedState.progress_percent}%</p>
          <p>Elapsed: {savedState.elapsed_seconds}s</p>
        </div>
      )}
      
      {showProgress && (
        <TrainingProgress onComplete={() => setShowProgress(false)} />
      )}
    </div>
  );
}
```

### Example 2: Manual State Recovery

```javascript
// Get current saved state without WebSocket
const getSavedTrainingState = async () => {
  try {
    const response = await apiClient.get('/ml/training/state');
    if (response.state) {
      console.log('Training in progress:', {
        phase: response.state.phase,
        progress: response.state.progress_percent + '%',
        accuracy: response.state.details?.val_accuracy,
        timeElapsed: response.state.elapsed_seconds + 's'
      });
      return response.state;
    } else {
      console.log('No active training');
      return null;
    }
  } catch (err) {
    console.error('Failed to get state:', err);
  }
};

// Call it
const state = await getSavedTrainingState();
```

### Example 3: Handling Both Saved State and Live Updates

```javascript
const TrainingProgressComponent = () => {
  const [progress, setProgress] = useState({
    phase: 'idle',
    progress_percent: 0,
    metrics: {},
    elapsed_seconds: 0
  });

  useEffect(() => {
    const ws = new WebSocket('ws://localhost:8000/ml/training/progress/stream');
    
    ws.onmessage = (event) => {
      const update = JSON.parse(event.data);
      
      setProgress(prev => {
        // Handle both saved state and live updates
        const newState = {
          ...prev,
          phase: update.phase || prev.phase,
          progress_percent: update.progress_percent ?? prev.progress_percent,
          elapsed_seconds: update.elapsed_seconds ?? prev.elapsed_seconds,
        };
        
        // Merge metrics from details or top-level fields
        if (update.details) {
          newState.metrics = { ...prev.metrics, ...update.details };
        }
        
        return newState;
      });
      
      // Log if it's a saved state
      if (update._source === 'saved_state') {
        console.log('Resumed from saved state');
      }
    };
    
    return () => ws.close();
  }, []);

  return (
    <div>
      <h2>{progress.phase}</h2>
      <div className="progress-bar" style={{ width: progress.progress_percent + '%' }} />
      <p>Elapsed: {progress.elapsed_seconds}s</p>
      <p>Accuracy: {(progress.metrics.val_accuracy * 100).toFixed(1)}%</p>
    </div>
  );
};
```

## Data Persistence in Redis

### Key Structure
```
Key: pskc:ml:training_progress
TTL: 3600 seconds (1 hour)
Value: JSON object with complete training state
```

### Example Redis Entry
```json
{
  "phase": "training_lstm",
  "progress_percent": 45.5,
  "current_step": 15,
  "total_steps": 50,
  "message": "Epoch 15/50",
  "timestamp": "2024-03-23T15:43:11Z",
  "details": {
    "train_accuracy": 0.78,
    "val_accuracy": 0.75,
    "train_loss": 0.23,
    "val_loss": 0.25,
    "epoch": 15,
    "total_epochs": 50,
    "samples_processed": 7500,
    "total_samples": 10000
  },
  "elapsed_seconds": 120.5,
  "start_time": 1711270971.234
}
```

### Check Redis Entry
```bash
# Using redis-cli
redis-cli -a pskc_redis_secret
> GET pskc:ml:training_progress
```

## Flow Diagrams

### Scenario 1: Normal Training Progress
```
User starts training
    ↓
POST /ml/training/train
    ↓
Backend updates progress
    ↓
update_progress() → _persist_to_redis() + WebSocket send
    ↓
Client receives updates via WebSocket
```

### Scenario 2: Page Reload During Training
```
Page starts loading
    ↓
useEffect: GET /ml/training/state
    ↓
Get saved state from Redis
    ↓
setShowProgress(true)
    ↓
Connect WebSocket → Receive saved state → Render progress
    ↓
Live updates continue to stream
```

### Scenario 3: Training Completed
```
Training finishes
    ↓
finish_training() → _persist_to_redis() + update_progress()
    ↓
WebSocket sends COMPLETED phase
    ↓
Client receives completion signal
    ↓
Progress state remains in Redis for 1 hour
    ↓
Page reload shows final state from Redis
    ↓
After 1 hour, Redis entry expires
```

## Error Handling

### Redis Unavailable
- Training continues normally
- Progress not persisted but shown in real-time via WebSocket
- Page reload won't show saved state, but training can be checked via `/ml/training/progress`

### WebSocket Disconnection
- Progress remains safe in Redis
- Page reload will restore state from `/ml/training/state`
- Reconnect will show saved state + continue with live updates

### No Saved State
- `/ml/training/state` returns `state: null`
- Progress UI doesn't show until training starts
- Normal training flow continues

## Best Practices

1. **Always check `/ml/training/state` on mount**
   - Enables instant UI update before WebSocket connects
   - Reduces visual delay for resumed training

2. **Respect the `_source` field**
   - `_source: "saved_state"` → Initial resumption
   - No `_source` field → Live update
   - Helps distinguish between recovery and real-time updates

3. **Handle both saved metrics and live metrics**
   - Saved state has full metrics in `details`
   - Live updates may have metrics in `details` or top-level
   - Always check both when extracting metrics

4. **Monitor elapsed time**
   - `elapsed_seconds` shows time since training start
   - Use for ETA calculations
   - Persisted in Redis so it's accurate across reloads

5. **Graceful degradation**
   - If Redis is down: training still works, WebSocket still updates
   - If WebSocket fails: can still poll `/ml/training/progress`
   - If both fail: training continues in background

## Performance Considerations

- **Redis writes:** One per progress update (lightweight JSON)
- **WebSocket messages:** Reduced via change detection (only send if state changed)
- **REST calls:** Only on page load + polling fallback
- **Memory:** Kept under control with max 1000 update history in memory

## Security

- Redis requires authentication (`pskc_redis_secret`)
- Progress state is not sensitive (non-PII)
- WebSocket connections properly validated
- TTL prevents stale data accumulation
