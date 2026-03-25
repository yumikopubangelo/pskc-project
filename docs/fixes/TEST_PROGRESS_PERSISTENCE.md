# Testing Progress Persistence Features

This document provides step-by-step instructions to test all progress persistence features.

## Prerequisites

- Backend running on `http://localhost:8000`
- Frontend running on `http://localhost:3000`
- Redis running and accessible
- Browser developer console open (F12)

## Test 1: Basic REST Endpoint

### Objective
Verify `/ml/training/state` endpoint works correctly when no training exists.

### Steps
1. Open browser console
2. Execute:
```javascript
fetch('http://localhost:8000/ml/training/state')
  .then(r => r.json())
  .then(d => console.log(JSON.stringify(d, null, 2)))
```

### Expected Result
```json
{
  "state": null,
  "source": "none",
  "message": "No prior training state found",
  "timestamp": "2024-03-23T15:43:11Z"
}
```

### Pass/Fail: ___________

---

## Test 2: Redis Persistence During Training

### Objective
Verify progress is saved to Redis on every update.

### Steps
1. Navigate to ML Training page
2. Start training by clicking "Train Model"
3. Wait 2-3 seconds for training to progress
4. Check Redis:
```bash
redis-cli -a pskc_redis_secret
> GET pskc:ml:training_progress
```

### Expected Result
- Redis returns a JSON object with training state
- Contains fields like `phase`, `progress_percent`, `elapsed_seconds`
- Should NOT be null/empty

### Sample Output
```json
{"phase":"training_lstm","progress_percent":25.5,"elapsed_seconds":30.5,...}
```

### Pass/Fail: ___________

---

## Test 3: REST Endpoint Returns Saved State

### Objective
Verify `/ml/training/state` returns actual training progress during training.

### Steps
1. Start training on ML Training page
2. Immediately in browser console, execute:
```javascript
fetch('http://localhost:8000/ml/training/state')
  .then(r => r.json())
  .then(d => console.log('Phase:', d.state?.phase, 'Progress:', d.state?.progress_percent))
```
3. Run multiple times over next 10 seconds

### Expected Result
- `state` is NOT null
- `phase` value changes (loading_data → preprocessing → training_lstm, etc.)
- `progress_percent` increases over time
- `source` is "redis"

### Pass/Fail: ___________

---

## Test 4: WebSocket Send-on-Connect

### Objective
Verify WebSocket sends saved state immediately when client connects.

### Steps
1. Start training
2. Wait 5 seconds
3. In browser console, connect to WebSocket:
```javascript
const ws = new WebSocket('ws://localhost:8000/ml/training/progress/stream');
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  console.log('Message source:', msg._source || 'live');
  console.log('Phase:', msg.phase);
  console.log('Progress:', msg.progress_percent);
};
```
4. Observe console

### Expected Result
- **First message** should have `_source: "saved_state"`
- Progress bar should immediately jump to current progress (not 0%)
- Subsequent messages should NOT have `_source` field
- Progress continues to update

### Pass/Fail: ___________

---

## Test 5: Frontend Auto-Resume on Page Load

### Objective
Verify training progress shows automatically when page loads during training.

### Steps
1. Start training on ML Training page
2. Wait 3-4 seconds for progress to accumulate
3. Refresh page (F5 or Ctrl+R)
4. Observe UI

### Expected Result
- **Immediately after reload** (before WebSocket connects):
  - Training Progress component appears
  - Progress bar shows saved progress (not 0%)
  - Phase shows correct training phase
  - Metrics display if available
- Progress bar doesn't start from 0%
- Training continues to update
- No console errors about missing state

### Console Logs to Check
```
Found saved progress state: {...}  <- Should appear
Received saved state, initializing display...  <- From TrainingProgress component
```

### Pass/Fail: ___________

---

## Test 6: Metrics Display from Saved State

### Objective
Verify metrics are correctly extracted and displayed from saved state.

### Steps
1. Start training
2. Wait for metrics to appear (accuracy, loss, epoch)
3. Refresh page while training is in progress
4. Observe metrics display

### Expected Result
- Accuracy values display correctly (e.g., "78.5%")
- Loss values display correctly (e.g., "0.2314")
- Epoch shows current progress (e.g., "15/50")
- Sample counts show correctly
- No "NaN" or "undefined" values in display

### Pass/Fail: ___________

---

## Test 7: Training Completion State Persistence

### Objective
Verify final training state persists after completion.

### Steps
1. Start training and wait for completion
2. Observe training finishes (phase = "completed")
3. Refresh page immediately after completion
4. Observe page loads

### Expected Result
- Page shows completed training state
- Progress bar shows 100%
- Final metrics are visible
- No errors in console
- "✓ Training Completed" message appears

### Pass/Fail: ___________

---

## Test 8: Training Failure State Persistence

### Objective
Verify failed training state persists correctly.

### Steps
1. Start training
2. Simulate failure by stopping backend or corrupting data
3. Wait for training to fail
4. Refresh page

### Expected Result
- Page shows failed training state
- "Training Failed" message appears
- Phase shows "failed"
- Error details visible if available

### Pass/Fail: ___________

---

## Test 9: Multiple Page Reloads

### Objective
Verify state remains consistent across multiple rapid reloads.

### Steps
1. Start training
2. Quickly reload page 3-4 times
3. Monitor console and UI

### Expected Result
- No errors in console
- Progress state consistent across reloads
- No duplicate messages
- WebSocket properly reconnects each time
- Metrics remain correct

### Pass/Fail: ___________

---

## Test 10: Redis Unavailable Fallback

### Objective
Verify system gracefully handles Redis being unavailable.

### Steps
1. Stop Redis:
```bash
docker stop redis  # if using Docker
# OR
redis-cli SHUTDOWN  # if running locally
```
2. Start training
3. Refresh page
4. Observe behavior

### Expected Result
- Training still progresses
- WebSocket still works
- Progress visible via WebSocket streaming
- `/ml/training/state` returns state: null
- No critical errors (debug logs OK)
- On page reload, progress shows 0% (can't recover from Redis)
- Training continues in real-time

### Pass/Fail: ___________

---

## Test 11: Metrics Format Handling

### Objective
Verify metrics are correctly formatted whether they're decimals or percentages.

### Steps
1. Monitor training and check console:
```javascript
// Add this after receiving updates
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  console.log('Accuracy:', msg.details?.train_accuracy);
  console.log('Type:', typeof msg.details?.train_accuracy);
  console.log('Range:', msg.details?.train_accuracy > 1 ? '0-100' : '0-1');
};
```

### Expected Result
- Accuracy values display as percentages (e.g., "78.5%")
- Loss values display with decimals (e.g., "0.2314")
- No "NaN" or "undefined" in UI
- Handles both decimal (0-1) and percentage (0-100) values

### Pass/Fail: ___________

---

## Test 12: WebSocket Reconnection with Saved State

### Objective
Verify WebSocket reconnection restores state properly.

### Steps
1. Start training
2. Close WebSocket connection in console:
```javascript
ws.close()
```
3. Wait 2 seconds
4. Reconnect:
```javascript
const ws2 = new WebSocket('ws://localhost:8000/ml/training/progress/stream');
ws2.onmessage = (e) => console.log(JSON.parse(e.data));
```

### Expected Result
- New WebSocket connection receives saved state
- `_source: "saved_state"` appears in first message
- Progress is correct (not reset)
- Live updates continue after saved state

### Pass/Fail: ___________

---

## Performance Tests

### Test P1: Response Time of REST Endpoint

```bash
time curl http://localhost:8000/ml/training/state
```

**Expected:** < 20ms

### Test P2: WebSocket Send-on-Connect Latency

Monitor in browser:
```javascript
const start = Date.now();
const ws = new WebSocket('ws://localhost:8000/ml/training/progress/stream');
ws.onmessage = () => {
  console.log('First message received in:', Date.now() - start, 'ms');
};
```

**Expected:** < 100ms

### Test P3: Redis Write Latency

Monitor backend logs during training for persist latency.

**Expected:** < 5ms per update

---

## Security Tests

### Test S1: Unauthorized Access

```bash
# Should still work (no auth required for training progress)
curl http://localhost:8000/ml/training/state
```

**Expected:** Successful response (state may be null)

### Test S2: Redis Password

Verify Redis requires password:
```bash
# Without password - should fail
redis-cli
> GET pskc:ml:training_progress
# Error: (error) NOAUTH Authentication required.
```

**Expected:** Error message about authentication

---

## Cleanup After Testing

1. Clear Redis if needed:
```bash
redis-cli -a pskc_redis_secret
> DEL pskc:ml:training_progress
```

2. Check logs for any errors:
```bash
# Backend logs
tail -f logs/app.log | grep -i "error\|exception"

# Frontend console (DevTools)
```

---

## Summary Checklist

| Test | Pass/Fail | Notes |
|------|-----------|-------|
| Test 1: REST Endpoint (no state) | _____ | |
| Test 2: Redis Persistence | _____ | |
| Test 3: REST Endpoint (with state) | _____ | |
| Test 4: WebSocket Send-on-Connect | _____ | |
| Test 5: Frontend Auto-Resume | _____ | |
| Test 6: Metrics Display | _____ | |
| Test 7: Completion State | _____ | |
| Test 8: Failure State | _____ | |
| Test 9: Multiple Reloads | _____ | |
| Test 10: Redis Unavailable | _____ | |
| Test 11: Metrics Format | _____ | |
| Test 12: WebSocket Reconnection | _____ | |
| Test P1: REST Latency | _____ | |
| Test P2: WebSocket Latency | _____ | |
| Test P3: Redis Write Latency | _____ | |
| Test S1: Unauthorized Access | _____ | |
| Test S2: Redis Password | _____ | |

**Overall Result:** _______________

---

## Troubleshooting

### "No prior training state found" always returned
- **Cause:** Redis not running or not connected
- **Solution:** Start Redis and verify connection

### WebSocket not sending saved state
- **Cause:** Tracking starts fresh, no prior state
- **Solution:** Start training first, then connect WebSocket

### Metrics showing "NaN" or "undefined"
- **Cause:** Metrics not properly extracted
- **Solution:** Check formatPercent() function and metric field names

### Page reload shows 0% progress
- **Cause:** Redis unavailable or entry expired
- **Solution:** Check Redis status and TTL

### Console errors about WebSocket
- **Cause:** Backend not running or WebSocket endpoint not available
- **Solution:** Check backend health and WebSocket endpoint

---

## Notes

- All tests assume default configuration
- Adjust host/port as needed for your setup
- Some tests may take 30-60 seconds due to training duration
- Check browser and backend logs for detailed errors
