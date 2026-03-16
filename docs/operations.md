# Operations Guide

Dokumen ini merangkum aspek konfigurasi, Docker, observability, dan catatan deployment yang perlu diketahui operator atau reviewer teknis.

## Konfigurasi Environment

Environment file dibaca oleh `config/settings.py` melalui `pydantic-settings`.

### Variabel penting

| Variable | Default | Keterangan |
| --- | --- | --- |
| `APP_ENV` | `development` | mode aplikasi |
| `APP_PORT` | `8000` | port FastAPI |
| `LOG_LEVEL` | `debug` | level log aplikasi |
| `SECRET_KEY` | kosong | wajib diisi untuk production |
| `AUDIT_LOG_DIRECTORY` | `/app/logs` | direktori root audit log untuk runtime service |
| `CACHE_TTL_SECONDS` | `300` | TTL default cache |
| `CACHE_MAX_SIZE` | `10000` | kapasitas maksimum local cache |
| `CACHE_ENCRYPTION_KEY` | kosong | sumber material untuk derive master key |
| `ML_MODEL_NAME` | `pskc_model` | nama logical model yang dibaca runtime dari registry |
| `ML_MODEL_REGISTRY_DIR` | `data/models` | direktori registry model, checksum manifest, dan artefak aktif |
| `ML_MODEL_STAGE` | `development` | stage default untuk artefak model baru yang disimpan ke registry |
| `ML_MODEL_SIGNING_KEY` | kosong | secret signing metadata model; jika kosong, runtime fallback ke `CACHE_ENCRYPTION_KEY` |
| `ML_MODEL_PATH` | `data/models/pskc_model.pskc.json` | path kompatibilitas lama; runtime utama sekarang memakai active version registry |
| `ML_PREDICTION_THRESHOLD` | `0.75` | threshold prediksi |
| `ML_UPDATE_INTERVAL_SECONDS` | `30` | interval update model/predictor |
| `ML_TOP_N_PREDICTIONS` | `10` | jumlah prediksi top-N |
| `SIMULATION_MODE` | `false` | flag mode simulasi |
| `SIMULATION_SCENARIO` | `all` | skenario simulasi default |
| `REDIS_HOST` | `localhost` | host Redis |
| `REDIS_PORT` | `6379` | port Redis |
| `REDIS_PASSWORD` | kosong | password Redis |
| `REDIS_CACHE_PREFIX` | `pskc:cache` | prefix key untuk shared encrypted cache |
| `PREFETCH_QUEUE_KEY` | `pskc:prefetch:jobs` | nama queue Redis untuk job prefetch |
| `PREFETCH_WORKER_BLOCK_TIMEOUT` | `5` | timeout blocking pop worker prefetch |
| `PREFETCH_MAX_RETRIES` | `3` | jumlah retry sebelum job masuk DLQ |
| `PREFETCH_RETRY_BACKOFF_SECONDS` | `5` | backoff dasar retry prefetch |
| `GRAFANA_PASSWORD` | kosong | password admin Grafana |

## Validasi Production Settings

`config/settings.py` akan memvalidasi beberapa nilai saat `APP_ENV=production`:

- `SECRET_KEY`
- `CACHE_ENCRYPTION_KEY`
- `GRAFANA_PASSWORD`

Jika nilainya lemah atau kosong, aplikasi seharusnya menolak start.

## Docker Compose

Service yang didefinisikan di `docker-compose.yml`:

| Service | Port | Status praktis |
| --- | --- | --- |
| `api` | `8000` | service utama yang paling relevan |
| `redis` | `6379` | shared encrypted cache L2 dan queue untuk prefetch worker |
| `frontend` | `3000` | Vite dev server untuk UI React; proxy internal diarahkan ke `api:8000` |
| `prefetch-worker` | - | konsumen Redis queue yang mengisi shared cache dari hasil prediksi API |
| `prometheus` | `9090` | profile opsional, scrape `api` via `/metrics/prometheus` menggunakan `config/prometheus.yml` |
| `grafana` | `3001` | profile opsional, bergantung pada Prometheus |

### Command yang direkomendasikan

```powershell
docker compose up frontend api redis prefetch-worker
```

Untuk validasi backend runtime tanpa frontend:

```powershell
docker compose up -d --build api redis prefetch-worker
python scripts/smoke_backend_runtime.py
docker compose down -v
```

Catatan penting untuk service `frontend`:

- `VITE_API_URL` harus tetap `/api` agar browser berbicara ke origin frontend
- `VITE_API_PROXY_TARGET` dipakai oleh Vite server di dalam container, dan untuk compose ini nilainya harus `http://api:8000`
- hostname seperti `pskc-api` atau `api` hanya valid di network Docker, bukan untuk request langsung dari browser host

### Command yang perlu persiapan tambahan

```powershell
docker compose --profile monitoring up
```

Repo sekarang sudah menyertakan `config/prometheus.yml`.

## Logging dan File System

### Audit log

Backend membuat `TamperEvidentAuditLogger` dengan direktori `/app/logs`.

Implikasinya:

- di container, compose sekarang me-mount `./logs` ke `/app/logs`
- `api` dan `prefetch-worker` memakai subdirektori terpisah (`/app/logs/api` dan `/app/logs/prefetch-worker`) agar file audit tidak saling berbenturan
- di local Windows run, path absolut tersebut dapat mengarah ke lokasi berbeda dari ekspektasi developer

### Data dan model

Folder berikut penting untuk persistensi:

- `data/models/`
- `data/raw/`
- `data/training/`

## Health dan Observability

### Yang tersedia sekarang

- `GET /health` — simple liveness check
- `GET /health/ready` — readiness check dengan dependency verification
- `GET /health/startup` — Kubernetes-style startup probe
- log aplikasi dari uvicorn / Python logging
- audit log file lokal
- `GET /metrics/prefetch`
- `GET /metrics/prometheus`
- `GET /prefetch/dlq`
- `scripts/smoke_backend_runtime.py` untuk validasi live stack backend

### Dependency Health Policy

Sistem membedakan antara dua jenis dependencies:

| Dependency | Tipe | Behavior saat unavailable |
| --- | --- | --- |
| FIPS Module | fail_closed | Blokir startup & readiness |
| Audit Logger | fail_closed | Blokir startup & readiness |
| Redis Cache | fail_open | Tetap serve traffic tanpa cache |
| Prefetch Queue | fail_open | Tetap serve traffic tanpa prefetch |
| ML Runtime | fail_open | Tetap serve traffic tanpa prediksi |

### Contoh Response

```json
// GET /health/ready
{
  "ready": true,
  "status": "All critical dependencies are healthy",
  "version": "1.0.0",
  "timestamp": "2024-01-01T00:00:00",
  "dependencies": {
    "fips_module": {"status": "healthy", "type": "fail_closed", "error": null},
    "audit_logger": {"status": "healthy", "type": "fail_closed", "error": null},
    "redis_cache": {"status": "healthy", "type": "fail_open", "error": null},
    "prefetch_queue": {"status": "healthy", "type": "fail_open", "error": null},
    "ml_runtime": {"status": "healthy", "type": "fail_open", "error": null}
  }
}
```

### Yang belum fully wired

- Prometheus scrape config sekarang ada di `config/prometheus.yml`
- exporter Prometheus backend tersedia di `GET /metrics/prometheus`
- sebagian halaman frontend masih presentasional, meskipun dashboard utama sudah mengambil telemetry backend nyata

## Endpoint Access Control

### Kategori Endpoint

| Kategori | Endpoint | Akses |
| --- | --- | --- |
| Public | `/health`, `/health/ready`, `/health/startup`, `/metrics` | Semua orang |
| Operational | `/cache/*`, `/ml/*`, `/prefetch/*`, `/simulation/*` | Internal network |
| Admin | `/admin`, `/internal`, `/security/*`, `/debug` | Terbatas (private IP) |

### Sensitive Path Protection

Middleware memblokir akses eksternal ke path sensitif:
- `/admin/*`
- `/internal/*`
- `/debug/*`
- `/security/audit`
- `/security/intrusions`

Konfigurasi di `config/settings.py`:
- `sensitive_path_prefixes` — daftar prefix yang diblokir
- `public_endpoints` — endpoint tanpa autentikasi
- `operational_endpoints` — endpoint operasional
- `admin_endpoints` — endpoint admin

## Security Checklist Untuk Deployment Serius

1. isi `CACHE_ENCRYPTION_KEY` dan `SECRET_KEY` dengan secret kuat
2. mount direktori log yang persisten
3. isi `TRUSTED_PROXIES` sesuai topologi jaringan aktual
4. sesuaikan `HTTP_SECURITY_*` dan `HTTP_RATE_LIMIT_*` dengan kebutuhan deployment
5. tinjau ulang seluruh flow request setelah refactor boundary kriptografi
6. isi `ML_MODEL_SIGNING_KEY` dengan secret stabil jika Anda ingin signature model tidak bergantung pada `CACHE_ENCRYPTION_KEY`
7. gunakan artefak model yang dapat diverifikasi checksum dan tidak bergantung pada `.pkl`

## Current Operational Gaps

| Gap | Dampak |
| --- | --- |
| Redis queue/cache belum punya tuning operasional matang | backlog job, retry/DLQ, replay, dan fault handling worker masih sederhana |
| frontend Docker masih berupa Vite dev server | cocok untuk development/demo, tetapi bukan image frontend production |
| telemetry Prometheus masih sederhana | profile monitoring sekarang juga mengekspor lifecycle registry model, tetapi banyak metrik tetap berasal dari state runtime proses API |
| policy trusted proxy dan path sensitif belum tentu sesuai topologi produksi | self-test FIPS dan middleware sudah aktif, tetapi `TRUSTED_PROXIES` serta opsi blokir path sensitif tetap perlu diisi dengan benar |
| CI deployment belum mencakup seluruh topology | workflow backend sekarang memvalidasi focused tests dan live Docker smoke, tetapi belum menguji reverse proxy, monitoring profile, atau skenario production matrix |

## Deployment dengan Reverse Proxy

### Development/Local

```powershell
docker compose up -d api redis prefetch-worker
```

### Production dengan Nginx

```powershell
# Build production images
docker compose -f docker-compose.production.yml build

# Start production stack
docker compose -f docker-compose.production.yml up -d

# Check nginx logs
docker compose -f docker-compose.production.yml logs nginx
```

### Topologi Production

```
[Client] -> [Nginx:443] -> [PSKC API:8000] -> [Redis:6379]
                                     -> [Prefetch Worker]
                                     
[Prometheus:9090] <- [PSKC API /metrics]
[Grafana:3001] <- [Prometheus]
```

### Environment Variables Production

Buat file `.env.production`:

```bash
# Required secrets
SECRET_KEY=your-production-secret-key-min-32-chars
CACHE_ENCRYPTION_KEY=your-encryption-key-min-32-chars
ML_MODEL_SIGNING_KEY=your-model-signing-key
REDIS_PASSWORD=your-redis-password
GRAFANA_PASSWORD=your-grafana-password

# Optional overrides
APP_ENV=production
LOG_LEVEL=info
TRUSTED_PROXIES=10.0.0.0/8,172.16.0.0/12
```

### Trusted Proxy Configuration

Set `TRUSTED_PROXIES` dengan CIDR dari reverse proxy Anda:

```bash
# Untuk Docker Compose networking
TRUSTED_PROXIES=10.0.0.0/8,172.16.0.0/12

# Untuk AWS ELB/ALB
TRUSTED_PROXIES=10.0.0.0/8,172.16.0.0/12,203.0.113.0/24

# Untuk Cloudflare
TRUSTED_PROXIES=103.21.244.0/22,103.22.200.0/22,... (Cloudflare IP ranges)
```

### Kubernetes Probes

Gunakan endpoint berikut untuk Kubernetes:

| Probe | Endpoint | Kriteria |
| --- | --- | --- |
| livenessProbe | `/health` | Process alive |
| readinessProbe | `/health/ready` | Critical deps healthy |
| startupProbe | `/health/startup` | Startup complete |

Contoh konfigurasi Kubernetes:

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 30

readinessProbe:
  httpGet:
    path: /health/ready
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10
  failureThreshold: 3

startupProbe:
  httpGet:
    path: /health/startup
    port: 8000
  failureThreshold: 30
  periodSeconds: 10
```

## Observability Historis

### Metrics Persistence

Metrics sekarang dapat bertahan antar proses restart karena disimpan di Redis:

| Endpoint | Fungsi |
| --- | --- |
| `/metrics/historical/cache` | Cache hit rate dalam time window |
| `/metrics/historical/latency` | Latency percentiles (p50, p95, p99) |

Contoh response `/metrics/historical/cache?window_seconds=3600`:

```json
{
  "hit_rate": 0.85,
  "hits": 8500,
  "misses": 1500,
  "total": 10000,
  "window_seconds": 3600
}
```

### Prometheus Alerting

File `config/prometheus.rules.yml` berisi alert rules untuk:

| Alert | Severity | Kondisi |
| --- | --- | --- |
| PSKCRedisUnavailable | critical | Redis unavailable > 1m |
| PSKCPrefetchDLQGrowing | warning | DLQ > 10 items > 5m |
| PSKCPrefetchDLQCritical | critical | DLQ > 100 items > 10m |
| PSKCCacheHitRateLow | warning | Hit rate < 50% > 10m |
| PSKCMLModelNotLoaded | critical | ML model not loaded > 5m |
| PSKCHighLatency | warning | Avg latency > 1000ms > 5m |

### Comprehensive Metrics API

Metrics sekarang persistent di Redis dan bisa diakses melalui API:

| Endpoint | Fungsi |
| --- | --- |
| `/metrics/comprehensive` | Ringkasan metrics lengkap (cache, latency, ML, lifecycle) |
| `/metrics/historical/cache` | Cache hit rate dalam time window |
| `/metrics/historical/latency` | Latency percentiles (p50, p95, p99) |
| `/metrics/ml/training` | History training ML |
| `/metrics/drift` | History deteksi concept drift |
| `/metrics/lifecycle/model` | History lifecycle model |
| `/metrics/lifecycle/key-rotation` | History rotasi kunci |

### Retention Policy

Konfigurasi retention di environment:

| Variable | Default | Description |
| --- | --- | --- |
| `METRICS_RETENTION_DAYS` | 7 | Days to retain metrics |
| `AUDIT_RETENTION_DAYS` | 90 | Days to retain audit logs |
| `LIFECYCLE_RETENTION_DAYS` | 365 | Days to retain ML lifecycle events |

## Incident Notes yang Perlu Diingat

Jika operator melihat perilaku janggal pada endpoint selain `/health`, area yang pertama kali diperiksa biasanya adalah:

- wiring `SecureCacheManager` dan `EncryptedCacheStore`
- interaksi audit logger dengan secure cache
- path log `/app/logs`
- helper atau modul lama yang belum terselaraskan dengan refactor terbaru
