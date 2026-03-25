# PyTorch Version Selection Guide

## Current Setup
Currently using: **`torch==2.3.1+cpu`** (CPU-only lightweight version)

## PyTorch Version Options

### Option 1: CPU-Only (Current) ⚡ LIGHTWEIGHT
```
torch==2.3.1+cpu
```
**Details**:
- Size: ~500-700 MB
- Features: CPU-only, optimized for CPU inference
- GPU Support: ❌ No
- Performance: Good for CPU-based systems
- Installation: Fast (~2-3 minutes)

**Pros**:
- ✅ Smallest image size (~500MB)
- ✅ Faster build time
- ✅ Lower memory footprint
- ✅ Sufficient for CPU-only inference

**Cons**:
- ❌ No GPU acceleration
- ❌ Limited pre-compiled optimizations

---

### Option 2: CUDA-enabled (Heavier) 🚀 NORMAL
```
torch==2.3.1  # From default PyPI or torch with CUDA
torch==2.3.1+cu118  # CUDA 11.8 version
torch==2.3.1+cu121  # CUDA 12.1 version
```
**Details**:
- Size: **~2-3 GB** (1.5-2GB per version)
- Features: GPU support (NVIDIA CUDA)
- GPU Support: ✅ Yes (NVIDIA GPUs)
- Performance: Best with GPU, good with CPU fallback
- Installation: Slower (~5-10 minutes)

**Pros**:
- ✅ GPU acceleration (if GPU available)
- ✅ Better performance on GPU
- ✅ Can fallback to CPU
- ✅ Includes all optimizations

**Cons**:
- ❌ **Much larger image** (~2-3GB vs 500MB)
- ❌ Slower build and deployment
- ❌ More disk space needed
- ❌ GPU only beneficial if you have NVIDIA GPU

---

### Option 3: AMD GPU (if applicable)
```
torch==2.3.1+rocm5.7  # For AMD GPUs
```
Not applicable for most users.

---

## Comparison Table

| Aspect | CPU-Only | CUDA 11.8 | CUDA 12.1 |
|--------|----------|-----------|-----------|
| Image Size | 500-700 MB | 2-2.5 GB | 2-3 GB |
| CPU Performance | Good ✅ | Good ✅ | Good ✅ |
| GPU Performance | N/A | Excellent 🚀 | Excellent 🚀 |
| Build Time | 2-3 min | 5-10 min | 5-10 min |
| Deployment Time | Fast ⚡ | Slower | Slower |
| Requires GPU | ❌ No | ✅ Yes | ✅ Yes |
| Deployment Feasibility | Easy | Medium | Medium |

---

## Recommendation

### Use **CPU-Only** (Current) if:
✅ No NVIDIA GPU available
✅ Running on CPU-only server (AWS/GCP CPU instances)
✅ Want fast deployment and small image
✅ Image size is a constraint
✅ Cost is important (smaller deployments)

### Use **CUDA** (Heavier) if:
✅ Have NVIDIA GPU available
✅ Need GPU acceleration for training
✅ Training speed is critical
✅ Can afford 2-3GB larger image
✅ Using on-premises GPU servers

---

## For Your PSKC Project

**Current Recommendation: Keep CPU-Only (Current)**

**Reasoning**:
1. **PSKC is inference-focused**: Model inference on keys, not training
2. **CPU performance sufficient**: Key-value lookups don't require GPU
3. **Deployment simplicity**: Smaller image, faster deployment
4. **Cost-effective**: Less resources needed per container
5. **LSTM model**: Not GPU-intensive for inference

**When to switch to CUDA**:
- If training new models frequently (would benefit from GPU)
- If running on GPU infrastructure anyway
- If inference latency becomes bottleneck (unlikely for key caching)

---

## If You Want to Switch

### Change to CUDA 12.1 (Recommended if using GPU):

**Edit `Dockerfile` line 29-31**:

```dockerfile
# FROM THIS:
RUN pip install --prefix=/install --no-cache-dir \
    torch==2.3.1+cpu \
    --index-url https://download.pytorch.org/whl/cpu

# TO THIS:
RUN pip install --prefix=/install --no-cache-dir \
    torch==2.3.1 \
    --index-url https://download.pytorch.org/whl/cu121
```

Also update **line 60-62** (runtime stage):

```dockerfile
# FROM THIS:
RUN pip install --no-cache-dir \
    torch==2.3.1+cpu \
    --index-url https://download.pytorch.org/whl/cpu

# TO THIS:
RUN pip install --no-cache-dir \
    torch==2.3.1 \
    --index-url https://download.pytorch.org/whl/cu121
```

### Change to CUDA 11.8 (For older systems):

```dockerfile
torch==2.3.1+cu118 \
--index-url https://download.pytorch.org/whl/cu118
```

---

## What Changes After Switching

### Dockerfile Build:
- Build time: 2-3 min → 5-10 min (longer)
- Image size: 500 MB → 2-3 GB (larger)
- Docker layer: ~2GB download + storage

### Container Startup:
- Still same startup time
- Uses GPU if available, CPU as fallback

### Code Changes:
- **NONE**: Your code works the same
- PyTorch automatically detects GPU
- LSTM training/inference uses GPU if available

### Performance:
- CPU inference: Same as CPU-only
- GPU inference: Much faster (if GPU available)
- Memory usage: Higher (loaded CUDA libraries)

---

## Checking Your Hardware

### Do you have GPU?

```bash
# Check if you have NVIDIA GPU
nvidia-smi

# Or in Docker
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
```

### If no GPU available → Use CPU-Only (Current) ✅
### If GPU available → Consider CUDA version ✅

---

## Installation Index

| Version | Use Case | Download | Size |
|---------|----------|----------|------|
| `torch==2.3.1+cpu` | CPU-only servers | PyTorch CPU wheels | ~600 MB |
| `torch==2.3.1+cu118` | NVIDIA CUDA 11.8 | PyTorch CUDA wheels | ~2.2 GB |
| `torch==2.3.1+cu121` | NVIDIA CUDA 12.1 | PyTorch CUDA wheels | ~2.3 GB |

---

## My Recommendation for PSKC

**🎯 Keep CPU-Only (current)**

**Reasoning**:
1. PSKC bottleneck is **network latency** (KMS calls), not computation
2. LSTM inference very fast on CPU
3. GPU helps only if doing **training frequently**
4. Your architecture is inference-heavy, not training-heavy
5. Docker image 500MB vs 2.5GB = 5x smaller, 5x faster deployment

**Future consideration**:
- If you add real-time model retraining (not just periodic training)
- Then GPU would help significantly
- For now, not necessary

---

## Quick Decision Tree

```
Do you have NVIDIA GPU available?
├─ YES → Do you train models frequently?
│  ├─ YES → Use CUDA 12.1 (torch==2.3.1+cu121)
│  └─ NO → Keep CPU-Only (current setup)
└─ NO → Keep CPU-Only (current setup) ✅
```

---

## Summary

| Version | Size | Speed | GPU | Recommendation |
|---------|------|-------|-----|-----------------|
| **CPU-Only (Current)** | **500 MB** | **Fast** | **No** | **✅ For PSKC** |
| CUDA 12.1 | 2.3 GB | Normal | Yes | For GPU systems |
| CUDA 11.8 | 2.2 GB | Normal | Yes | For older NVIDIA |

**Current setup is optimal for PSKC** ✅
