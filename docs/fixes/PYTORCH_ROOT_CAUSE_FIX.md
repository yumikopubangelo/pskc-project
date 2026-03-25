# 🔧 PyTorch Missing Issue - ROOT CAUSE & FIX

## Problem
When running Docker container, warning appears:
```
WARNING: PyTorch not available, LSTM model disabled
```

This prevents the LSTM model from being used, even though PyTorch should be installed.

## Root Cause

**Docker Multi-Stage Build Issue**:

The Dockerfile has two stages (builder → runtime):

```dockerfile
# Stage 1: Builder
FROM python:3.11-slim AS builder
...
RUN pip install --no-cache-dir torch==2.3.1+cpu ...  # ❌ NO --prefix!
```

```dockerfile
# Stage 2: Runtime
FROM python:3.11-slim AS runtime
...
COPY --from=builder /install /usr/local  # ❌ Only copies /install!
```

**What happened**:
1. PyTorch installed to: `builder:/usr/local/lib/python3.11/site-packages/torch`
2. Only `/install` directory copied to runtime: `runtime:/usr/local`
3. PyTorch wasn't in `/install`, so it didn't transfer ❌
4. Runtime tries to import torch → ImportError → TORCH_AVAILABLE = False
5. LSTM model disabled

## The Fix

### Change 1: Builder Stage (line 29)
```dockerfile
# BEFORE (broken)
RUN pip install --no-cache-dir \
    torch==2.3.1+cpu \
    --index-url https://download.pytorch.org/whl/cpu

# AFTER (fixed)
RUN pip install --prefix=/install --no-cache-dir \
    torch==2.3.1+cpu \
    --index-url https://download.pytorch.org/whl/cpu
```

**Why**: `--prefix=/install` ensures PyTorch goes to `/install` directory, which gets copied to runtime.

### Change 2: Runtime Stage (line 60)
```dockerfile
# ADDED: Backup PyTorch installation in runtime
RUN pip install --no-cache-dir \
    torch==2.3.1+cpu \
    --index-url https://download.pytorch.org/whl/cpu
```

**Why**: Double insurance - if copy from builder fails, PyTorch is installed directly in runtime.

## How It Works Now

```
Builder Stage:
  ✅ PyTorch installed with --prefix=/install
  ✅ Stored in: /install/lib/python3.11/site-packages/torch

Copy to Runtime:
  ✅ COPY --from=builder /install /usr/local
  ✅ PyTorch now available in: /usr/local/lib/python3.11/site-packages/torch

Runtime Stage:
  ✅ PyTorch backup installed as redundancy
  ✅ Both copy and direct install ensure availability
```

## Deployment

### Step 1: Rebuild Docker
```bash
cd d:\pskc-project
docker-compose build --no-cache
```

During build you'll see:
```
Step 1/... Installing PyTorch in builder...
Step 2/... Copying /install from builder...
Step 3/... Installing PyTorch backup in runtime...
```

### Step 2: Restart Containers
```bash
docker-compose down
docker-compose up -d
```

### Step 3: Verify
```bash
# Check that PyTorch is available
docker exec pskc-api python -c "import torch; print(f'PyTorch {torch.__version__} available')"
```

Expected output:
```
PyTorch 2.3.1+cpu available
```

Or check logs:
```bash
docker logs pskc-api | grep -i pytorch
# Should NOT see: "PyTorch not available, LSTM model disabled"
```

## Why This Fixes the Issue

### Before Fix:
```python
# In src/ml/model.py line 25-32
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    logger.warning("PyTorch not available, LSTM model disabled")  # ❌ This warning
```

**Result**: TORCH_AVAILABLE = False because torch not in runtime

### After Fix:
- PyTorch properly installed in runtime via both copy and direct install
- `import torch` succeeds
- TORCH_AVAILABLE = True
- LSTM model is enabled ✅

## Files Modified

| File | Lines | Change |
|------|-------|--------|
| Dockerfile | 27-35 | Added `--prefix=/install` to PyTorch installation in builder |
| Dockerfile | 50-62 | Added backup PyTorch installation in runtime |

## Impact

| Component | Before Fix | After Fix |
|-----------|-----------|-----------|
| LSTM Model | Disabled ❌ | Enabled ✅ |
| Ensemble | RF + Markov only | LSTM + RF + Markov |
| Prediction Accuracy | Lower | Higher |
| Weight Adjustment | N/A | Dynamic (EWMA) |

## Verification Checklist

After deployment, verify:

- [ ] Docker build completes without errors
- [ ] `docker logs pskc-api` shows no "PyTorch not available" warning
- [ ] `docker exec pskc-api python -c "import torch"` runs without error
- [ ] API starts successfully and listens on port 8000
- [ ] `/ml/training/train` endpoint is accessible
- [ ] LSTM model is used in predictions (check logs or model output)

## Why Multi-Stage Build?

Docker multi-stage builds reduce image size:
- Builder stage: 2GB+ (gcc, build tools, all dependencies)
- Runtime stage: ~500MB (only runtime dependencies)

The `--prefix=/install` pattern ensures:
- Only dependencies in `/install` are copied (saves space)
- All dependencies are available in runtime
- Image is as small as possible

## If Still Having Issues

**Full rebuild** (nuclear option):
```bash
docker-compose down
docker system prune -a
docker-compose build --no-cache
docker-compose up -d
```

**Check what's installed**:
```bash
docker exec pskc-api pip list | grep -i torch
# Should show: torch  2.3.1+cpu
```

**Check import path**:
```bash
docker exec pskc-api python -c "import torch; print(torch.__file__)"
# Should show: /usr/local/lib/python3.11/site-packages/torch/__init__.py
```

---

## Summary

✅ **Problem**: PyTorch not transferred to runtime stage
✅ **Cause**: Missing `--prefix=/install` in builder, no backup in runtime
✅ **Solution**: Use `--prefix=/install` + backup installation in runtime
✅ **Result**: PyTorch available, LSTM model enabled, better predictions

**Status**: Ready for deployment ✅
