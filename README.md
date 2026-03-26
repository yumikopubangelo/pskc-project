# Predictive Secure Key Caching (PSKC)

PSKC adalah sistem cache kunci terenkripsi dengan prediksi ML untuk menurunkan latensi akses key. Saat ini repo ini sudah menjalankan backend FastAPI, L1 cache in-process, L2 Redis terenkripsi, prefetch worker terpisah, model registry aman, realtime simulation, dan dashboard frontend yang membaca backend nyata.

Dokumen ini sengaja fokus ke kondisi implementasi saat ini. Untuk backlog pengembangan berikutnya, baca [docs/feature_roadmap.md](docs/feature_roadmap.md). Untuk daftar fitur yang sudah aktif, baca [docs/comprehensive_features.md](docs/comprehensive_features.md).

## Status Saat Ini

| Area | Status | Ringkasannya |
| --- | --- | --- |
| Backend API | Aktif | FastAPI modular, health, keys, metrics, ML, security, simulation, dan model intelligence sudah tersedia. |
| Cache | Aktif | L1 `LocalCache` + L2 Redis terenkripsi via `EncryptedCacheStore` dan `SecureCacheManager`. |
| Prefetch | Aktif | Request path enqueue job ke Redis, worker terpisah memanaskan shared cache, retry dan DLQ dasar sudah ada. |
| ML runtime | Aktif | Trainer, predictor, River online learning, model registry aman, promote/rollback, lifecycle metadata, dan planner full-training sudah tersambung. |
| Simulation | Aktif | Halaman simulation sekarang fokus ke realtime session dengan bukti L1/L2/KMS, latency breakdown, drift, dan per-key accuracy. |
| Model Intelligence | Aktif | Dashboard versi model, history training, metrics, drift, River stats, dan prediction logs sudah tersedia. |
| Security | Aktif dengan caveat | HTTP security middleware, rate limiter, FIPS startup self-test, tamper-evident audit log, dan IDS sudah aktif. |
| Frontend | Aktif | Overview, Dashboard, Simulation, ML Training, Model Intelligence, dan Security Testing membaca backend. |
| Docker | Aktif | `frontend`, `api`, `redis`, `prefetch-worker`, dan profile monitoring bisa dijalankan. |

## Arsitektur Runtime

```text
browser
  -> frontend (React/Vite)
    -> /api
      -> FastAPI app (src/api/routes.py)
        -> SecureCacheManager
          -> LocalCache (L1, per process)
          -> RedisCache (L2, shared)
          -> EncryptedCacheStore
          -> IDS + audit logger + FIPS crypto
        -> KeyFetcher / KMS fallback
        -> ML runtime (trainer, predictor, registry)
        -> Prefetch queue producer

prefetch-worker
  -> Redis queue
  -> Redis shared cache

database
  -> SQLite by default
  -> stores ModelVersion, TrainingMetadata, ModelMetric, PredictionLog, etc.
```

## Halaman Frontend yang Aktif

| Halaman | Path | Fungsi |
| --- | --- | --- |
| Overview | `/` | Ringkasan status backend dan entry point UI |
| Dashboard | `/dashboard` | Ringkasan metrik runtime |
| Simulation | `/simulation` | Realtime simulation dengan L1/L2/KMS trace, per-key accuracy, drift, dan proof komponen |
| ML Training | `/ml-training` | Generate data, pilih quality profile + time budget, trigger full retrain/evaluation, dan lihat status model |
| Model Intelligence | `/model-intelligence` | Version history, training history, per-version metrics, drift, River, prediction logs |
| Security Testing | `/security-testing` | Tampilan fitur keamanan dan hasil uji |

Catatan:

- Halaman simulation sekarang realtime-only.
- Halaman pipeline / node graph bukan jalur utama lagi.
- `Model Intelligence` memakai endpoint `/api/models/intelligence/dashboard`.
- Endpoint lama `/models/intelligence/dashboard` tetap dilayani untuk kompatibilitas bundle lama.

## Quick Start

### Local backend

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn src.api.routes:app --reload --host 0.0.0.0 --port 8000
```

### Local frontend

```powershell
Set-Location frontend
npm install
npm run dev
```

### Docker

```powershell
docker compose up -d --build frontend api redis prefetch-worker
```

Monitoring profile:

```powershell
docker compose --profile monitoring up -d prometheus grafana
```

## Konfigurasi Penting

Lihat [.env.example](.env.example) untuk daftar lengkap. Variabel yang paling penting:

| Variable | Fungsi |
| --- | --- |
| `APP_ENV` | mode aplikasi |
| `CACHE_ENCRYPTION_KEY` | material awal untuk derivasi master key cache |
| `DATABASE_URL` | URL database jika ingin override default SQLite |
| `DATABASE_PATH` | path file SQLite jika tidak memakai `DATABASE_URL` |
| `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` | koneksi Redis shared cache dan queue |
| `ML_MODEL_NAME` | nama logical model di registry |
| `ML_MODEL_REGISTRY_DIR` | direktori artefak model aman |
| `ML_MODEL_STAGE` | stage default model baru |
| `ML_MODEL_SIGNING_KEY` | signing key metadata model |
| `ML_TRAINING_QUALITY_PROFILE` | profile default full retraining (`fast`, `balanced`, `thorough`) |
| `ML_TRAINING_TIME_BUDGET_MINUTES` | budget default full retraining |
| `ML_TRAINING_TIME_BUDGET_MAX_MINUTES` | batas atas budget full retraining |
| `TRUSTED_PROXIES` | CIDR proxy yang dipercaya untuk forwarded headers |
| `HTTP_SECURITY_*` | hardening middleware HTTP |
| `AUDIT_LOG_DIRECTORY` | lokasi audit log |

## Endpoint Penting

| Method | Path | Fungsi |
| --- | --- | --- |
| `GET` | `/health` | health check |
| `POST` | `/keys/store` | simpan key ke secure cache |
| `POST` | `/keys/access` | ambil key dari L1/L2 atau fallback ke KMS |
| `GET` | `/metrics` | ringkasan metrik dashboard |
| `GET` | `/metrics/prometheus` | exporter Prometheus |
| `GET` | `/ml/status` | status runtime model aktif |
| `GET` | `/ml/registry` | ringkasan registry model |
| `GET` | `/ml/lifecycle` | history lifecycle model |
| `GET` | `/ml/evaluate` | evaluasi model aktif |
| `POST` | `/ml/retrain` | manual retrain |
| `GET` | `/ml/training/plan` | rekomendasi full-training profile, budget, dan hyperparameter |
| `POST` | `/ml/training/train` | start full retraining dengan profile + time budget |
| `POST` | `/ml/promote` | promote version ke stage target |
| `POST` | `/ml/rollback` | rollback ke version aman |
| `GET` | `/api/models/intelligence/dashboard` | payload utama Model Intelligence |
| `POST` | `/simulation/live-session/start` | start realtime simulation |
| `GET` | `/simulation/live-session/{id}` | snapshot realtime simulation |
| `GET` | `/simulation/live-session/{id}/stream` | SSE realtime simulation |
| `POST` | `/simulation/live-session/{id}/stop` | stop realtime simulation |
| `GET` | `/prefetch/dlq` | inspeksi dead-letter queue |

## Validasi yang Disarankan

Focused backend validation:

```powershell
pytest tests/test_settings_database.py tests/test_database_schema_compatibility.py tests/test_model_intelligence_dashboard.py -q
```

Build frontend:

```powershell
Set-Location frontend
npm run build
```

Smoke live via Docker:

```powershell
docker compose up -d --build api redis prefetch-worker
python scripts/smoke_backend_runtime.py
```

Catatan implementasi saat ini:

- startup sekarang memperbaiki schema SQLite lama untuk kolom observability tambahan seperti `per_key_metrics.hit_rate`
- halaman ML Training sudah memakai planner backend untuk quality profile dan time budget
- drift-triggered online learning tetap terpisah dari full retraining, jadi simulation tidak memicu full retrain blocking

## Dokumentasi

Dokumen yang paling berguna sekarang:

- [docs/index.md](docs/index.md)
- [docs/getting_started.md](docs/getting_started.md)
- [docs/comprehensive_features.md](docs/comprehensive_features.md)
- [docs/feature_roadmap.md](docs/feature_roadmap.md)
- [docs/realtime_simulation.md](docs/realtime_simulation.md)
- [docs/architecture/architecture.md](docs/architecture/architecture.md)
- [docs/architecture/api_reference.md](docs/architecture/api_reference.md)
- [docs/architecture/security_model.md](docs/architecture/security_model.md)
- [docs/architecture/simulation_and_ml.md](docs/architecture/simulation_and_ml.md)
- [docs/operations.md](docs/operations.md)
- [docs/development.md](docs/development.md)

## Known Gaps

Hal yang masih belum matang penuh:

- reverse proxy / production deployment profile yang benar-benar siap operasi
- observability historis yang persisten, bukan hanya snapshot runtime
- replay DLQ dan backpressure prefetch yang lebih matang
- governance release model lintas environment
- sebagian test legacy masih menargetkan arsitektur route lama

## Apa yang Harus Dibaca Berikutnya

- Jika Anda ingin menjalankan sistem: baca [docs/getting_started.md](docs/getting_started.md)
- Jika Anda ingin tahu apa yang sudah ada: baca [docs/comprehensive_features.md](docs/comprehensive_features.md)
- Jika Anda ingin tahu apa yang harus dibangun berikutnya: baca [docs/feature_roadmap.md](docs/feature_roadmap.md)
- Jika Anda ingin memahami simulation realtime: baca [docs/realtime_simulation.md](docs/realtime_simulation.md)
