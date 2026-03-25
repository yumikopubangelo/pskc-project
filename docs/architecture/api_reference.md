# API Reference

Dokumen ini mendeskripsikan endpoint FastAPI yang benar-benar tersedia dan relevan untuk frontend saat ini.

## Base URL

- Local default: `http://localhost:8000`
- Via frontend dev server: `http://localhost:3000/api`
- OpenAPI docs: `http://localhost:8000/docs`

## Authentication dan IP Handling

API belum memakai token auth umum untuk seluruh endpoint. Namun, request handler membaca IP klien dengan aturan berikut:

- `X-Forwarded-For` hanya dipercaya jika koneksi datang dari IP yang termasuk `TRUSTED_PROXIES`
- jika proxy tidak dipercaya, backend memakai IP koneksi langsung

## Core Endpoints

### `GET /health`

Health check dasar untuk API.

### `POST /keys/access`

Ambil kunci dari secure cache lokal. Jika cache miss, backend memanggil `KeyFetcher` lalu menyimpan hasilnya ke cache terenkripsi.

Request body:

```json
{
  "key_id": "demo-key",
  "service_id": "demo-service",
  "verify": true
}
```

Catatan:

- material kunci tidak pernah dikembalikan di response
- endpoint ini juga menambah counter request, hit, miss, dan latency untuk dashboard
- endpoint ini juga merekam event akses ke collector ML runtime
- setelah request utama selesai, backend menjadwalkan job prefetch ke Redis queue; worker terpisah kemudian mengisi shared cache terenkripsi
- jika worker gagal mengambil key dari upstream, job akan diretry dengan backoff eksponensial sederhana lalu dipindahkan ke DLQ setelah melewati batas retry

### `POST /keys/store`

Simpan material kunci base64 ke secure cache lokal.

Request body:

```json
{
  "key_id": "demo-key",
  "key_data": "ZGVtb19rZXlfZGF0YQ==",
  "service_id": "demo-service"
}
```

## Key Lifecycle Management

### `POST /keys/lifecycle/create`

Buat kunci baru dengan lifecycle management terintegrasi (cache + secure store).

Query parameters:
- `key_id` (required) - Identifier kunci
- `key_type` (optional, default: "encryption") - Tipe kunci
- `created_by` (optional, default: "system")
- `description` (optional)
- `expires_in_days` (optional) - Hari hingga kunci expired

### `POST /keys/lifecycle/{key_id}/rotate`

Rotasi kunci ke versi baru dengan invalidasi cache otomatis.

Query parameters:
- `created_by` (optional)
- `force` (optional, default: false)

### `POST /keys/lifecycle/{key_id}/revoke`

Cabut kunci segera dengan invalidasi cache.

Query parameters:
- `reason` (optional)
- `invalidated_by` (optional)

### `POST /keys/lifecycle/{key_id}/expire`

Expired kunci secara manual.

### `GET /keys/lifecycle`

List semua kunci terkelola dengan filter opsional (status, key_type).

### `POST /keys/lifecycle/workflow/{workflow}`

Eksekusi predefined workflow:
- `create_rotate` - Buat dan langsung rotasi
- `rotate_revoke` - Rotasi lalu cabut
- `create_expire` - Buat dengan expiration
- `full_lifecycle` - Buat → rotasi berkali-kali → cabut

## Metrics dan Cache

### `GET /metrics`

Ringkasan metrik runtime backend.

Response fields penting:

- `cache_hits`
- `cache_misses`
- `cache_hit_rate`
- `total_requests`
- `avg_latency_ms`
- `active_keys`

### `GET /cache/stats`

Statistik ukuran cache dan hit/miss cache.

### `GET /cache/keys`

Daftar key aktif yang saat ini tercatat di cache runtime.

### `POST /cache/invalidate/{key}`

Hapus key dari daftar cache aktif runtime.

## ML

### `GET /ml/status`

Status runtime ML yang tersedia di backend.

Response fields penting:

- `status`
- `model_loaded`
- `last_training`
- `sample_count`

Catatan:

- `status` dapat bernilai `not_trained`, `collecting_data`, `ready_for_training`, `artifact_present`, atau `trained`
- `sample_count` berasal dari event akses nyata yang dikumpulkan backend
- `model_loaded=true` berarti model runtime hasil training sudah aktif dipakai predictor

### `GET /ml/registry`

Ringkasan registry model untuk logical model aktif.

Response fields penting:

- `model_name`
- `summary.active_version`
- `summary.active_stage`
- `summary.versions[]`
- `stats.signed_versions`
- `stats.unsigned_versions`

### `GET /ml/lifecycle`

History lifecycle model yang persisten di registry.

Query params:

- `limit`
- `model_name`
- `event_type`

Response fields penting:

- `events[]`
- `stats.events_total`
- `stats.events_by_type`

### `GET /ml/predictions`

Daftar prediksi key yang tersedia saat ini.

Catatan:

- jika request path belum menghasilkan trafik, response bisa berupa list kosong
- sebelum model terlatih, predictor fallback ke hot keys dari collector runtime

### `POST /ml/retrain`

Trigger retraining runtime berdasarkan event akses yang sudah dikumpulkan backend. Endpoint ini mengembalikan status sukses/gagal, jumlah sample, waktu training, dan metrik evaluasi saat tersedia.

### `POST /ml/promote`

Promosikan versi model tertentu ke stage target. Jika `make_active=true`, runtime akan reload versi aktif baru setelah integritas artefak diverifikasi.

### `POST /ml/rollback`

Rollback runtime ke versi aman sebelumnya atau ke versi yang dipilih eksplisit.

## Simulation

### `GET /simulation/scenarios`

Katalog skenario simulasi backend yang bisa dijalankan dari UI.

Response berisi:

- `scenarios[]`
- `default_scenario`

Setiap skenario memuat metadata berikut:

- `id`, `name`, `category`, `summary`
- `default_request_count`
- `target_p99_ms`
- `expected_hit_rate`
- `profiles[]`
- `references[]`

### `POST /simulation/run`

Jalankan engine simulasi Python di backend.

Request body contoh:

```json
{
  "scenario": "amazon",
  "profile_id": "high",
  "request_count": 1000
}
```

Response fields penting:

- `simulation_id`
- `status`
- `scenario`
- `profile_id`
- `request_count`

### `GET /simulation/results/{simulation_id}`

Ambil hasil simulasi yang sudah dijalankan.

Response berisi blok utama berikut:

- `metadata`
- `overview`
- `results.without_pskc`
- `results.with_pskc`
- `comparison`
- `charts.latency_trend`
- `charts.hit_rate`

Frontend halaman `Simulation` sekarang memakai endpoint ini sebagai sumber chart dan ringkasan utama.

## Security

### `GET /security/audit`

Membaca event terbaru dari tamper-evident audit log runtime.

### `GET /security/intrusions`

Membaca alert intrusion terbaru dari IDS runtime yang aktif.

## Endpoint Tambahan Untuk Dashboard

### `GET /metrics/latency`

Mengembalikan komparasi latency dari hasil simulasi backend terakhir yang dijalankan melalui `/simulation/run`. Jika belum ada simulasi, response tetap `data: []`.

### `GET /metrics/cache-distribution`

Mengembalikan distribusi cache hit dan miss jika backend sudah mencatat request nyata.

### `GET /metrics/accuracy`

Mengembalikan history akurasi training ML runtime jika backend sudah pernah menjalankan `/ml/retrain`.

### `GET /metrics/prefetch`

Mengembalikan metrik queue prefetch berbasis Redis:

- `queue_length`
- `retry_length`
- `dlq_length`
- `stats.enqueued_total`
- `stats.dequeued_total`
- `stats.completed_total`
- `stats.retried_total`
- `stats.dlq_total`

### `GET /metrics/prometheus`

Mengembalikan metrik runtime backend dalam format text exposition Prometheus.

Metrik yang diekspor saat ini mencakup:

- ringkasan request/cache (`pskc_requests_total`, `pskc_cache_hits_total`, `pskc_cache_misses_total`)
- ukuran cache lokal dan shared cache Redis
- status model ML runtime dan jumlah sample collector
- signature coverage registry model dan event lifecycle yang persisten
- panjang queue/retry/DLQ prefetch

### `GET /prefetch/dlq`

Mengembalikan item dead-letter queue untuk job prefetch yang gagal setelah batas retry atau gagal menulis ke secure cache.

## Referensi Kode

- `src/api/routes.py`
- `src/api/schemas.py`
- `src/api/simulation_service.py`
- `src/auth/key_fetcher.py`
- `src/security/security_headers.py`
