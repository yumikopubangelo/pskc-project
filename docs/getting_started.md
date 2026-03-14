# Getting Started

Dokumen ini menjelaskan cara menjalankan PSKC dengan ekspektasi yang sesuai dengan kondisi repository saat ini.

## Prasyarat

### Backend

- Python 3.11
- `pip`
- Opsional: Docker Desktop

### Frontend

- Node.js 18 atau lebih baru
- `npm`

## 1. Clone dan Konfigurasi Dasar

```powershell
git clone <repo-url>
Set-Location pskc-project
Copy-Item .env.example .env
```

Variabel minimal yang perlu dicek:

- `APP_ENV`
- `APP_PORT`
- `CACHE_ENCRYPTION_KEY`
- `CACHE_TTL_SECONDS`
- `CACHE_MAX_SIZE`

Untuk development lokal, nilai default dari `.env.example` cukup untuk mulai mencoba aplikasi.

## 2. Menjalankan Backend Lokal

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn src.api.routes:app --reload --host 0.0.0.0 --port 8000
```

Jika start berhasil, FastAPI biasanya tersedia di:

- API root: `http://localhost:8000`
- OpenAPI docs: `http://localhost:8000/docs`
- Health: `http://localhost:8000/health`

## 3. Smoke Test Backend

### Health check

```powershell
curl http://localhost:8000/health
```

Respons yang diharapkan mirip:

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "timestamp": "2026-03-10T10:00:00.000000",
  "services": {
    "cache": "ok",
    "ml": "ok",
    "auth": "ok"
  }
}
```

### Simpan kunci ke cache

```powershell
curl -X POST http://localhost:8000/keys/store `
  -H "Content-Type: application/json" `
  -d '{"key_id":"demo-key","key_data":"ZGVtb19rZXlfZGF0YQ==","service_id":"demo-service"}'
```

### Ambil kunci dari cache atau fallback fetcher

```powershell
curl -X POST http://localhost:8000/keys/access `
  -H "Content-Type: application/json" `
  -d '{"key_id":"demo-key","service_id":"demo-service","verify":true}'
```

Catatan penting:

- Field `verify` ada di schema, tetapi saat ini belum dipakai untuk memanggil verifier khusus.
- Field `ttl` ada di schema store, tetapi implementasi endpoint belum meneruskan nilai itu ke secure store.
- Setelah refactor keamanan terbaru, endpoint selain `/health` masih perlu validasi runtime tambahan. Lihat [operations.md](operations.md).

## 4. Menjalankan Frontend Lokal

Frontend interaktif bisa dijalankan langsung dengan Vite lokal atau lewat service Docker frontend.

```powershell
Set-Location frontend
npm install
npm run dev
```

Default Vite URL adalah `http://localhost:3000`.

Catatan frontend saat ini:

- Dashboard utama memakai data backend nyata dan tidak merender fallback dummy.
- Jika backend belum hidup, dashboard akan tetap terbuka tetapi seluruh metrik dan chart berada di state kosong.
- Overview, dashboard, simulation, dan ML pipeline sekarang memakai backend sebagai sumber data utama.
- Halaman simulasi di browser berbeda dari script `simulation/runner.py` di backend.
- `frontend/src/utils/apiClient.js` mendefinisikan beberapa endpoint yang belum ada di FastAPI saat ini.
- Mode default frontend sekarang adalah `auto`, jadi frontend mencoba backend lokal lebih dulu.
- `VITE_API_MODE=mock` sekarang diperlakukan seperti `auto`, sehingga frontend tetap mencoba backend lokal lebih dulu.
- Jika ingin memaksa semua request frontend selalu ke backend lokal, set `VITE_API_MODE=live`.

## 5. Menjalankan dengan Docker

### Opsi yang direkomendasikan

```powershell
docker compose up frontend api redis prefetch-worker
```

Ini cocok untuk mencoba stack frontend, backend, Redis shared cache, dan prefetch worker sekaligus.

Setelah semua service hidup:

- frontend: `http://localhost:3000`
- backend: `http://localhost:8000`

Catatan Docker frontend:

- container frontend menjalankan Vite dev server
- browser tetap mengakses API melalui path relatif `/api`
- Vite di dalam container yang mem-proxy request ke `http://api:8000`
- jangan arahkan browser host ke `http://pskc-api:8000`, karena hostname itu hanya valid di network Docker

### Monitoring profile

```powershell
docker compose --profile monitoring up
```

Profile monitoring sekarang memakai `config/prometheus.yml` yang sudah tersedia di repository ini.

## 6. Menjalankan Simulasi

```powershell
python simulation/runner.py --scenario all
python simulation/runner.py --scenario spotify
python simulation/runner.py --scenario amazon --requests 2000
python simulation/runner.py --scenario dynamic --requests 2000
python simulation/runner.py --scenario coldstart
```

Lihat [simulation_and_ml.md](simulation_and_ml.md) untuk detail skenario.

## 7. Menjalankan Script ML dan Data

```powershell
python scripts/seed_data.py
python scripts/generate_training_data.py --scenario all --samples 5000
python scripts/train_model.py --data data/training/pskc_training_data.json
python scripts/benchmark.py --all
```

## Troubleshooting Singkat

### Aplikasi start tetapi endpoint tertentu error

Periksa area berikut:

- boundary cache terenkripsi dan audit logger setelah refactor keamanan
- path log `/app/logs` yang dipakai saat startup
- endpoint frontend atau script yang masih mengacu ke API lama

### Frontend Docker tidak bisa memanggil backend

Periksa tiga hal:

- service `frontend` dan `api` sama-sama hidup di compose
- environment frontend memakai `VITE_API_URL=/api`
- proxy target frontend mengarah ke `http://api:8000`, bukan `http://pskc-api:8000` di sisi browser

### Monitoring profile gagal start

Pastikan service `api`, `prometheus`, dan `grafana` ikut start jika Anda mengaktifkan profile `monitoring`.
