# Arsitektur Caching: L1 dan L2

Dokumen ini menjelaskan strategi caching PSKC dengan detail mendalam tentang layer L1 (local memory) dan L2 (Redis), termasuk data flow, TTL management, eviction policy, dan encryption.

## Gambaran Umum

PSKC menggunakan **two-tier caching strategy** untuk efisiensi maksimal:

```
┌─────────────────────────────────────────────────────────────┐
│                        REQUEST FLOW                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  SecureCacheManager  │
                    │  (Gatekeeper)    │
                    └──────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
    ┌────────┐          ┌──────────┐          ┌───────────┐
    │ IDS    │          │  L1 Local│          │Tamper Log │
    │Checks  │          │  Cache   │          │           │
    │        │          │(In-Memory)          │           │
    └────────┘          └──────────┘          └───────────┘
                              │
                         (L1 MISS)
                              │
                              ▼
                        ┌──────────────┐
                        │  L2 Redis    │
                        │ (Encrypted)  │
                        └──────────────┘
                              │
                         (L2 MISS)
                              │
                              ▼
                        ┌──────────────┐
                        │  KeyFetcher  │
                        │  (KMS/Origin)│
                        └──────────────┘
```

## Layer 1: Local In-Memory Cache (L1)

### Tujuan
- **Zero-latency access**: Akses memory lokal tanpa network overhead
- **Per-process isolation**: Setiap worker/API instance punya cache sendiri
- **Lightweight**: Cocok untuk development dan single-server testing

### Implementasi
- **File**: `src/cache/local_cache.py`
- **Data Structure**: Dictionary Python dengan TTL tracking
- **Thread-safety**: Protected by `threading.RLock()`
- **Max Size**: Konfigurasi `cache_max_size` (default: 10,000 entries)

### Fitur-Fitur

#### 1. TTL Management
```python
# Setiap entry menyimpan:
{
    "key_id": {
        "plaintext_value": <encrypted_bytes>,
        "timestamp_created": <unix_time>,
        "ttl_seconds": <lifetime>,
        "metadata": {
            "source": "redis" | "keyfetcher",
            "encrypted": True
        }
    }
}

# TTL dihitung dari timestamp_created, bukan last-access
# Default: 300 detik (5 menit)
```

#### 2. Simple Eviction Policy
```
- **LRU-like cleanup**: Saat jumlah entry > max_size
- **Strategy**: Remove oldest entries (FIFO) hingga mencapai 80% capacity
- **Trigger**: Automatic saat set() called dan cache penuh
- **Cost**: O(n) cleanup untuk menghindari complex data structures
```

#### 3. Encryption at Rest
```python
# L1 cache SELALU menyimpan data terenkripsi
# Plaintext hanya dalam memory transien selama processing
# Benefit:
#   - Jika attacker dump L1 memory, data masih protected
#   - Konsisten dengan security model PSKC
```

### Operasi Utama

| Operasi | Latency | Behavior |
|---------|---------|----------|
| `get(key_id)` | <1ms | Return plaintext jika found & not expired; otherwise None |
| `set(key_id, value, ttl)` | <1ms | Store encrypted value dengan TTL; trigger eviction jika perlu |
| `delete(key_id)` | <1ms | Remove entry immediately |
| `clear_expired()` | O(n) | Scan semua entry dan hapus yang expired; berjalan periodic |
| `get_stats()` | <1ms | Return hit/miss count, eviction count, memory usage |

### Konfigurasi

```env
# File: .env atau docker-compose.yml
CACHE_TTL_SECONDS=300                    # L1 entry lifetime
CACHE_MAX_SIZE=10000                     # Max entries sebelum eviction
```

### Use Case Optimal
- **REST API service**: Caching response kunci yang frequently accessed
- **Single-server deployment**: Semua request dari satu process
- **High data sensitivity**: Plaintext tidak pernah written to disk

### Limitations
- **Not distributed**: Setiap instance punya separate cache, no cache coherence
- **Lost on restart**: Data hilang saat process di-terminate
- **Memory-bound**: Max size terbatas memory yang available
- **No persistence**: Tidak ada backup/recovery mechanism

---

## Layer 2: Redis Distributed Cache (L2)

### Tujuan
- **Shared across all workers**: API servers dan prefetch workers share single cache
- **Persistent (optional)**: Can survive process restarts dengan RDB/AOF
- **High throughput**: Optimized untuk 1000s concurrent connections
- **Prefix support**: Namespace keys untuk isolation (e.g., `pskc:cache:user_id:key_id`)

### Implementasi
- **File**: `src/cache/redis_cache.py`
- **Connection**: Pool-based with automatic retry and backoff
- **Encryption**: Client-side AES-GCM sebelum sending ke Redis (in-transit + at-rest)
- **Authentication**: Password-protected connection via `REDIS_PASSWORD`

### Fitur-Fitur

#### 1. Encrypted Data Storage
```python
# Data flow saat L1 miss, L2 hit:
plaintext_key = SecureCacheManager.secure_get()
  -> EncryptedCacheStore.get_with_metadata()
    -> RedisCache.get(key_id)
      # Redis returns: <IV:16 bytes>:<CIPHERTEXT:variable>:<TAG:16 bytes>
      -> FipsCryptographicModule.decrypt_aes_gcm()
        # Returns plaintext + metadata
      -> Returns to caller

# Data flow saat cache set:
SecureCacheManager.secure_set(key_id, plaintext)
  -> EncryptedCacheStore.set()
    -> FipsCryptographicModule.encrypt_aes_gcm()
      # Returns: IV + ciphertext + authentication tag
    -> RedisCache.set(key_id, encrypted_value, ttl)
      # Redis stores: encrypted_value with TTL
```

#### 2. TTL & Expiration
```
- Redis TTL set saat keys stored (via SETEX atau SET with EX)
- Automatic eviction saat TTL expired
- No cleanup sweep needed (Redis handles it)
- Configurable per-entry atau use default policy
```

#### 3. Connection Management
```python
# Adaptive backoff saat Redis unavailable:
attempt=0: immediate reconnect
attempt=1: wait 1 second
attempt=2: wait 5 seconds
attempt=3: wait 30 seconds (configured REDIS_FAILURE_BACKOFF_SECONDS)

# If all attempts fail:
- Fallback to L1 only (no L2 reads/writes)
- Log warning dengan connection error details
- Continue serving cache hits from L1
- Prefetch worker blocked (can't fill shared cache)
```

#### 4. Key Namespacing

```python
# REDIS_CACHE_PREFIX = "pskc:cache"
# Format: {prefix}:{service_id}:{key_id}:{optional_context}

Example keys:
  pskc:cache:api-prod:user_12345:key_1
  pskc:cache:api-prod:user_12345:key_2
  pskc:cache:worker:tenant_xyz:key_9

Benefit:
  - Isolation antara services/tenants
  - Easy to batch clear untuk specific service
  - No collision dengan other Redis users
```

### Operasi Utama

| Operasi | Latency | Behavior |
|---------|---------|----------|
| `get(key_id, ttl_hint)` | 1-5ms | Fetch dari Redis; decrypt locally |
| `set(key_id, value, ttl)` | 1-5ms | Encrypt locally; store to Redis dengan TTL |
| `delete(key_id)` | <1ms | Remove key dari Redis |
| `exists(key_id)` | <1ms | Check existence tanpa retrieving value |
| `get_all_by_pattern()` | Variable | Scan keys matching pattern (e.g., prefetch:*) |
| `health_check()` | 1ms | Ping Redis; return connectivity status |

### Konfigurasi

```env
# .env atau docker-compose.yml
REDIS_HOST=redis                         # Hostname atau IP
REDIS_PORT=6379                          # Port (default: 6379)
REDIS_DB=0                               # Database index
REDIS_PASSWORD=pskc_redis_secret         # Auth password

REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS=0.5 # Connection timeout
REDIS_SOCKET_TIMEOUT_SECONDS=10.0        # Command timeout
REDIS_FAILURE_BACKOFF_SECONDS=30.0       # Backoff saat unavailable

REDIS_CACHE_PREFIX=pskc:cache            # Key namespace prefix
PREFETCH_QUEUE_KEY=pskc:prefetch:jobs    # Queue untuk prefetch worker
```

### Use Case Optimal
- **Distributed deployment**: Multiple API servers sharing cache
- **Cross-process communication**: Prefetch worker filling cache untuk API servers
- **Data persistence**: RDB snapshots untuk recovery after restart
- **High availability**: Redis Sentinel/Cluster untuk redundancy

### Limitations
- **Network latency**: 1-5ms per Redis call (vs <1ms untuk L1)
- **Failure domain**: If Redis down, L1 becomes bottleneck
- **Concurrency**: Single Redis instance bottleneck pada extreme scale (>10K req/s)
- **Encryption overhead**: Client-side AES-GCM add computational cost

---

## Cache Coherence & Multi-Layer Strategy

### Data Flow pada Cache Hit

```
Request kunci:
  1. SecureCacheManager.secure_get(key_id)
  2. EncryptedCacheStore.get_with_metadata(key_id)
  3. LocalCache.get(key_id) ───→ HIT ──→ Return plaintext
  |
  (L1 MISS)
  |
  4. RedisCache.get(key_id) ──→ HIT ──→ Decrypt + populate L1 + Return
  |
  (L2 MISS)
  |
  5. KeyFetcher.fetch_key(key_id) ──→ Get dari upstream/KMS
  6. EncryptedCacheStore.set() ──→ Encrypt + store L1 + store L2
  7. Return plaintext to caller
```

### Data Flow pada Cache Write

```
SET kuci:
  1. SecureCacheManager.secure_set(key_id, plaintext)
  2. EncryptedCacheStore.set()
  3. Encrypt plaintext dengan AES-GCM
  4. LocalCache.set(encrypted, ttl=CACHE_TTL_SECONDS)
  5. RedisCache.set(encrypted, ttl=CACHE_TTL_SECONDS)
  6. Log audit entry
  7. Trigger prefetch job (optional)
```

### Invalidation Scenarios

| Scenario | L1 Action | L2 Action | Trigger |
|----------|-----------|-----------|---------|
| Key rotated | Delete entry | Delete entry | Key rotation API |
| Key revoked | Delete entry | Delete entry | Revocation API |
| TTL expired | Auto-removed by timer | Auto-removed by Redis | Time passage |
| Admin flush | Clear all | Clear all | `DELETE /cache/flush` |
| Memory pressure | LRU eviction | Not affected | when L1 > max_size |

---

## Encryption & Security

### Key Hierarchy

```
┌──────────────────────────────────┐
│  CACHE_ENCRYPTION_KEY            │
│  (Seed dari environment)          │
└──────────────────────────────────┘
             │
             ▼ HKDF (info="cache-master-key")
┌──────────────────────────────────┐
│  Master Key (256-bit)            │
│  Derived & stored in FIPS module │
└──────────────────────────────────┘
             │
      ┌──────┴──────┐
      ▼             ▼
┌─────────┐   ┌─────────────┐
│ L1 Enc  │   │ L2 Enc+Auth │
│ (AES)   │   │ (AES-GCM)   │
└─────────┘   └─────────────┘
```

### Encryption Algorithm
- **Cipher**: AES-256-GCM (authenticated encryption)
- **Key derivation**: HKDF-SHA256 dengan unique per-context info
- **IV (nonce)**: Generated randomly per encryption (16 bytes)
- **Authentication tag**: 16 bytes, verified saat decrypt

### Example: Encrypted Cache Entry

```
Plaintext: "my-secret-key-material"

Encryption process:
  1. Generate random IV (16 bytes)
  2. Derive encryption key dari master key
  3. AES-256-GCM encrypt plaintext
     → Output: ciphertext (variable length)
     → Output: authentication tag (16 bytes)
  4. Combined: IV || ciphertext || tag (hexadecimal encoded)

Encrypted string (example):
  "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6:5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d:q1w2e3r4t5y6u7i8o9p0a1s2d3f4g5h6"
  └─ IV ─────────────┘└─ Ciphertext ────────────────────────────┘└─ Tag ───────────────────┘
```

---

## Performance Characteristics

### Latency Breakdown

```
L1 Hit:
  ├─ Lock acquire: <0.1ms
  ├─ Lookup: <0.1ms
  ├─ Decrypt: 0.5-1ms (AES-GCM)
  └─ Total: ~1-2ms

L2 Hit (after L1 miss):
  ├─ Network RTT: 1-3ms
  ├─ Redis get: 1-2ms
  ├─ Decrypt: 0.5-1ms
  └─ Total: ~3-7ms

L2 Miss + KeyFetcher:
  ├─ Network to KMS/origin: 10-100ms
  ├─ Local encrypt: 0.5-1ms
  ├─ L1 write: <0.5ms
  ├─ L2 write (network + write): 2-5ms
  └─ Total: ~12-110ms
```

### Throughput Estimates

| Scenario | QPS | Bottleneck |
|----------|-----|-----------|
| All L1 hits | 10K+ | CPU (AES-GCM) |
| 90% L1, 10% L2 | 5K+ | Network to Redis |
| Cold cache (all L2 miss) | <100 | KMS/Origin latency |

### Memory Impact

```
Per cache entry (example key_id="user_123:key_456"):
  Overhead: 100-200 bytes (Python dict internals)
  Key: ~50 bytes
  Encrypted value: ~200 bytes (AES-GCM)
  Metadata: ~50 bytes
  Total per entry: ~400-500 bytes

With 10,000 entries:
  Total memory: ~4-5 MB

Recommendation: Set CACHE_MAX_SIZE based on available memory:
  - Small VM (512MB): max_size = 1,000-2,000
  - Medium VM (2GB): max_size = 5,000-10,000
  - Large VM (8GB): max_size = 50,000+
```

---

## Troubleshooting

### Issue: L1 Cache Constantly Evicting

**Symptom**: High eviction count, low hit rate

**Diagnosis**:
```python
cache_stats = local_cache.get_stats()
print(f"Hit rate: {cache_stats['hits'] / (cache_stats['hits'] + cache_stats['misses'])}")
print(f"Evictions: {cache_stats['evictions']}")
```

**Solution**:
1. Increase `CACHE_MAX_SIZE` jika memory available
2. Analyze access pattern: apakah banyak unique keys?
3. Turunkan `CACHE_TTL_SECONDS` jika banyak stale data

### Issue: Redis Connection Flaky

**Symptom**: Frequent "Failed to get from Redis" logs, latency spikes

**Diagnosis**:
```bash
# Check Redis availability
redis-cli -h <redis_host> -p <redis_port> ping

# Check network latency
ping <redis_host>

# Check Redis memory
redis-cli info memory
```

**Solution**:
1. Verify network connectivity dan firewall rules
2. Increase `REDIS_SOCKET_TIMEOUT_SECONDS` jika slow network
3. Add Redis replicas (Sentinel mode) untuk HA
4. Consider Redis Cluster untuk scale beyond single instance

### Issue: Encrypted Data Corrupt / Can't Decrypt

**Symptom**: "Decryption failed" atau "Authentication tag mismatch"

**Diagnosis**:
```python
# Check if key derivation consistent
master_key_1 = FipsCryptographicModule.derive_key_hkdf(seed, "cache-master-key")
master_key_2 = FipsCryptographicModule.derive_key_hkdf(seed, "cache-master-key")
assert master_key_1 == master_key_2  # Should be true
```

**Solution**:
1. Verify `CACHE_ENCRYPTION_KEY` tidak berubah (akan cause all existing entries unreadable)
2. Clear cache jika upgrade libcrypto/OpenSSL
3. Check that FIPS module self-tests pass pada startup

---

## Best Practices

### 1. **Set Appropriate TTL**
```python
# Fast-changing data: short TTL
cache_ttl = 60  # 1 minute

# Stable data: long TTL
cache_ttl = 3600  # 1 hour

# Default (if not specified): 300 seconds (5 minutes)
```

### 2. **Monitor Cache Health**
```python
import logging

logger = logging.getLogger(__name__)

stats = cache.get_stats()
logger.info(f"Cache stats: hits={stats['hits']}, misses={stats['misses']}, "
            f"hit_rate={stats['hits'] / (stats['hits'] + stats['misses']):.2%}")
```

### 3. **Handle Redis Unavailability Gracefully**
```python
try:
    value = redis_cache.get(key_id)
except RedisConnectionError:
    # Fallback to L1 or upstream fetch
    value = local_cache.get(key_id) or fetch_from_upstream(key_id)
```

### 4. **Don't Store Plaintext Sensitive Data**
```python
# WRONG: Storing plaintext password
local_cache.set("user_password", plaintext_password)

# RIGHT: Only store encrypted or hashed
encrypted = fips_module.encrypt_aes_gcm(password)
local_cache.set("user_pwd", encrypted)  # Already encrypted automatically
```

### 5. **Monitor Encryption Overhead**
- AES-GCM is fast (~1-2µs per MB on modern CPUs)
- Profile your critical path to ensure <10ms total latency
- Use `perf` or `py-spy` if encryption becomes bottleneck

---

## Related Components

- **EncryptedCacheStore**: `src/cache/encrypted_store.py` - Orchestrates L1+L2 with encryption
- **SecureCacheManager**: `src/security/intrusion_detection.py` - Adds IDS checks on top
- **CachePolicyManager**: `src/cache/cache_policy.py` - Dynamic TTL based on hotness
- **Prefetch Worker**: `src/workers/prefetch_worker.py` - Fills cache proactively
- **Key Lifecycle Manager**: `src/security/key_lifecycle_manager.py` - Cache eviction on key rotation
