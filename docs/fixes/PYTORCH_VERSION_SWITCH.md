# 🔧 How to Switch PyTorch Versions

## If You Want to Use Heavier PyTorch (with CUDA)

Follow these steps if you have NVIDIA GPU and want GPU acceleration.

---

## Step 1: Check Your GPU (if any)

```bash
# Check if you have NVIDIA GPU
nvidia-smi

# If GPU found, note the CUDA version shown
# Common versions: 11.8, 12.1
```

If command fails or shows no GPU → **Don't switch, use CPU-only** ✅

---

## Step 2: Choose PyTorch Version

### For CUDA 12.1 (Newer, Recommended)
```
torch==2.3.1+cu121
```

### For CUDA 11.8 (Older systems)
```
torch==2.3.1+cu118
```

### For Newest (Latest CUDA)
```
torch==2.3.1  # Will use latest available CUDA
```

---

## Step 3: Edit Dockerfile

### Option A: Using CUDA 12.1 (Recommended)

**Find lines 29-31** (builder stage):
```dockerfile
RUN pip install --prefix=/install --no-cache-dir \
    torch==2.3.1+cpu \
    --index-url https://download.pytorch.org/whl/cpu
```

**Replace with**:
```dockerfile
RUN pip install --prefix=/install --no-cache-dir \
    torch==2.3.1+cu121 \
    --index-url https://download.pytorch.org/whl/cu121
```

**Find lines 60-62** (runtime stage):
```dockerfile
RUN pip install --no-cache-dir \
    torch==2.3.1+cpu \
    --index-url https://download.pytorch.org/whl/cpu
```

**Replace with**:
```dockerfile
RUN pip install --no-cache-dir \
    torch==2.3.1+cu121 \
    --index-url https://download.pytorch.org/whl/cu121
```

---

## Step 4: Rebuild Docker

```bash
cd d:\pskc-project
docker-compose build --no-cache
```

**Expected**:
- Build will take **5-10 minutes** (vs 2-3 minutes for CPU)
- Image will be **2-3GB** (vs 500MB for CPU)
- More packages to download due to CUDA libraries

---

## Step 5: Restart Services

```bash
docker-compose down
docker-compose up -d
```

---

## Step 6: Verify GPU is Available

```bash
# Check PyTorch GPU availability
docker exec pskc-api python -c "
import torch
print(f'PyTorch {torch.__version__}')
print(f'CUDA available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'CUDA device: {torch.cuda.get_device_name(0)}')
    print(f'Number of GPUs: {torch.cuda.device_count()}')
"
```

**Expected output**:
```
PyTorch 2.3.1+cu121
CUDA available: True
CUDA device: (your GPU name)
Number of GPUs: 1
```

Or for CPU-only:
```
PyTorch 2.3.1+cpu
CUDA available: False
```

---

## Comparison: Before vs After

### Before (CPU-Only)
```
Build time: 2-3 minutes
Image size: 500-700 MB
CUDA available: False
Training speed: Normal
Inference speed: Good
GPU used: No
```

### After (CUDA 12.1)
```
Build time: 5-10 minutes
Image size: 2-3 GB
CUDA available: True
Training speed: Much faster 🚀
Inference speed: Very good 🚀
GPU used: Yes (if available)
```

---

## Performance Impact

### If GPU Available:
- **Training**: 5-10x faster
- **Inference**: 2-3x faster
- **Memory**: More GPU memory used

### If GPU NOT Available:
- **Training**: Same as CPU-only
- **Inference**: Same as CPU-only
- **Memory**: Much more RAM needed (CUDA libraries)

---

## Troubleshooting

### Build takes too long
- Normal! CUDA downloads are large (~2GB)
- First build: 10 minutes, subsequent: 5 minutes

### Docker image is huge
- Expected! CUDA version is 2-3GB
- You can clean with: `docker system prune -a`

### GPU not detected
```bash
# Check CUDA version compatibility
docker exec pskc-api python -c "import torch; print(torch.__version__)"

# May need to use cu118 instead of cu121
```

### Want to switch back to CPU-only
- Revert Dockerfile changes (change back `torch==2.3.1+cpu`)
- Run: `docker-compose build --no-cache`
- Done!

---

## Reverting to CPU-Only

If you want to go back to CPU-only (smaller, faster):

**Edit Dockerfile back**:

**Line 29-31**:
```dockerfile
RUN pip install --prefix=/install --no-cache-dir \
    torch==2.3.1+cpu \
    --index-url https://download.pytorch.org/whl/cpu
```

**Line 60-62**:
```dockerfile
RUN pip install --no-cache-dir \
    torch==2.3.1+cpu \
    --index-url https://download.pytorch.org/whl/cpu
```

Then rebuild:
```bash
docker-compose build --no-cache
docker-compose down && docker-compose up -d
```

---

## Recommendation Summary

| Scenario | Recommendation |
|----------|-----------------|
| No GPU available | ✅ Stay with CPU-only |
| Have GPU, train frequently | ✅ Switch to CUDA 12.1 |
| Have GPU, only inference | ✅ Stay with CPU-only (simpler) |
| Want smallest image | ✅ Stay with CPU-only |
| Want fastest training | ✅ Switch to CUDA 12.1 |

---

## Files Affected

Only need to modify:
- `Dockerfile` (2 sections: builder + runtime PyTorch installation)

No code changes needed! PyTorch automatically detects GPU.

---

**Status**: Ready to switch if you have GPU and want training acceleration
**Default**: Keep CPU-only for simplicity and smaller deployments ✅
