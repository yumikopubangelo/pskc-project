# Arsitektur Sistem

Dokumen ini menjelaskan arsitektur runtime PSKC berdasarkan kode yang aktif saat ini, bukan desain aspiratif lama.

## Gambaran Umum

Backend utama berada di `src/api/routes.py` dan membangun dependency inti saat startup menggunakan FastAPI lifespan.

```text
request
  -> FastAPI router
    -> SecureCacheManager
      -> EncryptedCacheStore
        -> LocalCache
        -> RedisCache
        -> CachePolicyManager
        -> FipsCryptographicModule
        -> TamperEvidentAuditLogger
    -> KeyFetcher (hanya saat cache miss)
  -> PrefetchQueue (Redis)
    -> prefetch worker
```

## Komponen Runtime Aktif

| Komponen | File utama | Peran |
| --- | --- | --- |
| FastAPI app | `src/api/routes.py` | Entry point HTTP dan dependency wiring |
| Local cache | `src/cache/local_cache.py` | Cache in-memory dengan TTL dan eviction sederhana |
| Redis shared cache | `src/cache/redis_cache.py` | L2 encrypted cache lintas proses untuk API dan worker |
| Cache policy | `src/cache/cache_policy.py` | Hitung TTL dinamis dan metadata hot/warm/cold |
| Encrypted store | `src/cache/encrypted_store.py` | Enkripsi/dekripsi transparan untuk data cache |
| Secure cache manager | `src/security/intrusion_detection.py` | Gatekeeper untuk operasi cache aman |
| FIPS-style crypto boundary | `src/security/fips_module.py` | AES-GCM, HKDF, hashing, signing, RNG |
| Audit logger | `src/security/tamper_evident_logger.py` | Hash-chained audit log |
| KMS fetcher | `src/auth/key_fetcher.py` | Fallback fetch saat cache miss |
| Prefetch worker | `src/workers/prefetch_worker.py` | Konsumsi job prefetch Redis dan isi cache bersama |
| **Key Lifecycle Manager** | `src/security/key_lifecycle_manager.py` | **Unified workflow: create → rotate → revoke → expire** |

## Inisialisasi Aplikasi

Saat aplikasi start, `lifespan()` melakukan langkah berikut:

1. Membaca `CACHE_ENCRYPTION_KEY` dari settings.
2. Menderivasi master key dengan HKDF.
3. Membuat `FipsCryptographicModule`.
4. Membuat `TamperEvidentAuditLogger` dengan path log default `/app/logs`.
5. Membuat `LocalCache`, `RedisCache`, `CachePolicyManager`, `EncryptedCacheStore`, dan `SecureCacheManager`.
6. Menginisialisasi runtime ML online.
7. Menyimpan instance penting ke `app.state`.

Self-test FIPS di `src/security/fips_self_tests.py` sekarang dipanggil saat startup FastAPI dan akan menggagalkan boot bila KAT boundary kriptografi gagal.

## Flow Request Yang Aktif

### 1. `GET /health`

Flow paling sederhana:

```text
client -> FastAPI -> HealthResponse
```

Tidak ada akses ke cache, model, atau KMS.

### 2. `POST /keys/access`

Flow request saat ini:

```text
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
      -> EncryptedCacheStore.set()
        -> encrypt via FipsCryptographicModule
        -> LocalCache.set()
        -> RedisCache.set()
    -> schedule Redis prefetch job
    -> KeyAccessResponse
```

Catatan:

- Jika cache miss dan `KeyFetcher` tidak punya endpoint upstream, ia mengembalikan key sintetis untuk mode generic/testing.
- Response tidak pernah mengembalikan material kunci plaintext.
- Field `verify` saat ini belum mengubah flow runtime.

### 3. `POST /keys/store`

Flow request:

```text
client
  -> routes.store_key()
    -> decode base64
    -> SecureCacheManager.secure_set()
      -> IDS cache poisoning check
      -> EncryptedCacheStore.set()
    -> KeyStoreResponse
```

Catatan:

- Schema menerima `ttl`, tetapi implementasi endpoint belum meneruskannya ke secure store.
- Invalid payload atau mismatch internal masih bisa berujung `500`, karena penanganan error belum sepenuhnya granular.

## Komponen yang Ada tetapi Bukan Jalur Runtime Aktif

### Redis

`docker-compose.yml` sekarang menyediakan Redis yang aktif dipakai sebagai:

1. shared encrypted cache L2 untuk API dan worker
2. queue untuk job prefetch

Request path tetap mempertahankan `LocalCache` sebagai L1 agar hit lokal tetap cepat.

### Middleware keamanan HTTP

`src/security/security_headers.py` dan `SlidingWindowRateLimiter` sekarang didaftarkan di `src/api/routes.py` sebagai middleware FastAPI default. Trusted proxy CIDR dibaca dari `TRUSTED_PROXIES`, sedangkan tuning header hardening dan rate limiter memakai `HTTP_SECURITY_*`.

### Predictor dan prefetch otomatis

Modul ML sekarang terhubung ke runtime backend untuk collector event, status model, prediction, manual retraining, dan request-path scheduling ke Redis queue. Worker terpisah kemudian mengonsumsi job itu, fetch key dari KMS, dan menulis hasil terenkripsi ke Redis cache bersama.

Retry path saat ini:

1. job gagal fetch akan dipindah ke retry set Redis dengan backoff eksponensial sederhana
2. worker mempromosikan job retry yang sudah jatuh tempo kembali ke queue utama
3. job yang melewati batas retry atau gagal `secure_set()` dipindah ke DLQ Redis

### Simulasi

Folder `simulation/` sekarang dilayani melalui endpoint `/simulation/*` untuk frontend dan benchmark interaktif. Meski demikian, ia tetap terpisah dari jalur request produksi untuk `keys/access`.

## Batasan dan Realita Implementasi

Arsitektur yang perlu dipahami apa adanya:

1. Secure cache sekarang berupa hybrid L1/L2: `LocalCache` per-proses ditambah Redis shared cache lintas proses.
2. Refactor FIPS-style boundary sudah tervalidasi pada jalur request inti (`store/access/invalidate/security`), tetapi coverage integration lintas environment dan topology deploy masih belum penuh.
3. Audit log saat ini mengarah ke `/app/logs`, sehingga deployment lokal perlu memastikan path itu dapat dibuat atau di-mount.
4. Self-test FIPS sekarang aktif by default. Middleware HTTP dan rate limiter juga aktif, tetapi policy blokir path sensitif dari external IP sengaja dibuat configurable agar tidak memutus endpoint dashboard yang sudah dipakai frontend.
5. Worker prefetch sudah punya retry/DLQ dasar, tetapi belum punya backpressure, concurrency control, atau dead-letter replay workflow yang matang.

## File Lain yang Relevan

- [api_reference.md](api_reference.md)
- [security_model.md](security_model.md)
- [simulation_and_ml.md](simulation_and_ml.md)
