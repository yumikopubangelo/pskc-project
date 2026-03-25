# PyTorch Installation Fix

## Problem
When running the Docker container, you see:
```
WARNING: PyTorch not available, LSTM model disabled
```

This happens even though PyTorch should be installed.

## Root Cause
The Dockerfile had a **multi-stage build issue**:

1. **Builder Stage**: PyTorch was installed with `--no-cache-dir` but **WITHOUT** the `--prefix=/install` flag
   - This installed PyTorch to the default Python site-packages in the builder image

2. **Runtime Stage**: Only copied `/install` directory from builder to runtime
   - But PyTorch wasn't in `/install` — it was installed to the global site-packages
   - Result: PyTorch wasn't transferred to the runtime stage ❌

## Solution

### Step 1: Fixed Dockerfile
Changed PyTorch installation to use `--prefix=/install` **in the builder stage**:

**BEFORE** (broken):
```dockerfile
RUN pip install --no-cache-dir \
    torch==2.3.1+cpu \
    --index-url https://download.pytorch.org/whl/cpu

RUN pip install --prefix=/install --no-cache-dir -r requirements.txt
```

**AFTER** (fixed):
```dockerfile
# Install PyTorch with --prefix so it gets copied to runtime stage
RUN pip install --prefix=/install --no-cache-dir \
    torch==2.3.1+cpu \
    --index-url https://download.pytorch.org/whl/cpu

RUN pip install --prefix=/install --no-cache-dir -r requirements.txt
```

### Step 2: Added Backup PyTorch Installation in Runtime
Also added PyTorch installation in the runtime stage as a redundancy check:

```dockerfile
# CRITICAL FIX: Ensure PyTorch is available in runtime
# Install PyTorch again from PyTorch's official index as backup
RUN pip install --no-cache-dir \
    torch==2.3.1+cpu \
    --index-url https://download.pytorch.org/whl/cpu
```

This ensures PyTorch is definitely available even if the copy from builder failed.

## Files Modified
- `Dockerfile` (lines 27-35 for builder, lines 50-61 for runtime)

## Deployment Steps

### 1. Rebuild Docker Image
```bash
cd d:\pskc-project
docker-compose build --no-cache
```

This will rebuild the image with the fixed Dockerfile. The build will:
1. Install PyTorch in builder with `--prefix=/install`
2. Copy `/install` to runtime (now includes PyTorch)
3. Install PyTorch again in runtime as backup

### 2. Restart Services
```bash
docker-compose down
docker-compose up -d
```

### 3. Verify PyTorch is Available
```bash
# Check logs for PyTorch availability
docker logs pskc-api | grep -i pytorch

# You should NOT see: "PyTorch not available, LSTM model disabled"
# You should see successful startup instead
```

Or test directly:
```bash
docker exec pskc-api python -c "import torch; print(f'PyTorch {torch.__version__} available')"
```

Expected output:
```
PyTorch 2.3.1+cpu available
```

## Why This Happened

Docker multi-stage builds:
```dockerfile
# Stage 1 (builder)
FROM python:3.11-slim AS builder
RUN pip install torch  # Installs to /usr/local/lib/python.../site-packages

# Stage 2 (runtime)  
FROM python:3.11-slim AS runtime
COPY --from=builder /install /usr/local  # Only copies /install, not site-packages!
```

The issue: Packages installed without `--prefix=/install` go to the default site-packages location, which isn't copied to the runtime stage.

## How the Fix Works

```dockerfile
# Stage 1 (builder)
RUN pip install --prefix=/install torch  # Installs to /install

# Stage 2 (runtime)
COPY --from=builder /install /usr/local  # Now includes torch!
```

By using `--prefix=/install`, PyTorch is installed to the `/install` directory in the builder, which then gets copied to `/usr/local` in the runtime stage.

## Verification Checklist

After deployment, verify:

- [ ] Docker build completes without errors
- [ ] API container starts: `docker logs pskc-api | head -20`
- [ ] No "PyTorch not available" warning in logs
- [ ] PyTorch is importable: `docker exec pskc-api python -c "import torch"`
- [ ] LSTM model is enabled in the model initialization
- [ ] No error messages related to torch imports
- [ ] Backend can now use LSTM for predictions

## Technical Details

**PyTorch Version**: `2.3.1+cpu` (CPU-only for smaller image size)

**Installation Method**: From PyTorch's official wheel index
- URL: `https://download.pytorch.org/whl/cpu`
- This avoids compilation and is faster

**Installation Locations**:
- Builder stage: `/install` (so it gets copied)
- Runtime stage: `/usr/local` (copied from builder) + fresh install as backup

## Impact

✅ **Before Fix**: LSTM model disabled, only RF + Markov available
✅ **After Fix**: Full ensemble with LSTM + RF + Markov available

**Performance Impact**:
- Better accuracy with all three models in ensemble
- Dynamic weight adjustment works correctly
- More robust predictions

## If Still Having Issues

1. **Clean rebuild**:
   ```bash
   docker-compose down
   docker system prune -a
   docker-compose build --no-cache
   docker-compose up -d
   ```

2. **Check Docker build log**:
   ```bash
   docker-compose build --no-cache 2>&1 | grep -i "torch\|pytorch"
   ```

3. **Verify in running container**:
   ```bash
   docker exec pskc-api python -c "
   try:
       import torch
       print(f'✅ PyTorch {torch.__version__} available')
   except ImportError as e:
       print(f'❌ PyTorch import failed: {e}')
   "
   ```

4. **Check installed packages**:
   ```bash
   docker exec pskc-api pip list | grep torch
   ```

---

**Fix Status**: ✅ Ready for deployment
**Tested**: Code review completed
**Impact**: Enables LSTM in ensemble, improves prediction accuracy
