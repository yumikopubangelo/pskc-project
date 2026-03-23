# API Changes - Progress Persistence

## New Endpoints

### 1. GET `/ml/training/state`

**Purpose:** Retrieve the last saved training state from Redis for auto-resume capability.

**HTTP Request:**
```http
GET /ml/training/state HTTP/1.1
Host: localhost:8000
```

**cURL Example:**
```bash
curl -X GET "http://localhost:8000/ml/training/state"
```

**JavaScript Fetch Example:**
```javascript
const response = await fetch('http://localhost:8000/ml/training/state');
const data = await response.json();
```

**Response: 200 OK (Training in progress)**
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
    "start_time": 1711270971.234
  },
  "source": "redis",
  "timestamp": "2024-03-23T15:43:11Z"
}
```

**Response: 200 OK (No saved state)**
```json
{
  "state": null,
  "source": "none",
  "message": "No prior training state found",
  "timestamp": "2024-03-23T15:43:11Z"
}
```

**Status Codes:**
- `200 OK` - State retrieved successfully (may be null)
- `500 Internal Server Error` - Server error

**Response Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `state` | Object\|null | Complete training state or null if none exists |
| `state.phase` | String | Training phase (idle, loading_data, training_lstm, etc.) |
| `state.progress_percent` | Float | Progress as percentage (0-100) |
| `state.current_step` | Integer | Current step number |
| `state.total_steps` | Integer | Total steps |
| `state.message` | String | Human-readable message |
| `state.timestamp` | ISO8601 | When this update was created |
| `state.details` | Object | Training metrics (accuracy, loss, epoch, etc.) |
| `state.elapsed_seconds` | Float | Time elapsed since training started |
| `state.start_time` | Unix Timestamp | Training start time |
| `source` | String | Data source ("redis" or "none") |
| `timestamp` | ISO8601 | When response was generated |

**Use Cases:**
1. On page load to check if training is in progress
2. To restore UI state without waiting for WebSocket connection
3. To display training progress before user interaction

**Implementation:**
```python
@router.get("/ml/training/state")
async def get_training_state():
    from src.api.training_progress import get_training_progress_tracker
    
    tracker = get_training_progress_tracker()
    saved_state = tracker.get_last_saved_state()
    
    if saved_state:
        return {
            "state": saved_state,
            "source": "redis",
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    else:
        return {
            "state": None,
            "source": "none",
            "message": "No prior training state found",
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
```

---

## Modified Endpoints

### WebSocket `/ml/training/progress/stream`

**Enhancement:** Now sends saved state immediately upon connection.

**Connection Behavior:**

**Before:**
```
Client connects
    ↓
Waits for next progress update
```

**After:**
```
Client connects
    ↓
Server sends saved state (if exists)
    ↓
Client can render immediately
    ↓
Continues with live updates
```

**Message Format (Saved State - NEW):**
```json
{
  "phase": "training_lstm",
  "progress_percent": 45.5,
  "current_step": 15,
  "total_steps": 50,
  "message": "Resuming from saved state...",
  "_source": "saved_state",
  "timestamp": "2024-03-23T15:43:11Z",
  "details": {
    "train_accuracy": 0.78,
    "val_accuracy": 0.75,
    "epoch": 15,
    "total_epochs": 50
  },
  "elapsed_seconds": 120.5
}
```

**Message Format (Live Updates - unchanged):**
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
    "val_accuracy": 0.751
  },
  "elapsed_seconds": 121.0
}
```

**Key Differences:**
- Saved state has `_source: "saved_state"` marker
- Sent immediately on `onopen` event
- Allows client to render progress without waiting

**Implementation Changes:**
```python
@router.websocket("/ml/training/progress/stream")
async def websocket_training_progress(websocket: WebSocket):
    # ... existing code ...
    
    try:
        # NEW: Send saved state on connect
        tracker = get_training_progress_tracker()
        saved_state = tracker.get_last_saved_state()
        if saved_state:
            await websocket.send_json({
                **saved_state,
                "_source": "saved_state",
                "message": "Resuming from saved state..."
            })
            logger.info(f"Sent saved state to client {client_id}")
        
        # ... rest of streaming logic ...
```

---

## Backward Compatibility

✅ **Fully backward compatible**

- Existing clients that don't expect saved state still work
- `_source` field is optional and can be ignored
- No changes to live update message format
- Existing `/ml/training/progress` polling endpoint unchanged

---

## Redis Storage Details

### Key Information
```
Key: pskc:ml:training_progress
Type: String (JSON)
TTL: 3600 seconds (1 hour)
Encoding: UTF-8 JSON
```

### Data Structure
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

### When Data is Written
- **On every progress update** (new behavior)
- Previously was only written at completion

### When Data is Cleared
- 1 hour after last update (TTL)
- When new training session starts (tracker reset)

### Configuration
```python
# environment
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_DB = int(os.environ.get("REDIS_DB", "0"))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "pskc_redis_secret")

# storage key
REDIS_PROGRESS_KEY = "pskc:ml:training_progress"

# ttl
REDIS_TTL = 3600  # 1 hour
```

---

## Client Integration Example

### JavaScript/React
```javascript
import React, { useState, useEffect } from 'react';

export default function TrainingPage() {
  const [savedState, setSavedState] = useState(null);
  const [showProgress, setShowProgress] = useState(false);

  useEffect(() => {
    // Check for saved state on mount
    const checkProgress = async () => {
      try {
        const response = await fetch('/ml/training/state');
        const data = await response.json();
        
        if (data.state) {
          setSavedState(data.state);
          
          // Auto-show progress if training is ongoing
          const phase = data.state.phase;
          if (phase !== 'idle' && phase !== 'completed' && phase !== 'failed') {
            setShowProgress(true);
          }
        }
      } catch (err) {
        console.error('Failed to check progress:', err);
      }
    };

    checkProgress();
  }, []);

  return (
    <div>
      {savedState && <div>Resuming: {savedState.phase}</div>}
      {showProgress && <TrainingProgress />}
    </div>
  );
}
```

### Python
```python
import requests

# Get saved training state
response = requests.get('http://localhost:8000/ml/training/state')
data = response.json()

if data['state']:
    print(f"Training in progress: {data['state']['phase']}")
    print(f"Progress: {data['state']['progress_percent']}%")
    print(f"Elapsed: {data['state']['elapsed_seconds']}s")
else:
    print("No active training")
```

---

## Error Scenarios

### Redis Unavailable
- Endpoint returns: `{"state": null, "source": "none", ...}`
- Training continues normally
- Progress visible via WebSocket only
- No persistence across page reloads

### Training Not Started
- Endpoint returns: `{"state": null, "source": "none", ...}`
- Normal behavior, no error

### Corrupt Redis Data
- Endpoint gracefully handles exceptions
- Returns: `{"state": null, ...}`
- Logged at DEBUG level

---

## Performance Metrics

| Metric | Value |
|--------|-------|
| Redis write latency | ~1ms |
| API endpoint latency | ~5-10ms |
| WebSocket message size | ~200-500 bytes |
| Redis storage per update | ~500 bytes |
| TTL | 3600 seconds |

---

## Testing

### Test Saved State Retrieval
```bash
# While training is in progress
curl http://localhost:8000/ml/training/state | jq '.state | {phase, progress_percent, elapsed_seconds}'
```

### Test WebSocket Receive
```bash
# Using websocat
websocat ws://localhost:8000/ml/training/progress/stream

# Should see saved state immediately if training is in progress
{"phase":"training_lstm","progress_percent":45.5,"_source":"saved_state",...}
```

### Test Resume Flow
```javascript
// 1. Start training
fetch('/ml/training/train', {method: 'POST'})

// 2. Wait a few seconds
await new Promise(r => setTimeout(r, 3000))

// 3. Reload page
window.location.reload()

// 4. Check console - should see saved state immediately
// Expected: "Received saved state, initializing display..."
```
