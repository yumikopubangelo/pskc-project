# PyTorch Version - Lightweight vs Normal (Indonesia)

## Status Saat Ini
Menggunakan: **`torch==2.3.1+cpu`** (CPU-only, lightweight)

---

## Pertanyaan Anda
"Kalau pytorch yang lebih berat itu apakah bisa? Lebih bagus lightweight atau normal?"

**Jawab**: Kedua bisa, tapi tergantung kebutuhan. Berikut penjelasannya:

---

## Perbandingan: Lightweight vs Normal

### ⚡ Lightweight (Current - CPU Only)
```
torch==2.3.1+cpu
```
- **Ukuran image**: 500-700 MB
- **GPU**: ❌ Tidak ada support
- **Kecepatan build**: 2-3 menit
- **Performa**: Cukup untuk CPU, tidak perlu GPU

✅ Cocok untuk PSKC

### 🚀 Normal/Full (Dengan CUDA)
```
torch==2.3.1+cu121  (CUDA 12.1)
atau
torch==2.3.1+cu118  (CUDA 11.8)
```
- **Ukuran image**: 2-3 GB (5x lebih besar!)
- **GPU**: ✅ Support NVIDIA GPU
- **Kecepatan build**: 5-10 menit (2-3x lebih lambat)
- **Performa**: Jauh lebih cepat jika ada GPU

---

## Mana Yang Lebih Baik?

### Pakai **Lightweight (Current)** ✅ Jika:
- ✅ Tidak punya GPU NVIDIA
- ✅ Fokus pada inference (prediksi), bukan training
- ✅ Ingin image docker lebih kecil
- ✅ Ingin deployment lebih cepat
- ✅ Ingin menghemat space
- ✅ PSKC hanya menjalankan inference

### Pakai **Normal/Full (CUDA)** ✅ Jika:
- ✅ Punya GPU NVIDIA
- ✅ Sering training model baru
- ✅ Butuh kecepatan training
- ✅ Bisa beli server dengan GPU
- ✅ Training speed adalah prioritas

---

## Untuk PSKC, Rekomendasi: **TETAP LIGHTWEIGHT ✅**

**Alasan**:
1. PSKC adalah **inference-heavy**, bukan training-heavy
2. Model LSTM inference **sangat cepat** di CPU
3. Bottleneck PSKC adalah **latency KMS**, bukan computational time
4. GPU hanya membantu kalau frequent training
5. Docker image 500MB vs 2.5GB = lebih cepat deploy

---

## Kalau Mau Ganti ke CUDA (Normal/Heavier)

### Langkah 1: Cek GPU
```bash
nvidia-smi
```
Jika tidak ada GPU → jangan ganti

### Langkah 2: Edit Dockerfile (2 tempat)

**Tempat 1 - Line 29-31 (Builder)**:
```dockerfile
# Dari:
RUN pip install --prefix=/install --no-cache-dir \
    torch==2.3.1+cpu \
    --index-url https://download.pytorch.org/whl/cpu

# Menjadi:
RUN pip install --prefix=/install --no-cache-dir \
    torch==2.3.1+cu121 \
    --index-url https://download.pytorch.org/whl/cu121
```

**Tempat 2 - Line 60-62 (Runtime)**:
```dockerfile
# Dari:
RUN pip install --no-cache-dir \
    torch==2.3.1+cpu \
    --index-url https://download.pytorch.org/whl/cpu

# Menjadi:
RUN pip install --no-cache-dir \
    torch==2.3.1+cu121 \
    --index-url https://download.pytorch.org/whl/cu121
```

### Langkah 3: Rebuild & Restart
```bash
docker-compose build --no-cache
docker-compose down && docker-compose up -d
```

**Waktu**: 5-10 menit (vs 2-3 menit untuk CPU)

---

## Tabel Perbandingan

| Aspek | Lightweight | Normal (CUDA) |
|-------|------------|---------------|
| Ukuran | 500 MB | 2-3 GB |
| Kecepatan Build | 2-3 menit | 5-10 menit |
| Inference Speed | Good ✅ | Excellent 🚀 (dengan GPU) |
| Training Speed | Normal | Cepat 🚀 (dengan GPU) |
| GPU Support | ❌ Tidak | ✅ Ya |
| Cocok untuk PSKC | ✅ Ya | Overengineering |

---

## Keputusan Cepat

```
Apakah punya GPU?
├─ TIDAK → Pakai Lightweight (current) ✅
└─ YA → 
    ├─ Sering training? → Pakai CUDA 12.1 ✅
    └─ Hanya inference? → Pakai Lightweight (current) ✅
```

---

## Kesimpulannya:

**Untuk PSKC:**
- **Lightweight (current) adalah pilihan terbaik** ✅
- Bukan karena lightweight lebih baik, tapi karena sesuai kebutuhan PSKC
- Jika ada GPU dan sering training → bisa ganti ke CUDA
- Tapi untuk sekarang, **tetap lightweight** adalah optimal

---

## Dokumentasi Lengkap

- `PYTORCH_VERSION_GUIDE.md` - Penjelasan detail
- `PYTORCH_VERSION_SWITCH.md` - Cara switch ke CUDA
- `PYTORCH_FIX.md` - Fix PyTorch yang tidak ter-install

**Status**: ✅ Lightweight recommended untuk PSKC
