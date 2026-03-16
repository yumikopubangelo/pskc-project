# Dokumentasi Lengkap Fitur PSKC

Dokumen ini menjelaskan secara komprehensif semua fitur, fitur keamanan, dan machine learning yang tersedia di proyek PSKC (Predictive Secure Key Caching).

## Daftar Isi

1. [Ringkasan Proyek](#ringkasan-proyek)
2. [Fitur Utama](#fitur-utama)
3. [Fitur Keamanan](#fitur-keamanan)
4. [Fitur Machine Learning](#fitur-machine-learning)
5. [Arsitektur Sistem](#arsitektur-sistem)
6. [Endpoint API](#endpoint-api)
7. [Konfigurasi](#konfigurasi)

---

## Ringkasan Proyek

PSKC adalah proyek riset dan implementasi untuk menurunkan latensi autentikasi di arsitektur mikroservis dengan menyimpan material kunci secara lokal, terenkripsi, dan dapat dipanaskan terlebih dahulu (prefetch) berdasarkan pola akses.

**Tujuan Utama:**
- Mengurangi latensi autentikasi dengan caching kunci secara lokal
- Menyimpan kunci secara aman dengan enkripsi AES-256-GCM
- Memprediksi pola akses kunci untuk prefetching cerdas
- Menyediakan audit trail yang tamper-evident

---

## Fitur Utama

### 1. Secure Cache System

Sistem cache hibrida dua tingkat (L1 dan L2):

| Komponen | File | Deskripsi |
|----------|------|------------|
| LocalCache | [`src/cache/local_cache.py`](src/cache/local_cache.py) | Cache in-process dengan TTL dan eviction |
| RedisCache | [`src/cache/redis_cache.py`](src/cache/redis_cache.py) | Shared encrypted cache lintas proses |
| EncryptedStore | [`src/cache/encrypted_store.py`](src/cache/encrypted_store.py) | Enkripsi/dekripsi transparan |
| CachePolicy | [`src/cache/cache_policy.py`](src/cache/cache_policy.py) | TTL dinamis dan metadata hot/warm/cold |

**Fitur:**
- Two-tier caching (L1: Local, L2: Redis)
- Enkripsi data cache dengan AES-256-GCM
- Kebijakan TTL dinamis berdasarkan pola akses
- Metadata hot/warm/cold untuk optimasi

### 2. API dan Backend

FastAPI-based REST API dengan endpoint untuk:

| Endpoint | Method | Deskripsi |
|----------|--------|-----------|
| `/health` | GET | Health check sederhana |
| `/keys/access` | POST | Ambil kunci dari cache |
| `/keys/store` | POST | Simpan kunci ke cache terenkripsi |
| `/keys/invalidate` | POST | Invalidasi kunci dari cache |
| `/metrics` | GET | Ringkasan metrik backend |
| `/metrics/prefetch` | GET | Status queue prefetch Redis |
| `/metrics/prometheus` | GET | Exporter Prometheus |

Lihat [`src/api/routes.py`](src/api/routes.py) untuk detail lengkap.

### 3. Prefetch Worker

Worker terpisah untuk prefetch kunci berdasarkan prediksi:

| File | Deskripsi |
|------|------------|
| [`src/workers/prefetch_worker.py`](src/workers/prefetch_worker.py) | Worker utama untuk memproses job prefetch |
| [`src/prefetch/queue.py`](src/prefetch/queue.py) | Manajemen queue Redis untuk prefetch |

**Fitur:**
- Retry dengan backoff eksponensial
- Dead Letter Queue (DLQ) untuk job gagal
- Integrasi dengan Redis queue

### 4. Observability dan Monitoring

| Komponen | File | Deskripsi |
|----------|------|------------|
| PrometheusExporter | [`src/observability/prometheus_exporter.py`](src/observability/prometheus_exporter.py) | Ekspor metrik untuk Prometheus |
| MetricsPersistence | [`src/observability/metrics_persistence.py`](src/observability/metrics_persistence.py) | Penyimpanan metrik historis |

### 5. Simulation Engine

Engine simulasi untuk benchmarking dan pengujian dengan studi kasus Indonesia:

| Skenario | File | Fokus |
|----------|------|-------|
| SIAKAD SSO | `simulation/scenarios/siakad_sso.py` | Portal Akademik PT (single tenant), peak KRS/UAS |
| SEVIMA Siakadcloud | `simulation/scenarios/sevima_cloud.py` | Multi-tenant cloud, >900 PT Indonesia |
| PDDikti | `simulation/scenarios/pddikti_auth.py` | Skala nasional, >4.900 PT, 9.6 juta mahasiswa |
| Dynamic Production | `simulation/scenarios/dynamic_production.py` | Perubahan beban kerja dinamis |
| Cold Start | `simulation/engines/cold_start_simulator.py` | Evolusi ML warmup ke mature dengan EWMA concept drift |

Lihat [`simulation/runner.py`](simulation/runner.py) untuk menjalankan simulasi.

---

## Fitur Keamanan

### 1. Kriptografi

#### AES-256-GCM Encryption
- **File:** [`src/security/fips_module.py`](src/security/fips_module.py)
- **Status:** Aktif
- **Detail:** Nonce 96-bit dihasilkan secara acak menggunakan `secrets.token_bytes(12)`

#### HKDF Key Derivation
- **File:** [`src/security/fips_module.py`](src/security/fips_module.py)
- **Status:** Aktif
- **Detail:** Master key di-derive dari `CACHE_ENCRYPTION_KEY` menggunakan HKDF

#### FIPS Power-On Self-Tests
- **File:** [`src/security/fips_self_tests.py`](src/security/fips_self_tests.py)
- **Status:** Aktif by default
- **Detail:** Menjalankan KAT (Known Answer Test) dan fungsi dasar saat startup

### 2. Audit dan Logging

#### Tamper-Evident Logger
- **File:** [`src/security/tamper_evident_logger.py`](src/security/tamper_evident_logger.py)
- **Status:** Aktif secara desain
- **Detail:** Menggunakan hash chain dan signature berbasis boundary crypto

#### Security Audit
- **File:** [`src/security/security_audit.py`](src/security/security_audit.py)
- **Status:** Aktif
- **Detail:** Audit trail lengkap untuk operasi keamanan

### 3. HTTP Security

#### Security Headers Middleware
- **File:** [`src/security/security_headers.py`](src/security/security_headers.py)
- **Status:** Aktif by default
- **Fitur:**
  - HSTS (HTTP Strict Transport Security)
  - CSP (Content Security Policy)
  - Request size limit
  - Host validation
  - Path traversal guard

#### Rate Limiter
- **File:** [`src/security/security_headers.py`](src/security/security_headers.py)
- **Status:** Aktif by default
- **Detail:** Sliding window rate limiter dengan konfigurasi `HTTP_RATE_LIMIT_*`

### 4. Access Control

#### Trusted Proxy Handling
- **File:** [`src/api/routes.py`](src/api/routes.py)
- **Status:** Aktif
- **Detail:** Ekstraksi IP yang sadar trusted proxy, `X-Forwarded-For` tidak dipercaya dari sembarang source

#### Access Control
- **File:** [`src/security/access_control.py`](src/security/access_control.py)
- **Status:** Aktif
- **Detail:** Kontrol akses berbasis role dan permission

### 5. Intrusion Detection System (IDS)

- **File:** [`src/security/intrusion_detection.py`](src/security/intrusion_detection.py)
- **Status:** Aktif dasar
- **Fitur:**
  - Reputation gate
  - Rate check
  - Nonce reuse guard
  - Cache poisoning heuristics
  - Alert buffer

### 6. Model Security

#### Checksum Verification
- **File:** [`src/ml/model_registry.py`](src/ml/model_registry.py)
- **Status:** Aktif
- **Detail:** `checksums.json` wajib untuk load model

#### Metadata Signing dan Provenance
- **File:** [`src/ml/model_registry.py`](src/ml/model_registry.py)
- **Status:** Aktif
- **Detail:** Versi model disign, stage/provenance dilacak

#### Blok .pkl Load
- **File:** [`src/ml/model_registry.py`](src/ml/model_registry.py)
- **Status:** Aktif
- **Detail:** Menolak unsafe deserialization

### 7. Secret Rotation

#### Encryption Key Rotation
- **File:** [`src/security/rotate_encryption_key.py`](src/security/rotate_encryption_key.py)
- **Status:** Tersedia
- **Detail:** Rotasi kunci enkripsi secara aman

#### Secret Rotation
- **File:** [`src/security/secret_rotation.py`](src/security/secret_rotation.py)
- **Status:** ✅ Aktif
- **Detail:** Rotasi secrets dengan grace period, atomicity, dan dual-key period untuk zero-downtime

#### Key Lifecycle Management
- **File:** [`src/security/key_lifecycle_manager.py`](src/security/key_lifecycle_manager.py)
- **Status:** ✅ Aktif - **Workflow Lengkap!**
- **Detail:** Unified workflow **create → rotate → revoke → expire** dengan:
  - Cache integration (auto invalidation on key changes)
  - Secure store integration
  - Automatic expiration dengan grace period
  - Lifecycle event hooks
  - Complete audit trail
  - Predefined workflows (create_rotate, rotate_revoke, create_expire, full_lifecycle)

### 8. Security Testing

- **File:** [`src/security/security_testing.py`](src/security/security_testing.py)
- **Status:** Aktif
- **Detail:** Suite pengujian keamanan komprehensif

---

## Fitur Machine Learning

### 1. Data Collection

#### Data Collector
- **File:** [`src/ml/data_collector.py`](src/ml/data_collector.py)
- **Status:** Online via API
- **Detail:** Merekam access event dan statistik key

### 2. Feature Engineering

#### Feature Engineer
- **File:** [`src/ml/feature_engineering.py`](src/ml/feature_engineering.py)
- **Status:** Aktif
- **Detail:** Membangun vector fitur temporal/statistik

### 3. Model Training

#### Model Trainer
- **File:** [`src/ml/trainer.py`](src/ml/trainer.py)
- **Status:** Online via API
- **Detail:** Training model dengan data historis

#### Ensemble Model
- **File:** [`src/ml/model.py`](src/ml/model.py)
- **Status:** Aktif - **sudah berjalan di runtime**
- **Detail:** Kombinasi **LSTM + RandomForest + Markov Chain** telah terintegrasi penuh dan aktif di jalur prediksi

### 4. Model Registry

#### Model Registry
- **File:** [`src/ml/model_registry.py`](src/ml/model_registry.py)
- **Status:** Aktif
- **Fitur:**
  - Versioning model
  - Active model management
  - Checksum verification
  - Metadata signing
  - Provenance tracking
  - Lifecycle management

### 5. Prediction

#### Key Predictor
- **File:** [`src/ml/predictor.py`](src/ml/predictor.py)
- **Status:** Online via API
- **Detail:** Top-N prediction dan prefetch helper

#### Online Learning (Concept Drift EWMA)
- **Status:** ✅ **Sudah Matang!**
- **Detail:** Implementasi online learning dengan Exponential Weighted Moving Average (EWMA) untuk menangani concept drift sudah matang dengan:
  - True EWMA implementation dengan adaptive windowing
  - ADWIN-like detection untuk perubahan distribusi mendadak
  - EDDM (Early Drift Detection Method) untuk akurasi
  - Weighted voting dari multiple detection methods
  - Endpoint `/ml/drift` untuk analisis lengkap

### 6. Evaluation

#### ML Evaluation
- **File:** [`src/ml/evaluation.py`](src/ml/evaluation.py)
- **Status:** Aktif
- **Detail:** Evaluasi performa model

### 7. Script Pendukung

| Script | File | Deskripsi |
|--------|------|------------|
| Generate Training Data | [`scripts/generate_training_data.py`](scripts/generate_training_data.py) | Generate data training dari skenario |
| Train Model | [`scripts/train_model.py`](scripts/train_model.py) | Training model ML |
| Benchmark | [`scripts/benchmark.py`](scripts/benchmark.py) | Benchmark baseline vs PSKC |
| Seed Data | [`scripts/seed_data.py`](scripts/seed_data.py) | Seed data sintetis |

### 8. Endpoint ML

| Endpoint | Method | Deskripsi |
|----------|--------|-----------|
| `/ml/status` | GET | Status runtime ML |
| `/ml/registry` | GET | Ringkasan registry model |
| `/ml/lifecycle` | GET | History lifecycle model |
| `/ml/promote` | POST | Promosikan versi model |
| `/ml/rollback` | POST | Rollback ke versi sebelumnya |
| `/ml/predictions` | GET | Prediksi kunci |
| `/ml/retrain` | POST | Retraining model |

---

## Arsitektur Sistem

```
request
  -> FastAPI router
    -> SecureCacheManager
      -> EncryptedCacheStore
        -> LocalCache (L1)
        -> RedisCache (L2)
        -> CachePolicyManager
        -> FipsCryptographicModule
        -> TamperEvidentAuditLogger
    -> KeyFetcher (hanya saat cache miss)
  -> PrefetchQueue (Redis)
    -> prefetch worker
```

### Flow Request: `/keys/access`

```
client
  -> routes.access_key()
    -> _extract_client_ip()
    -> SecureCacheManager.secure_get()
      -> IDS checks
      -> EncryptedCacheStore.get_with_metadata()
        -> LocalCache.get()
        -> fallback ke RedisCache jika L1 miss
        -> decrypt via FipsCryptographicModule
    -> jika miss: KeyFetcher.fetch_key()
    -> SecureCacheManager.secure_set()
    -> schedule Redis prefetch job
    -> KeyAccessResponse
```

---

## Endpoint API

### Health dan Metrics

| Method | Path | Deskripsi |
|--------|------|-----------|
| GET | `/health` | Health check sederhana |
| GET | `/metrics` | Ringkasan metrik backend |
| GET | `/metrics/prefetch` | Status queue prefetch Redis |
| GET | `/metrics/prometheus` | Exporter Prometheus |

### Key Operations

| Method | Path | Deskripsi |
|--------|------|-----------|
| POST | `/keys/access` | Ambil kunci dari cache |
| POST | `/keys/store` | Simpan kunci ke cache |
| POST | `/keys/invalidate` | Invalidasi kunci |

### ML Operations

| Method | Path | Deskripsi |
|--------|------|-----------|
| GET | `/ml/status` | Status runtime ML |
| GET | `/ml/registry` | Ringkasan registry model |
| GET | `/ml/lifecycle` | History lifecycle model |
| POST | `/ml/promote` | Promosikan versi model |
| POST | `/ml/rollback` | Rollback versi model |
| GET | `/ml/predictions` | Prediksi kunci |
| POST | `/ml/retrain` | Retraining model |

### Simulation Operations

| Method | Path | Deskripsi |
|--------|------|-----------|
| GET | `/simulation/scenarios` | Katalog skenario simulasi |
| POST | `/simulation/run` | Jalankan simulasi |
| GET | `/simulation/results/{id}` | Ambil hasil simulasi |

### Prefetch Operations

| Method | Path | Deskripsi |
|--------|------|-----------|
| GET | `/prefetch/dlq` | Lihat job prefetch di DLQ |

---

## Konfigurasi

### Variabel Lingkungan Utama

| Variable | Fungsi |
|----------|--------|
| `APP_ENV` | Mode aplikasi (`development` atau `production`) |
| `APP_PORT` | Port FastAPI |
| `FIPS_SELF_TEST_ENABLED` | Toggle untuk self-test kriptografi |
| `TRUSTED_PROXIES` | Daftar CIDR proxy tepercaya |
| `AUDIT_LOG_DIRECTORY` | Direktori root audit log |
| `CACHE_ENCRYPTION_KEY` | Material awal untuk derivasi master key |
| `CACHE_TTL_SECONDS` | TTL default cache |
| `CACHE_MAX_SIZE` | Kapasitas maksimum cache in-memory |
| `HTTP_SECURITY_*` | Toggle dan tuning middleware header hardening |
| `HTTP_RATE_LIMIT_*` | Tuning rate limiter |
| `ML_MODEL_NAME` | Nama logical model di registry aktif |
| `ML_MODEL_REGISTRY_DIR` | Direktori registry model |
| `ML_MODEL_STAGE` | Stage default artefak model baru |
| `ML_MODEL_SIGNING_KEY` | Secret untuk signing metadata model |
| `ML_PREDICTION_THRESHOLD` | Threshold prediksi |
| `REDIS_*` | Konfigurasi Redis |

---

## Referensi

- [README.md](../README.md) - Ringkasan proyek
- [docs/architecture.md](architecture.md) - Arsitektur detail
- [docs/security_model.md](security_model.md) - Model keamanan
- [docs/simulation_and_ml.md](simulation_and_ml.md) - Simulasi dan ML
- [docs/api_reference.md](api_reference.md) - Referensi API
- [docs/operations.md](operations.md) - Operasi dan deployment
