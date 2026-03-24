# Fitur PSKC yang Sudah Selesai

Dokumen ini adalah inventaris fitur yang **sudah diimplementasikan dan aktif** di codebase PSKC.
Untuk backlog fitur yang masih perlu dikerjakan, lihat [`feature_roadmap.md`](feature_roadmap.md).

---

## Daftar Isi

1. [Cache System](#1-cache-system)
2. [Kriptografi & Enkripsi](#2-kriptografi--enkripsi)
3. [HTTP Security & Middleware](#3-http-security--middleware)
4. [Intrusion Detection System](#4-intrusion-detection-system)
5. [Access Control](#5-access-control)
6. [Key Lifecycle & Secret Rotation](#6-key-lifecycle--secret-rotation)
7. [Audit & Logging](#7-audit--logging)
8. [Machine Learning — Model & Prediksi](#8-machine-learning--model--prediksi)
9. [Machine Learning — Training Pipeline](#9-machine-learning--training-pipeline)
10. [Machine Learning — Online Learning (River)](#10-machine-learning--online-learning-river)
11. [Machine Learning — Registry & Governance](#11-machine-learning--registry--governance)
12. [Data Collection & Feature Engineering](#12-data-collection--feature-engineering)
13. [Drift Detection](#13-drift-detection)
14. [Prefetch System](#14-prefetch-system)
15. [Observability & Metrics](#15-observability--metrics)
16. [Real-time Training Progress](#16-real-time-training-progress)
17. [Simulation Engine](#17-simulation-engine)
18. [API Routes](#18-api-routes)
19. [Admin Control Plane](#19-admin-control-plane)
20. [Database & Repository](#20-database--repository)
21. [Frontend Production](#21-frontend-production)
22. [Runtime & Bootstrap](#22-runtime--bootstrap)
23. [Arsitektur Sistem](#23-arsitektur-sistem)
24. [Konfigurasi](#24-konfigurasi)

---

## 1. Cache System

Sistem cache hibrida dua tingkat (L1 in-process + L2 Redis terenkripsi).

| Komponen | File | Status |
|----------|------|--------|
| LocalCache | [`src/cache/local_cache.py`](src/cache/local_cache.py) | ✅ Aktif |
| RedisCache | [`src/cache/redis_cache.py`](src/cache/redis_cache.py) | ✅ Aktif |
| EncryptedCacheStore | [`src/cache/encrypted_store.py`](src/cache/encrypted_store.py) | ✅ Aktif |
| CachePolicyManager | [`src/cache/cache_policy.py`](src/cache/cache_policy.py) | ✅ Aktif |

**Fitur:**
- Two-tier caching: L1 thread-safe LRU in-memory, L2 Redis shared lintas proses
- Enkripsi transparan AES-256-GCM di semua layer
- TTL dinamis berbasis pola akses (hot / warm / cold metadata)
- Eviction cleanup thread otomatis
- Tracking metadata per-entry (access count, last accessed, cache tier)
- Failure handling dan backoff untuk L2 Redis

---

## 2. Kriptografi & Enkripsi

| Komponen | File | Status |
|----------|------|--------|
| FipsCryptographicModule | [`src/security/fips_module.py`](src/security/fips_module.py) | ✅ Aktif |
| FIPS Self-Tests | [`src/security/fips_self_tests.py`](src/security/fips_self_tests.py) | ✅ Aktif saat startup |

**Fitur:**
- **AES-256-GCM** dengan nonce 96-bit random (`secrets.token_bytes(12)`)
- **HKDF** key derivation dari `CACHE_ENCRYPTION_KEY` → master key
- **PBKDF2** support untuk key derivation alternatif
- **FIPS Power-On Self-Tests (KAT)** — Known Answer Test dijalankan saat startup
- Validasi integritas kriptografi sebelum operasi cache dimulai

---

## 3. HTTP Security & Middleware

| Komponen | File | Status |
|----------|------|--------|
| SecurityHeadersMiddleware | [`src/security/security_headers.py`](src/security/security_headers.py) | ✅ Aktif |
| SlidingWindowRateLimiter | [`src/security/security_headers.py`](src/security/security_headers.py) | ✅ Aktif |

**Fitur:**
- **HSTS** (HTTP Strict Transport Security)
- **CSP** (Content Security Policy)
- Request size limit (konfigurasi via `HTTP_SECURITY_*`)
- Host validation — tolak request dengan Host header tidak dikenali
- Path traversal guard
- Trusted proxy handling (`X-Forwarded-For` hanya dipercaya dari CIDR yang terdaftar)
- Sliding window rate limiter dengan konfigurasi `HTTP_RATE_LIMIT_*`

---

## 4. Intrusion Detection System

| Komponen | File | Status |
|----------|------|--------|
| IntrusionDetectionSystem | [`src/security/intrusion_detection.py`](src/security/intrusion_detection.py) | ✅ Aktif |
| SecureCacheManager | [`src/security/`](src/security/) | ✅ Aktif |

**Fitur:**
- **Reputation gate** — IP dengan reputasi buruk diblokir di awal
- **Rate check** — deteksi burst request mencurigakan
- **Nonce reuse guard** — tolak request dengan nonce yang sudah dipakai
- **Cache poisoning heuristics** — deteksi pola yang menyerupai cache poisoning
- Alert buffer dengan threshold yang dapat dikonfigurasi
- SecureCacheManager mengorkestrasikan semua IDS check sebelum akses cache

---

## 5. Access Control

| Komponen | File | Status |
|----------|------|--------|
| Access Control | [`src/security/access_control.py`](src/security/access_control.py) | ✅ Aktif |

**Fitur:**
- Role-based access control (RBAC)
- Permission-based access control (PBAC)
- Integrasi dengan request path `/keys/access`

---

## 6. Key Lifecycle & Secret Rotation

| Komponen | File | Status |
|----------|------|--------|
| KeyLifecycleManager | [`src/security/key_lifecycle_manager.py`](src/security/key_lifecycle_manager.py) | ✅ Aktif |
| SecretRotation | [`src/security/secret_rotation.py`](src/security/secret_rotation.py) | ✅ Aktif |
| RotateEncryptionKey | [`src/security/rotate_encryption_key.py`](src/security/rotate_encryption_key.py) | ✅ Tersedia |

**Workflow lengkap: `create → rotate → revoke → expire`**

**Fitur:**
- **Zero-downtime rotation** dengan grace period — kunci lama tetap valid selama masa transisi
- **Dual-key validation window** — request yang sedang berjalan tidak terganggu rotasi
- **Atomik invalidasi** lintas L1 dan L2 cache
- **Automatic expiration** dengan grace period yang dapat dikonfigurasi
- **Lifecycle event hooks** — callback saat setiap transisi state
- Predefined workflows: `create_rotate`, `rotate_revoke`, `create_expire`, `full_lifecycle`
- Integrasi penuh dengan tamper-evident audit logger
- Cache integration: auto-invalidation saat kunci berubah
- Integrasi dengan secure store

---

## 7. Audit & Logging

| Komponen | File | Status |
|----------|------|--------|
| TamperEvidentAuditLogger | [`src/security/tamper_evident_logger.py`](src/security/tamper_evident_logger.py) | ✅ Aktif |
| SecurityAudit | [`src/security/security_audit.py`](src/security/security_audit.py) | ✅ Aktif |
| SecurityTesting | [`src/security/security_testing.py`](src/security/security_testing.py) | ✅ Aktif |

**Fitur:**
- **Hash chain logging** — setiap entri audit terikat ke entri sebelumnya
- **HMAC signature** per entri untuk verifikasi integritas
- Audit trail lengkap untuk semua operasi keamanan dan lifecycle key
- Semua admin action di-log secara otomatis
- Resistance terhadap tampering (pendeteksian modifikasi retroaktif)

---

## 8. Machine Learning — Model & Prediksi

| Komponen | File | Status |
|----------|------|--------|
| EnsembleModel | [`src/ml/model.py`](src/ml/model.py) | ✅ Aktif di runtime |
| MarkovChainPredictor | [`src/ml/model.py`](src/ml/model.py) | ✅ Aktif |
| EnsembleWeightTracker | [`src/ml/model.py`](src/ml/model.py) | ✅ Aktif |
| KeyPredictor | [`src/ml/predictor.py`](src/ml/predictor.py) | ✅ Aktif |

**Arsitektur ensemble 3 model:**

| Model | Peran | Bobot |
|-------|-------|-------|
| Random Forest | Batch model utama, generalisasi stabil | Dinamis |
| LSTM | Temporal model (catatan: saat ini menerima input tabular, bukan sekuensial — lihat roadmap) | Dinamis |
| Markov Chain | Sequential pattern, zero cold-start, O(1) prediction | 20% (statis) |

**Fitur:**
- Dynamic weight adjustment berbasis sliding-window accuracy per model (RF dan LSTM)
- Markov Chain dengan Laplace smoothing untuk key yang belum pernah dilihat
- Memory-bounded Markov: `max_transitions` dengan pruning otomatis
- `EnsembleWeightTracker` — softmax normalization bobot berdasarkan akurasi terbaru
- `KeyPredictor` menyediakan top-N prediction untuk prefetch
- Cache prediksi per model version

---

## 9. Machine Learning — Training Pipeline

| Komponen | File | Status |
|----------|------|--------|
| ModelTrainer | [`src/ml/trainer.py`](src/ml/trainer.py) | ✅ Aktif |
| DataBalancer | [`src/ml/model_improvements.py`](src/ml/model_improvements.py) | ✅ Aktif |
| FeatureSelector | [`src/ml/model_improvements.py`](src/ml/model_improvements.py) | ✅ Aktif |
| DataAugmenter | [`src/ml/model_improvements.py`](src/ml/model_improvements.py) | ✅ Aktif |
| FeatureNormalizer | [`src/ml/model_improvements.py`](src/ml/model_improvements.py) | ✅ Aktif |
| HyperparameterTuner | [`src/ml/trainer.py`](src/ml/trainer.py) | ✅ Aktif |

**Dua jalur training:**

| Jalur | Trigger | Window Data | Tujuan |
|-------|---------|-------------|--------|
| Scheduled | 24 jam | 50K event | Full retraining, generalisasi luas |
| Automatic | Drift detected | 5K event (1 jam) | Adaptasi cepat terhadap perubahan |

**Pipeline training (10 tahap):**
1. Load data dari DataCollector
2. Feature extraction (context_window = 10 event sebelumnya)
3. Feature normalization (StandardScaler)
4. Feature selection (SelectKBest, k adaptif 10–25)
5. Data augmentation (noise, scaling, mixup — 30% factor)
6. Data balancing (SMOTE-inspired class rebalancing)
7. Train/val split (70/30 temporal)
8. Model training (ensemble.fit)
9. Validation evaluation (top-1 dan top-10 accuracy)
10. Model persistence dengan version tracking

---

## 10. Machine Learning — Online Learning (River)

| Komponen | File | Status |
|----------|------|--------|
| RiverOnlineLearner | [`src/ml/river_online_learning.py`](src/ml/river_online_learning.py) | ✅ Terimplementasi |
| RiverEnsemble | [`src/ml/river_online_learning.py`](src/ml/river_online_learning.py) | ✅ Terimplementasi |

**Model River yang tersedia:**
- **SRPClassifier** (Streaming Random Patches) — default, menggantikan AdaptiveRandomForest di River ≥0.19
- **HoeffdingTreeClassifier** — memory-efficient incremental decision tree
- **LogisticRegression Pipeline** — StandardScaler → LogisticRegression via SGD

**Fitur:**
- `partial_fit()` — one-sample-at-a-time learning
- ADWIN drift detection terintegrasi di dalam River
- `predict_proba()` output untuk ensemble integration
- `RiverEnsemble` wrapper yang menggabungkan River dengan RF dan Markov

**Catatan:** River saat ini dilatih dan tersimpan tetapi belum sepenuhnya terhubung ke jalur prediksi utama `predict_top_n()`. Ini adalah salah satu item prioritas kritis di [feature_roadmap.md](feature_roadmap.md).

---

## 11. Machine Learning — Registry & Governance

| Komponen | File | Status |
|----------|------|--------|
| ModelRegistry | [`src/ml/model_registry.py`](src/ml/model_registry.py) | ✅ Aktif |
| IncrementalModelPersistence | [`src/ml/incremental_model.py`](src/ml/incremental_model.py) | ✅ Aktif |

**Fitur:**
- Versioning model dengan file tunggal `incremental_model.pskc.json`
- **Checksum verification** — `checksums.json` wajib saat load model
- **Metadata signing** — setiap versi model di-sign, stage/provenance dilacak
- **Blok unsafe deserialization** — file `.pkl` ditolak
- Safe checkpoint restore dengan OOV (out-of-vocabulary) handling
- Promotion dan rollback antar stage: `development → staging → production`
- Lifecycle log per model version
- Acceptance criteria: model baru hanya diterima jika akurasi ≥ previous + `min_improvement`
- History 100 entri training tersimpan di artefak model

---

## 12. Data Collection & Feature Engineering

| Komponen | File | Status |
|----------|------|--------|
| DataCollector | [`src/ml/data_collector.py`](src/ml/data_collector.py) | ✅ Aktif |
| FeatureEngineering | [`src/ml/feature_engineering.py`](src/ml/feature_engineering.py) | ✅ Aktif |
| PatternAnalyzer | [`src/ml/pattern_analyzer.py`](src/ml/pattern_analyzer.py) | ✅ Aktif |
| AutoRetrainer | [`src/ml/auto_retrainer.py`](src/ml/auto_retrainer.py) | ✅ Aktif |

**30 fitur yang diekstrak:**

| Kategori | Jumlah | Contoh |
|----------|--------|--------|
| Temporal | 8 | Hour sin/cos, day sin/cos, recent freq ratio, time since last |
| Pattern | 6 | Cache hit rate, key diversity, burst ratio, sequence entropy |
| Service | 4 | Unique services, dominant service ratio, service entropy |
| Latency | 6 | Mean, median, P95, P99, std dev, skewness |
| Frequency | 6 | Total count, normalisasi, Zipfian fit, peak ratio, recency |

**Fitur data pipeline:**
- Redis shared storage untuk event queue (25K recent + 50K total)
- Periodic flush setiap 50 event untuk reduce lock contention
- Thread-safe snapshot selama serialisasi
- Data validation: non-empty key, negative latency correction, access type enforcement
- Memory management: TTL-based cleanup, max entries dengan 80% pruning
- **PatternAnalyzer** — analisis divergensi pola (JS divergence, Jaccard, latency change)
- **AutoRetrainer** — keputusan retraining otomatis berbasis drift score dan confidence

---

## 13. Drift Detection

| Komponen | File | Status |
|----------|------|--------|
| DriftDetector | [`src/ml/trainer.py`](src/ml/trainer.py) | ✅ Aktif |

**Tiga metode deteksi dengan ensemble voting:**

| Metode | Cara Kerja | Threshold |
|--------|-----------|-----------|
| EWMA | Short-term (α=0.3) vs long-term (α=0.15) exponential smoothing | Drop >12% = drift, >6% = warning |
| ADWIN-like | Welch's t-test antara old vs new half dari adaptive window | t > 2.0 = drift |
| EDDM | Jarak antar error berurutan via Welford's algorithm | Statistical threshold |

**Keputusan:**
- Drift score ≥ 2 vote → `"drift"` (trigger retraining)
- Warning score ≥ 1 → `"warning"` (log & monitor)
- Lainnya → `"ok"` (stabil)

**Fitur:**
- History 100 drift event tersimpan
- Per-method statistik (drops, thresholds, confidence)
- Drift trend analysis (increasing / decreasing / stable)
- Reset short window setelah retrain untuk mencegah re-trigger

---

## 14. Prefetch System

| Komponen | File | Status |
|----------|------|--------|
| PrefetchQueue | [`src/prefetch/queue.py`](src/prefetch/queue.py) | ✅ Aktif |
| PrefetchWorker | [`src/workers/prefetch_worker.py`](src/workers/prefetch_worker.py) | ✅ Aktif |

**Fitur:**
- Redis-backed job queue dengan FIFO ordering
- Retry dengan exponential backoff
- **Dead Letter Queue (DLQ)** untuk job gagal
- Rate limiting (token bucket algorithm)
- Worker heartbeat tracking
- Event recording per job
- Adaptive rate limiting berbasis system load
- Failure classification untuk smart retry logic
- Integrasi dengan `ML predictor` untuk memicu prefetch dari prediksi

---

## 15. Observability & Metrics

| Komponen | File | Status |
|----------|------|--------|
| MetricsPersistence | [`src/observability/metrics_persistence.py`](src/observability/metrics_persistence.py) | ✅ Aktif |
| PrometheusExporter | [`src/observability/prometheus_exporter.py`](src/observability/prometheus_exporter.py) | ✅ Aktif |

**Metrics yang dipersist ke Redis:**
- Request count, cache hit rate, latency histogram
- ML training metrics (accuracy, sample count, training time)
- Drift events (timestamp, metode, score)
- Model lifecycle events (promote, rollback, training)
- Key rotation events
- Retention default: 24 jam

**Prometheus endpoint:** `/metrics/prometheus`

---

## 16. Real-time Training Progress

| Komponen | File | Status |
|----------|------|--------|
| TrainingProgressTracker | [`src/api/training_progress.py`](src/api/training_progress.py) | ✅ Aktif |

**Fitur:**
- Tracking fase training secara real-time (10 fase: load → preprocess → balance → augment → train → evaluate → persist)
- Persentase progress per fase
- Persisted ke Redis untuk akses lintas proses
- WebSocket support untuk streaming ke frontend
- History training tersimpan

---

## 17. Simulation Engine

| Skenario | File | Status |
|----------|------|--------|
| Enhanced Simulation | [`simulation/enhanced_simulation.py`](simulation/enhanced_simulation.py) | ✅ Selesai |
| Enhanced Simulation v2 | [`simulation/enhanced_simulation_v2.py`](simulation/enhanced_simulation_v2.py) | ✅ Selesai |
| PSKC Fast Comparison | [`simulation/pskc_comparison_fast.py`](simulation/pskc_comparison_fast.py) | ✅ Selesai |
| SIAKAD SSO | [`simulation/scenarios/siakad_sso.py`](simulation/scenarios/siakad_sso.py) | ✅ Selesai |
| SEVIMA Siakadcloud | [`simulation/scenarios/sevima_cloud.py`](simulation/scenarios/sevima_cloud.py) | ✅ Selesai |
| PDDikti | [`simulation/scenarios/pddikti_auth.py`](simulation/scenarios/pddikti_auth.py) | ✅ Selesai |
| Dynamic Production | [`simulation/scenarios/dynamic_production.py`](simulation/scenarios/dynamic_production.py) | ✅ Selesai |
| Cold Start | [`simulation/engines/cold_start_simulator.py`](simulation/engines/cold_start_simulator.py) | ✅ Selesai |

**Hasil benchmark saat ini:**
- Latency improvement: **61.6%** (21.3ms → 8.2ms rata-rata)
- Cache hit rate: **93.1%** (+13.8% dari baseline)
- KMS fetch reduction: **100%** (602 → 0 per 1000 request)
- Prefetch worker success rate: **96.5%**
- P99 latency: **8.5%** improvement

**Fitur engine:**
- Detailed request path tracing (L1→L2→ML→KMS visualization)
- Persistent L1/L2 cache antar request
- Log-normal KMS latency distribution (realistic)
- Pareto access pattern (80/20 rule)
- ML transition learning selama simulasi
- Side-by-side comparison PSKC vs baseline dengan 7-section report

---

## 18. API Routes

Modular 11 route file, semua teregistrasi di [`src/api/routes.py`](src/api/routes.py).

| Route Module | File | Endpoint Utama |
|-------------|------|----------------|
| Health | [`src/api/route_health.py`](src/api/route_health.py) | `/health`, `/ready`, `/startup` |
| Keys | [`src/api/route_keys.py`](src/api/route_keys.py) | `/keys/access`, `/keys/store`, `/keys/invalidate` |
| Metrics | [`src/api/route_metrics.py`](src/api/route_metrics.py) | `/metrics`, `/metrics/cache-distribution`, `/metrics/latency`, `/metrics/accuracy` |
| ML | [`src/api/route_ml.py`](src/api/route_ml.py) | `/ml/status`, `/ml/registry`, `/ml/promote`, `/ml/rollback`, `/ml/predictions`, `/ml/retrain`, `/ml/drift` |
| Training | [`src/api/route_training.py`](src/api/route_training.py) | `/ml/train/progress`, `/ml/train/start`, `/ml/train/stop`, `/ml/train/history` |
| Simulation | [`src/api/route_simulation.py`](src/api/route_simulation.py) | `/simulation/scenarios`, `/simulation/run`, `/simulation/results`, `/simulation/validate`, `/simulation/live` |
| Prefetch | [`src/api/route_prefetch.py`](src/api/route_prefetch.py) | `/prefetch/dlq`, `/prefetch/replay` |
| Security Lifecycle | [`src/api/route_security_lifecycle.py`](src/api/route_security_lifecycle.py) | Key rotation dan lifecycle API |
| Admin Pipeline | [`src/api/route_admin_pipeline.py`](src/api/route_admin_pipeline.py) | Admin control plane dan pipeline management |

**Schemas:** [`src/api/schemas.py`](src/api/schemas.py) — Pydantic models untuk semua request/response.

---

## 19. Admin Control Plane

| Komponen | File | Status |
|----------|------|--------|
| AdminControlPlane | [`src/api/admin_control_plane.py`](src/api/admin_control_plane.py) | ✅ Aktif |

**Role levels:** Observer, Operator, Admin

**Endpoint yang tersedia:**

| Grup | Endpoint | Deskripsi |
|------|----------|-----------|
| Auth | `GET /admin/auth/status` | Status sistem auth admin |
| Auth | `GET /admin/auth/audit` | Audit log semua admin action |
| Cache | `GET /admin/cache/summary` | Summary per service |
| Cache | `POST /admin/cache/invalidate` | Invalidate by prefix |
| Cache | `GET /admin/cache/ttl/{key_id}` | Inspect TTL |
| Cache | `GET/POST /admin/cache/warmup` | Warmup status dan trigger |
| Model | `GET /admin/model/versions` | Versi per stage |
| Model | `GET /admin/model/history/{name}` | Version history |
| Model | `GET /admin/model/compare` | Bandingkan dua versi |
| Model | `GET /admin/model/export/{name}` | Export lifecycle summary |
| Security | `GET /admin/security/summary` | Intrusion summary |
| Security | `GET /admin/security/blocked-ips` | Daftar IP yang diblokir |
| Security | `GET /admin/security/reputation` | IP reputation overview |
| Security | `POST /admin/security/unblock` | Unblock IP |
| Security | `GET /admin/security/audit-recovery` | Audit recovery history |

---

## 20. Database & Repository

| Komponen | File | Status |
|----------|------|--------|
| SQLAlchemy Models | [`src/database/models.py`](src/database/models.py) | ✅ Aktif |
| Database Connection | [`src/database/connection.py`](src/database/connection.py) | ✅ Aktif |
| Repository | [`src/database/repository.py`](src/database/repository.py) | ✅ Aktif |

**Tabel:**
- `SimulationEvent` — dengan indexing untuk query performa
- `RetrainingHistory` — riwayat setiap retraining event

**Migrasi:** Alembic tersedia di [`migrations/`](migrations/).

---

## 21. Frontend Production

| Komponen | File | Status |
|----------|------|--------|
| Production Dockerfile | [`frontend/Dockerfile.production`](frontend/Dockerfile.production) | ✅ Siap |
| Nginx Config | [`frontend/nginx.conf`](frontend/nginx.conf) | ✅ Siap |
| Vite Config | [`frontend/vite.config.js`](frontend/vite.config.js) | ✅ Konfigurasi production |
| API Client | [`frontend/src/utils/apiClient.js`](frontend/src/utils/apiClient.js) | ✅ Termasuk admin endpoints |

**Fitur:**
- Multi-stage Docker build: React build → nginx serve
- Static asset caching 1 tahun untuk immutable assets
- Gzip compression untuk text assets
- Security headers di level nginx
- API proxy: nginx forward `/api/` ke backend
- Content hashing untuk cache busting
- Semua admin endpoint tersedia di frontend API client
- Real-time training progress via WebSocket (DataGenerationProgress, TrainingProgress components)

---

## 22. Runtime & Bootstrap

| Komponen | File | Status |
|----------|------|--------|
| Bootstrap | [`src/runtime/bootstrap.py`](src/runtime/bootstrap.py) | ✅ Aktif |
| ML Service | [`src/api/ml_service.py`](src/api/ml_service.py) | ✅ Aktif |
| Simulation Service | [`src/api/simulation_service.py`](src/api/simulation_service.py) | ✅ Aktif |
| ML Worker | [`src/workers/ml_worker.py`](src/workers/ml_worker.py) | ✅ Aktif |

**Fitur bootstrap:**
- Dependency injection untuk semua komponen
- FIPS module initialization dan self-test
- Audit logger initialization
- Model registry initialization
- Graceful shutdown handling

---

## 23. Arsitektur Sistem

```
request
  → FastAPI router
    → SecurityHeadersMiddleware (HSTS, CSP, rate limit, host validation)
    → SecureCacheManager
      → IDS checks (reputation, rate, nonce, poisoning)
      → EncryptedCacheStore
        → LocalCache (L1, in-process LRU)
        → RedisCache (L2, shared encrypted)
        → CachePolicyManager (TTL dynamic)
        → FipsCryptographicModule (AES-256-GCM)
        → TamperEvidentAuditLogger (hash chain)
    → jika cache miss: KeyFetcher (KMS)
    → SecureCacheManager.secure_set()
    → enqueue Redis prefetch job
    → KeyAccessResponse

background:
  PrefetchWorker (async) → consumes prefetch queue → warms cache
  MLWorker (async) → handles online learning updates
  DriftDetector (per training cycle) → triggers auto-retraining
  AutoRetrainer → manages retraining decisions
```

### Flow `/keys/access`

```
client
  → route_keys.access_key()
    → _extract_client_ip() (trusted proxy aware)
    → SecureCacheManager.secure_get()
    → jika miss: KeyFetcher.fetch_key()
    → SecureCacheManager.secure_set()
    → schedule_prefetch_job()
    → KeyAccessResponse
```

---

## 24. Konfigurasi

### Variabel Lingkungan Utama

| Variable | Fungsi |
|----------|--------|
| `APP_ENV` | Mode aplikasi (`development` / `production`) |
| `APP_PORT` | Port FastAPI |
| `FIPS_SELF_TEST_ENABLED` | Toggle self-test kriptografi saat startup |
| `TRUSTED_PROXIES` | Daftar CIDR proxy tepercaya |
| `AUDIT_LOG_DIRECTORY` | Direktori root audit log |
| `CACHE_ENCRYPTION_KEY` | Material awal untuk derivasi master key |
| `CACHE_TTL_SECONDS` | TTL default cache |
| `CACHE_MAX_SIZE` | Kapasitas maksimum LocalCache |
| `HTTP_SECURITY_*` | Toggle dan tuning middleware header hardening |
| `HTTP_RATE_LIMIT_*` | Tuning rate limiter (window, max requests) |
| `ML_MODEL_NAME` | Nama logical model di registry |
| `ML_MODEL_REGISTRY_DIR` | Direktori registry model |
| `ML_MODEL_STAGE` | Stage default artefak model baru |
| `ML_MODEL_SIGNING_KEY` | Secret untuk signing metadata model |
| `ML_PREDICTION_THRESHOLD` | Threshold confidence untuk prediksi |
| `REDIS_HOST` | Redis hostname |
| `REDIS_PORT` | Redis port |
| `REDIS_PASSWORD` | Redis password |
| `REDIS_DB` | Redis database index |
| `ADMIN_API_KEY` | API key untuk admin endpoint |

---

## Dokumen Terkait

- [feature_roadmap.md](feature_roadmap.md) — Backlog fitur yang belum dikerjakan
- [project_status.md](project_status.md) — Ringkasan status proyek
- [architecture.md](architecture.md) — Arsitektur detail
- [api_reference.md](api_reference.md) — Referensi endpoint lengkap
- [security_model.md](security_model.md) — Model keamanan
- [simulation_and_ml.md](simulation_and_ml.md) — Detail ML dan simulasi
- [operations.md](operations.md) — Panduan operasional
