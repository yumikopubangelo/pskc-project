# Predictive Secure Key Caching (PSKC)

PSKC adalah proyek riset dan demo untuk menurunkan latensi autentikasi di arsitektur mikroservis dengan cara menyimpan material kunci secara lokal, terenkripsi, dan dapat dipanaskan terlebih dahulu berdasarkan pola akses.

Dokumentasi di repository ini sekarang mengikuti implementasi yang benar-benar ada di kode, termasuk fitur yang masih parsial atau belum terhubung penuh.

## Ringkasan Status

| Area | Status | Catatan |
| --- | --- | --- |
| Backend API | Aktif | FastAPI menyediakan endpoint health, cache metrics, ML status, dan simulation yang dipakai frontend saat ini. |
| Secure cache | Aktif | Jalur request memakai `LocalCache` sebagai L1, Redis sebagai shared encrypted L2, `EncryptedCacheStore`, dan `SecureCacheManager`. |
| ML dan simulasi | Online via API | Frontend memanggil endpoint ML dan simulation backend. Request path mengumpulkan event ML runtime, lalu menjadwalkan prefetch via Redis queue ke worker terpisah dengan retry dan DLQ. EWMA concept drift detection sudah mature dengan multiple methods (EWMA, ADWIN, EDDM). |
| Incremental Model | Aktif | Single-file model yang terus berkembang, tidak membuat file baru setiap training. |
| Data Processor | Aktif | Pipeline dari raw ke processed data dengan feature engineering. |
| Key Rotation | Aktif | Zero-downtime rotation dengan grace period dan atomicity. |
| Governance Model | Aktif | Signing, provenance, promotion, rollback tersedia. Ensemble LSTM+RF+Markov berjalan. |
| Security hardening | Aktif dengan caveat | Wrapper kriptografi, trusted proxy parsing, tamper-evident logger, HTTP security middleware, rate limiter, dan FIPS power-on self-tests sudah aktif. Policy deployment seperti `TRUSTED_PROXIES` tetap perlu diisi sesuai topologi nyata. |
| Frontend | Terhubung ke backend | Overview, Dashboard, Simulation, dan ML Pipeline membaca data backend. Node Graph tetap konseptual tetapi menampilkan status runtime nyata. |
| Docker stack | Aktif dengan validasi minimum | `api`, `redis`, `prefetch-worker`, dan profile monitoring sekarang bisa dijalankan. Repo juga punya smoke test live `docker compose` dan workflow CI minimum untuk focused backend tests + runtime validation. Benchmark validation suite tersedia untuk reproducibility dan statistical testing. |
| Kubernetes | Tersedia | Konfigurasi K8s lengkap dengan HPA, network policies, dan persistent volumes. |
| Deployment Policies | Dokumentasi lengkap | docs/deployment_policies.md berisi scaling, backup, security, dan HA policies.

## Peta Dokumentasi

- [docs/index.md](docs/index.md) - daftar seluruh dokumen
- [docs/getting_started.md](docs/getting_started.md) - cara menjalankan proyek secara lokal dan dengan Docker
- [docs/project_status.md](docs/project_status.md) - daftar yang belum selesai, masih kurang, dan belum dikembangkan
- [docs/feature_roadmap.md](docs/feature_roadmap.md) - backlog fitur yang lebih detail, prioritas, dan definisi selesai
- [docs/architecture.md](docs/architecture.md) - arsitektur runtime dan alur request yang aktif
- [docs/api_reference.md](docs/api_reference.md) - referensi endpoint FastAPI yang tersedia saat ini
- [docs/security_model.md](docs/security_model.md) - model keamanan, kontrol aktif, dan gap yang masih ada
- [docs/simulation_and_ml.md](docs/simulation_and_ml.md) - engine simulasi, training data, dan pipeline ML
- [docs/development.md](docs/development.md) - panduan contributor, struktur kode, dan status test suite
- [docs/operations.md](docs/operations.md) - konfigurasi, Docker, observability, dan catatan deployment
- [docs/security_analysis_report.md](docs/security_analysis_report.md) - status terkini dari temuan keamanan historis
- [docs/gemini.md](docs/gemini.md) - ringkasan tingkat tinggi untuk stakeholder non-teknis
- [docs/deployment_policies.md](docs/deployment_policies.md) - kebijakan deployment production, scaling, dan backup

## Arsitektur Singkat

Komponen runtime backend saat ini terlihat seperti berikut:

```text
client
  -> FastAPI app (`src/api/routes.py`)
    -> SecureCacheManager
      -> EncryptedCacheStore
        -> LocalCache (in-process)
        -> Redis shared cache
        -> CachePolicyManager
        -> FipsCryptographicModule
        -> TamperEvidentAuditLogger
    -> KeyFetcher (hanya saat cache miss)
  -> Prefetch worker (`src/workers/prefetch_worker.py`)
    -> Redis prefetch queue
    -> Redis shared cache
```

Poin penting:

- Jalur request API sekarang memakai Redis sebagai shared encrypted cache dan queue untuk prefetch worker.
- Request path sekarang merekam event untuk collector ML runtime dan melayani endpoint status/prediction/training.
- Pipeline model aman sekarang satu jalur: training script menyimpan artefak `.pskc.json` ke registry, registry mengaktifkan version baru, dan runtime trainer/predictor memuat active version itu saat startup.
- Simulator backend tersedia melalui endpoint khusus dan tetap terisolasi dari jalur request produksi.
- FastAPI tetap menyediakan OpenAPI bawaan di `/docs` selama aplikasi berhasil start.

## Struktur Repository

```text
.
|-- README.md
|-- config/
|-- data/
|-- docs/
|-- frontend/
|-- k8s/
|-- scripts/
|-- simulation/
|-- src/
`-- tests/
```

Folder penting:

- `src/api` - aplikasi FastAPI dan schema request/response
- `src/cache` - cache in-memory, kebijakan TTL, dan store terenkripsi
- `src/security` - boundary kriptografi, audit log, IDS, middleware keamanan
- `src/ml` - collector, feature engineering, model, registry, predictor, incremental model, data processor
- `k8s` - Kubernetes deployment manifests
- `simulation` - skenario benchmark berbasis parameter referensi
- `scripts` - utilitas untuk seed data, generate training data, benchmark, dan training
- `frontend` - dashboard demo berbasis React/Vite
- `docs` - dokumentasi teknis dan operasional

## Quick Start

### Opsi yang paling aman untuk mencoba backend

1. Salin environment file.
2. Jalankan backend lokal atau `docker compose up api redis prefetch-worker`.
3. Verifikasi `GET /health`.
4. Jalankan frontend via Vite jika ingin UI interaktif.

### Menjalankan backend lokal

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn src.api.routes:app --reload --host 0.0.0.0 --port 8000
```

### Menjalankan frontend lokal

```powershell
Set-Location frontend
npm install
npm run dev
```

Frontend Vite default tersedia di `http://localhost:3000`.

Catatan:

- Mode frontend default sekarang adalah `auto`, jadi dashboard akan mencoba membaca backend lokal lebih dulu.
- Jika backend belum hidup, dashboard menampilkan state kosong alih-alih angka dummy.
- `VITE_API_MODE=mock` sekarang diperlakukan seperti `auto` agar frontend tetap mengarah ke backend, bukan kembali ke dataset demo lokal.
- Jika ingin memaksa semua request frontend selalu ke backend lokal, set `VITE_API_MODE=live`.

### Menjalankan dengan Docker

```powershell
docker compose up frontend api redis prefetch-worker
```

Catatan:

- Frontend Docker tersedia di `http://localhost:3000` dan mem-proxy `/api` ke service `api:8000` di network Docker.
- Jangan set `VITE_API_URL` ke `http://pskc-api:8000` untuk browser host. Hostname itu hanya valid antar-container.
- Profile `monitoring` sekarang memakai `config/prometheus.yml` bawaan repo dan scrape `api` di `/metrics/prometheus`.

### Validasi backend live

Untuk validasi minimum yang benar-benar menjalankan stack backend:

```powershell
pytest tests/test_api_request_paths.py tests/test_http_security_middleware.py tests/test_prometheus_exporter.py tests/test_audit_logger.py tests/test_fips_self_tests.py tests/test_redis_resilience.py tests/test_ml.py -q
docker compose up -d --build api redis prefetch-worker
python scripts/smoke_backend_runtime.py
docker compose down -v
```

Smoke test live di atas memvalidasi startup, security headers, request path `store/access`, cache hit/miss, endpoint ML, endpoint simulation, audit endpoint, metrik Prometheus, dan worker prefetch berbasis Redis.

## Endpoint yang Tersedia

| Method | Path | Keterangan |
| --- | --- | --- |
| `GET` | `/health` | Health check sederhana |
| `POST` | `/keys/access` | Ambil kunci dari cache lokal atau fallback ke `KeyFetcher` |
| `POST` | `/keys/store` | Simpan kunci base64 ke cache terenkripsi |
| `GET` | `/metrics` | Ringkasan metrik backend untuk dashboard dan overview |
| `GET` | `/metrics/prefetch` | Status queue prefetch Redis, retry backlog, dan DLQ |
| `GET` | `/metrics/prometheus` | Exporter Prometheus text exposition untuk observability |
| `GET` | `/ml/status` | Status runtime ML, jumlah sample collector, dan waktu training terakhir |
| `GET` | `/ml/drift` | Analisis EWMA concept drift dengan statistik detail |
| `GET` | `/ml/registry` | Ringkasan registry model aktif, versi, stage, dan signature coverage |
| `GET` | `/ml/lifecycle` | History lifecycle model yang persisten |
| `POST` | `/ml/promote` | Promosikan versi model ke stage target dan opsional aktifkan runtime |
| `POST` | `/ml/rollback` | Rollback runtime ke versi model aman sebelumnya |
| `GET` | `/simulation/scenarios` | Katalog skenario simulasi backend |
| `POST` | `/simulation/run` | Jalankan simulasi backend |
| `GET` | `/simulation/results/{id}` | Ambil hasil simulasi backend |
| `GET` | `/prefetch/dlq` | Lihat job prefetch yang masuk dead-letter queue |

Lihat detail payload dan caveat implementasi di [docs/api_reference.md](docs/api_reference.md).

## Simulasi dan ML

PSKC menyediakan engine simulasi yang dirancang untuk studi kasus sistem autentikasi akademik dan pemerintahan Indonesia.

### Skenario Simulasi yang Tersedia

| Skenario | Deskripsi | Sumber Referensi |
|----------|-----------|------------------|
| **SIAKAD SSO** | Portal Akademik Perguruan Tinggi (single tenant) | JSiI Vol.10 No.1 (2023); MDPI App.Sci. 15(22) (2025) |
| **SEVIMA Siakadcloud** | SIAKAD Multi-Tenant Cloud | Data resmi SEVIMA (2024) - >900 PT Indonesia |
| **PDDikti** | Pangkalan Data Pendidikan Tinggi Nasional | Kemdikbudristek (2024) - >4.900 PT, 9,6 juta mahasiswa |
| **Dynamic Production** | Perubahan beban kerja dan failure pattern campuran | Simulasi berbasis parameter dinamis |
| **Cold Start** | Evolusi ML dari warmup hingga mature dengan EWMA concept drift | Analisis fase ML lifecycle |

### Command Simulasi

```powershell
# Jalankan semua skenario
python simulation/runner.py --scenario all

# SIAKAD SSO
python simulation/runner.py --scenario siakad --requests 2000

# SEVIMA Siakadcloud
python simulation/runner.py --scenario sevima --requests 2000

# PDDikti
python simulation/runner.py --scenario pddikti --requests 2000

# Dynamic Production
python simulation/runner.py --scenario dynamic --requests 2000

# Cold Start Analysis
python simulation/runner.py --scenario coldstart
```

### Machine Learning

PSKC menggunakan ensemble model yang menggabungkan:
- **LSTM** - untuk pola sekuensial temporal
- **RandomForest** - untuk feature importance dan stabilitas
- **Markov Chain** - untuk transisi state probabilistik

Pipeline ML:
```powershell
# Generate training data dari skenario
python scripts/generate_training_data.py --scenario all --samples 5000

# Training model
python scripts/train_model.py --data data/training/pskc_training_data.json

# Benchmark baseline vs PSKC
python scripts/benchmark.py --all
```

**Catatan:** EWMA concept drift detection sudah mature dengan multiple detection methods (EWMA, ADWIN-like, EDDM) dan weighted voting untuk decision making.

Penjelasan lebih lengkap ada di [docs/simulation_and_ml.md](docs/simulation_and_ml.md).

### Incremental Model Persistence

PSKC sekarang mendukung **single-file model yang terus berkembang** selain versioning tradisional:

```python
from src.ml.incremental_model import get_incremental_model

# Update model (tidak membuat file baru)
incremental = get_incremental_model()
result = incremental.update(
    model_data=serialized_model,
    reason="scheduled",  # atau "drift", "manual"
    metrics={"accuracy": 0.85},
    training_info={"sample_count": 1000}
)
```

File model disimpan di `data/models/incremental_model.pskc.json` dan terus di-update, tidak membuat file baru setiap training.

### Data Processor

Pipeline data dari raw ke processed:

```python
from src.ml.data_processor import get_data_processor

processor = get_data_processor()
result = processor.process(context_window=10)
```

Output di `data/processed/`:
- `training_data.json` - Data training dengan context window
- `key_features.json` - Fitur agregat per key
- `temporal_patterns.json` - Pola waktu akses
- `metadata.json` - Info processing

# Benchmark Validation Suite

PSKC menyediakan benchmark validator dengan reproducibility dan formal statistical validation:

```powershell
# Test scenario dengan 10 runs
python simulation/benchmark_validator.py --scenario test --runs 10 --seed 42

# SIAKAD scenario dengan 30 runs
python simulation/benchmark_validator.py --scenario siakad --runs 30 --seed 123

# Random seed mode (non-reproducible)
python simulation/benchmark_validator.py --scenario sevima --runs 50 --random-seed

# Save results to JSON
python simulation/benchmark_validator.py --scenario pddikti --runs 20 --output results.json
```

Fitur:
- **Reproducibility**: Seed control, deterministic execution
- **Statistical Validation**: Confidence intervals, hypothesis testing (Welch's t-test, Mann-Whitney U)
- **Effect Size**: Cohen's d dengan interpretasi (negligible/small/medium/large)
- **Multi-run Analysis**: Aggregated results dengan error bounds

Output mencakup:
- Konfigurasi dan timing
- Per-metric statistical comparisons (avg_ms, p95_ms, p99_ms, cache_hit_rate)
- p-values dengan significance indicators
- Confidence intervals untuk improvement
- Summary: all_significant, avg_improvement, avg_effect_size

## Production Deployment

PSKC mendukung deployment dengan Docker Compose dan Kubernetes:

### Docker Compose Production

```powershell
docker compose -f docker-compose.production.yml up -d
```

Fitur:
- Resource limits per service
- Rolling updates dengan auto-rollback
- Health checks (liveness/readiness)
- Redis dengan persistence (RDB + AOF)
- Prometheus + Grafana monitoring

### Kubernetes Deployment

```bash
kubectl apply -f k8s/pskc-production.yaml
```

Fitur:
- Horizontal Pod Autoscaler (HPA)
- Pod anti-affinity untuk high availability
- Network policies
- Persistent volume claims
- Ingress configuration

### Deployment Policies

Lihat [docs/deployment_policies.md](docs/deployment_policies.md) untuk:
- Resource allocation matrix
- Scaling triggers
- Backup & recovery procedures
- Security hardening
- Health check policies

### EWMA Concept Drift Detection

PSKC implements mature EWMA-based concept drift detection untuk auto-retraining:

```python
from src.ml.trainer import get_model_trainer

trainer = get_model_trainer()
drift_stats = trainer._drift_detector.get_stats()
drift_analysis = trainer._drift_detector.get_drift_analysis()
```

Detection methods:
- **EWMA**: Exponential weighted moving average comparison
- **ADWIN-like**: Adaptive windowing dengan statistical testing
- **EDDM**: Early drift detection method
- **Weighted voting**: Combines all methods untuk decision

Configuration:
```python
DriftDetector(
    short_window=30,        # Short-term window
    long_window=200,        # Long-term window
    drift_threshold=0.12,   # 12% drop triggers retrain
    warning_threshold=0.06, # 6% drop = warning
    ewma_alpha=0.3,        # EWMA smoothing factor
)
```

API endpoint: `GET /ml/drift`

## Konfigurasi Utama

Variabel penting dari `.env.example`:

| Variable | Fungsi |
| --- | --- |
| `APP_ENV` | mode aplikasi (`development` atau `production`) |
| `APP_PORT` | port FastAPI |
| `FIPS_SELF_TEST_ENABLED` | toggle untuk self-test kriptografi saat startup; default sebaiknya tetap `true` |
| `TRUSTED_PROXIES` | daftar CIDR proxy tepercaya yang boleh meneruskan `X-Forwarded-For` |
| `AUDIT_LOG_DIRECTORY` | direktori root audit log untuk service runtime; di Docker Compose backend dipisah per-service di bawah `/app/logs` |
| `CACHE_ENCRYPTION_KEY` | material awal untuk derivasi master key cache |
| `CACHE_TTL_SECONDS` | TTL default cache |
| `CACHE_MAX_SIZE` | kapasitas maksimum cache in-memory |
| `HTTP_SECURITY_*` | toggle dan tuning middleware header hardening, request size limit, dan rate limiter |
| `ML_MODEL_NAME` | nama logical model di registry aktif |
| `ML_MODEL_REGISTRY_DIR` | direktori registry model dan checksum manifest |
| `ML_MODEL_STAGE` | stage default artefak model baru, misalnya `development`, `staging`, atau `production` |
| `ML_MODEL_SIGNING_KEY` | secret opsional untuk signing metadata model; jika kosong, runtime fallback ke `CACHE_ENCRYPTION_KEY` |
| `ML_MODEL_PATH` | path kompatibilitas lama; runtime utama sekarang membaca active version dari registry |
| `ML_PREDICTION_THRESHOLD` | threshold prediksi |
| `SIMULATION_MODE` | flag mode simulasi |
| `SIMULATION_SCENARIO` | skenario simulasi default |
| `REDIS_*` | konfigurasi Redis untuk deployment atau eksperimen lanjutan |

## Known Limitations

Dokumen ini sengaja mencatat gap yang masih ada:

1. Repo sekarang punya focused backend test suite dan smoke test live `docker compose`, tetapi coverage deployment belum mencakup seluruh variasi topologi seperti reverse proxy nyata, profile monitoring, dan matrix environment production.
2. Middleware keamanan HTTP dan rate limiter sekarang aktif by default. Jika deployment Anda memakai reverse proxy, `TRUSTED_PROXIES` dan opsi `HTTP_SECURITY_*` perlu diisi sesuai topologi aktual.
3. FIPS power-on self-tests sekarang aktif by default saat startup. Walau begitu, backend tetap belum boleh diklaim FIPS compliant karena provider kriptografi yang dipakai belum tersertifikasi.
4. Pipeline ML sekarang sudah online untuk collector, prediction, manual retraining, dan prefetch worker terpisah berbasis Redis dengan retry/DLQ dasar. Training script, model registry, active version, runtime load, signing metadata, provenance, promotion, rollback, dan lifecycle observability sekarang sudah satu jalur.
5. Yang masih belum matang di area ML/ops adalah governance level lanjutannya: approval workflow antar environment, provenance eksternal seperti commit signing/SBOM, dan telemetry historis yang lebih kaya di luar snapshot runtime/registry saat ini.
6. Frontend utama sekarang sudah membaca backend untuk overview, dashboard, simulation, dan ML pipeline. Node Graph masih mempertahankan animasi konseptual, tetapi badge runtime-nya sudah berasal dari backend.
7. Test suite di `tests/` masih mencampur test legacy dan test untuk implementasi baru, sehingga tidak bisa diasumsikan seluruhnya hijau tanpa refactor tambahan.
8. Telemetry Prometheus sekarang tersedia lewat `/metrics/prometheus`, tetapi metrik backend masih berbasis snapshot runtime dan belum seluruhnya historis/persisten.

## Rekomendasi Membaca

Urutan yang disarankan untuk memahami proyek:

1. [docs/getting_started.md](docs/getting_started.md)
2. [docs/architecture.md](docs/architecture.md)
3. [docs/api_reference.md](docs/api_reference.md)
4. [docs/security_model.md](docs/security_model.md)
5. [docs/simulation_and_ml.md](docs/simulation_and_ml.md)
6. [docs/development.md](docs/development.md)

## Lisensi

Repository ini disusun untuk kebutuhan riset, evaluasi, dan presentasi teknis. Referensi sumber simulasi dicantumkan di [simulation/references/README.md](simulation/references/README.md).
