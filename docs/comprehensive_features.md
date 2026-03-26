# Comprehensive Features PSKC

Dokumen ini mencatat fitur yang **sudah aktif atau sudah terimplementasi** di repo saat ini. Untuk backlog berikutnya, baca [feature_roadmap.md](feature_roadmap.md).

Tujuan dokumen ini sederhana: kalau Anda bertanya "apa saja yang sudah benar-benar ada?", jawabannya ada di sini.

## 1. Backend Runtime

**Status:** aktif

Yang sudah ada:

- FastAPI modular di `src/api/`
- health, keys, metrics, ML, simulation, security, dan model intelligence endpoints
- bootstrap runtime service di `src/runtime/bootstrap.py`
- startup FIPS self-test dan dependency priming

File utama:

- `src/api/routes.py`
- `src/api/route_health.py`
- `src/api/route_keys.py`
- `src/api/route_metrics.py`
- `src/api/route_ml.py`
- `src/api/route_simulation.py`
- `src/api/routes_models.py`

## 2. Secure Cache

**Status:** aktif

Yang sudah ada:

- L1 `LocalCache` per process
- L2 Redis shared cache
- `EncryptedCacheStore`
- `SecureCacheManager`
- TTL policy dan metadata dasar

File utama:

- `src/cache/local_cache.py`
- `src/cache/redis_cache.py`
- `src/cache/encrypted_store.py`
- `src/security/intrusion_detection.py`

## 3. Prefetch Worker

**Status:** aktif

Yang sudah ada:

- request path enqueue job prefetch ke Redis
- worker terpisah yang konsumsi queue
- retry dasar
- dead-letter queue dasar
- proof worker di realtime simulation

File utama:

- `src/prefetch/queue.py`
- `src/workers/prefetch_worker.py`
- `src/api/ml_service.py`

## 4. Security Hardening

**Status:** aktif dengan caveat deployment

Yang sudah ada:

- HTTP security middleware
- request size limit
- rate limiter
- trusted proxy parsing
- tamper-evident audit logger
- IDS / reputation checks
- FIPS-style startup self-tests

File utama:

- `src/security/security_headers.py`
- `src/security/tamper_evident_logger.py`
- `src/security/intrusion_detection.py`
- `src/security/fips_self_tests.py`

## 5. Machine Learning Runtime

**Status:** aktif

Yang sudah ada:

- `ModelTrainer`
- `KeyPredictor`
- ensemble model runtime
- secure model registry
- promote / rollback
- lifecycle metadata
- River online learning path

File utama:

- `src/ml/trainer.py`
- `src/ml/predictor.py`
- `src/ml/model.py`
- `src/ml/model_registry.py`
- `src/ml/river_online_learning.py`

## 6. Training Paths

**Status:** aktif

Yang sudah ada:

- scheduled / manual full retrain path
- drift-triggered online learning path
- planner full-training dengan quality profile dan time budget
- training metadata persistence
- version persistence ke registry
- rejection jika accuracy di bawah threshold

Catatan:

- full retrain membuat persisted version baru
- online learning tidak membuat version baru dan dipakai untuk adaptasi cepat
- halaman ML Training sekarang membaca planner backend, bukan lagi sekadar tombol train sederhana

File utama:

- `src/ml/trainer.py`
- `src/ml/predictor.py`
- `scripts/train_model.py`

## 7. Model Intelligence

**Status:** aktif

Yang sudah ada:

- daftar model versions
- training history
- per-version metrics
- drift status
- River online stats
- recent prediction logs
- compatibility endpoint untuk path lama dan baru

File utama:

- `src/api/routes_models.py`
- `frontend/src/pages/ModelIntelligence.jsx`

## 8. Realtime Simulation

**Status:** aktif

Yang sudah ada:

- realtime session start / status / stop / SSE stream
- virtual API nodes
- L1/L2/KMS request path trace
- baseline direct KMS pada stream yang sama
- per-key accuracy
- drift score dan River stats
- cache origin proof
- latency breakdown per path

File utama:

- `src/api/live_simulation_service.py`
- `frontend/src/components/LiveSimulationDashboard.jsx`
- `frontend/src/pages/Simulation.jsx`
- `docs/realtime_simulation.md`

## 9. Frontend Product Surface

**Status:** aktif

Halaman yang ada sekarang:

- Overview
- Dashboard
- Simulation
- ML Training
- Model Intelligence
- Security Testing

Catatan:

- simulation sekarang realtime-only
- pipeline page bukan jalur utama lagi

File utama:

- `frontend/src/App.jsx`
- `frontend/src/pages/`
- `frontend/src/components/`

## 10. Database Persistence

**Status:** aktif

Yang sudah ada:

- SQLite default
- `ModelVersion`, `ModelMetric`, `TrainingMetadata`, `PredictionLog`, dan tabel pendukung
- path database sekarang lintas platform via settings
- startup compatibility repair untuk additive schema drift penting pada SQLite lama

File utama:

- `src/database/models.py`
- `src/database/connection.py`
- `config/settings.py`

## 11. Observability

**Status:** aktif dasar

Yang sudah ada:

- runtime metrics endpoint
- Prometheus exporter
- Model Intelligence query layer
- realtime simulation observability

File utama:

- `src/observability/prometheus_exporter.py`
- `src/observability/enhanced_observability.py`
- `src/api/routes_observability.py`

## 12. Docker and Operations

**Status:** aktif

Yang sudah ada:

- compose stack untuk frontend, api, redis, prefetch-worker
- monitoring profile untuk Prometheus dan Grafana
- smoke runtime script
- env example yang sesuai path DB sekarang

File utama:

- `docker-compose.yml`
- `config/prometheus.yml`
- `.env.example`
- `scripts/smoke_backend_runtime.py`

## Ringkasan Singkat

Kalau disederhanakan:

- **yang sudah kuat:** backend runtime, secure cache, prefetch worker, model registry, realtime simulation, model intelligence
- **yang sudah ada tapi masih bisa dimatangkan:** observability historis, ops tooling, governance lintas environment, deployment profile production

Kalau Anda ingin tahu apa yang harus dibangun setelah ini, lanjut ke [feature_roadmap.md](feature_roadmap.md).
