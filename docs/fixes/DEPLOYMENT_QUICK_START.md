# 🚀 Quick Start - Deploy Both Fixes

Two issues have been identified and fixed:
1. ✅ API Request Timeout on `/ml/training/generate` and `/ml/training/train`
2. ✅ PyTorch not available, LSTM model disabled

Both fixes are ready for deployment.

---

## Deploy in 3 Steps

### Step 1: Rebuild Docker Image
```bash
cd d:\pskc-project
docker-compose build --no-cache
```

This will:
- Install PyTorch with `--prefix=/install` (builder stage)
- Copy all dependencies to runtime
- Install PyTorch again in runtime (as backup)
- Install all other dependencies

**Expected**: Build completes successfully with no torch errors

### Step 2: Restart Services
```bash
docker-compose down
docker-compose up -d
```

This will:
- Stop all containers
- Start fresh with new image
- All services come online

**Expected**: Services start without errors

### Step 3: Verify Both Fixes
```bash
# Verify API is responding
curl http://localhost:8000/api/health

# Verify PyTorch is available
docker logs pskc-api | grep -i pytorch
# Should NOT show: "PyTorch not available, LSTM model disabled"

# Verify endpoints return HTTP 202
curl -X POST "http://localhost:8000/ml/training/generate?num_events=1000&num_keys=50&num_services=5&duration_hours=1"
# Should return HTTP 202 in < 500ms (not timeout)

curl -X POST "http://localhost:8000/ml/training/train?force=true&reason=manual"
# Should return HTTP 202 in < 500ms (not timeout)
```

---

## What Was Fixed

### Fix #1: API Timeout
**File**: `src/api/route_training.py` (lines 25-220)

**Problem**: API endpoints blocked waiting for long operations
**Solution**: Return HTTP 202 immediately, run operations in background
**Result**: No more timeout errors

### Fix #2: PyTorch Installation
**File**: `Dockerfile` (lines 27-35, 50-62)

**Problem**: PyTorch not transferred from builder to runtime stage
**Solution**: Use `--prefix=/install` in builder + backup install in runtime
**Result**: PyTorch available, LSTM model enabled

---

## Frontend Changes Required

The `/ml/training/generate` endpoint now returns **HTTP 202** instead of waiting.

**Update frontend** (e.g., MLTraining.jsx) to handle 202 response:

```javascript
const response = await fetch('/ml/training/generate', {
    method: 'POST',
    body: JSON.stringify({num_events: 5000, num_keys: 50, num_services: 5, duration_hours: 1})
})

if (response.status === 202) {
    const data = await response.json()
    console.log('Generation started, poll:', data.poll_endpoint)
    
    // Poll for progress
    const pollInterval = setInterval(async () => {
        const progress = await fetch(data.poll_endpoint)
        const status = await progress.json()
        
        if (status.percent_complete === 100) {
            clearInterval(pollInterval)
            console.log('Generation complete!')
        } else {
            console.log(`Progress: ${status.percent_complete}%`)
        }
    }, 1000)
}
```

See `IMPLEMENTATION_GUIDE.md` for complete frontend integration.

---

## Documentation

- **For API timeout**: See `IMPLEMENTATION_GUIDE.md` and `API_TIMEOUT_FIX_SUMMARY.md`
- **For PyTorch issue**: See `PYTORCH_ROOT_CAUSE_FIX.md` and `PYTORCH_FIX.md`
- **For navigation**: See `DOCUMENTATION_INDEX.md`

---

## Troubleshooting

### If build fails:
```bash
# Clean everything and rebuild
docker system prune -a
docker-compose build --no-cache
```

### If PyTorch still not available:
```bash
# Verify installation
docker exec pskc-api python -c "import torch; print(f'PyTorch {torch.__version__}')"

# Check logs
docker logs pskc-api | grep -i "error\|torch"
```

### If API still times out:
```bash
# Verify endpoint returns 202
curl -v -X POST "http://localhost:8000/ml/training/generate?num_events=100&num_keys=10&num_services=1&duration_hours=1"
# Should show "HTTP/1.1 202 Accepted" in ~100ms

# Check that progress polling works
curl "http://localhost:8000/ml/training/generate-progress"
```

---

## Expected Results After Deployment

✅ API no longer times out on training endpoints
✅ PyTorch is available (no warning message)
✅ LSTM model is enabled in ensemble
✅ Full ensemble (LSTM + RF + Markov) used for predictions
✅ Better prediction accuracy with all three models

---

## Time to Deploy

- Rebuild Docker: ~5-15 minutes (first time) or ~2-3 minutes (cached)
- Restart services: ~30 seconds
- Total: ~6-20 minutes

---

**Status**: ✅ Ready to deploy
**Next Step**: Run `docker-compose build --no-cache && docker-compose up -d`
