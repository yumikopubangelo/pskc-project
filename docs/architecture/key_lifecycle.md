# Key Lifecycle Management

Dokumen ini menjelaskan complete lifecycle kunci dalam PSKC (Predictive Secure Key Cache), dari creation sampai expiration/revocation.

## Ikhtisar Len
Setiap kunci mengalami beberapa tahapan dalam hidupnya:

```
┌─────────────────────────────────────────────────────────────┐
│                    KEY LIFECYCLE FLOW                       │
└─────────────────────────────────────────────────────────────┘

┌───────────┐
│  CREATE   │  Kunci baru di KMS, belum di cache
└────┬──────┘
     │
┌────▼──────────┐
│  ACTIVE       │  Kunci tersedia untuk akses (bisa di-cache)
└────┬──────────┘
     │  (optional)
┌────▼──────────┐
│  ROTATE       │  Versi lama dipertahankan, versi baru dibuat
│  (v1→v2)      │  Cache coherence dipicu
└────┬──────────┘
     │
┌────▼──────────┐
│  SCHEDULED    │  Waktu expiration diketahui
│  EXPIRATION   │  Pre-warming cache dilakukan (prefetch)
└────┬──────────┘
     │
┌────▼──────────┐
│  REVOKED      │  Akses tidak lagi diizinkan
│  (emergency)  │  Cache dihapus segera
└────┬──────────┘
     │
┌────▼──────────┐
│  EXPIRED      │  TTL habis, auto dihapus
│  (TTL elapsed)│  Cache dihapus
└────┬──────────┘
     │
┌────▼──────────┐
│  ARCHIVED     │  Disimpan untuk compliance/audit
│  (read-only)  │
└───────────────┘
```

---

## Stage 1: CREATE

### Saat Kunci Dibuat

**Lokasi**: Di upstream KMS (Key Management Service) external

**Event**:
```
Client membuat kunci baru via KMS API
  → KMS returns: key_id = "user_123:key_456"
                 key_material = [256 random bits]
                 created_at = 2024-03-20T10:00:00Z
                 expires_at = 2025-03-20T10:00:00Z (1 year TTL)
```

**PSKC State**:
- Kunci TIDAK di cache (new)
- Model registry TIDAK tahu tentang key_id ini
- First access akan trigger KMS fetch + cache populate

### First Access After Create

```
Client: GET /keys/access?key_id=user_123:key_456

PSKC:
  1. Check cache (L1) → MISS
  2. Check cache (L2/Redis) → MISS
  3. Fetch from KMS → HIT (key exists, returns material)
  4. Decrypt material (using PSKC DEK)
  5. Store to L1 + L2 cache with TTL
  6. Return plaintext to client
  7. Schedule prefetch job for predicted next keys
  8. Log access to data collector
```

**Cache TTL for New Key**:
- Default: MIN(key.expires_at - now, 24 hours)
- Example: Key expires in 1 year → cache TTL = 24 hours
- Example: Key expires in 2 hours → cache TTL = 2 hours

---

## Stage 2: ACTIVE

### Normal Operation

Kunci dalam status ACTIVE berarti:
- KMS reports status = "ACTIVE"
- Key dapat di-cache (TTL ditetapkan)
- Prefetch worker dapat predict akses ke key ini
- ML model dapat track access patterns

### Monitoring During Active

```
Every 5 minutes (monitoring loop):
  1. Check KMS for all cached keys: GET /keys/{key_id}/metadata
  2. If status changed → trigger event handler
  3. Log to audit: {timestamp, key_id, status, access_count}

Metrics tracked:
  - access_count: Berapa kali diakses dalam 24 jam terakhir
  - cache_hit_count: Berapa kali dari cache vs KMS
  - last_accessed: Kapan terakhir diakses
  - confidence_in_next_access: ML prediction confidence
```

### Conditional Prefetch During Active

```
During active-normal state, prefetch worker:

1. Collects access patterns (from data_collector)
   Example: user_123:key_456 accessed
            → 80% time followed by user_123:key_789
            → prefetch user_123:key_789

2. If key nearing expiration (< 24 hours):
   - Increase prefetch aggressiveness
   - Mark key as "WARM" in cache (keep longer)
   - Log warning: "Key user_123:key_456 expires in 23h"

3. Maintain cache warmth:
   - Touch cache entry every 4 hours (refresh TTL)
   - Prevent premature eviction
   - Example: Accessed once, then silent → evicted after 24h
             But if key used 100x/day → keep warm in cache
```

---

## Stage 3: ROTATE

### Rotation Initiation

**Trigger**: Manual rotate command atau scheduled rotation policy

```
Client: POST /keys/rotate
  Request: { key_id: "user_123:key_456" }
  
Response:
  {
    "old_key": {
      "key_id": "user_123:key_456#v1",
      "status": "ROTATED",
      "retired_at": "2024-03-20T10:01:00Z",
      "retire_after": "2024-03-27T10:01:00Z"  # 7 days grace period
    },
    "new_key": {
      "key_id": "user_123:key_456#v2",
      "status": "ACTIVE",
      "created_at": "2024-03-20T10:01:00Z"
    }
  }
```

### Cache Invalidation During Rotation

**PSKC Internal Handling**:

```
ROTATION EVENT DETECTED (via monitoring loop or webhook):

1. Old Key Handling:
   - Mark old_key as "ROTATED" (status flag)
   - Remove old_key from L1 cache immediately
   - Remove old_key from L2 (Redis) immediately
   - Audit log: {timestamp, key_id, event: "ROTATED"}

2. Grace Period:
   - Old key NOT fetched fresh (stale entries rejected)
   - But old_key value RETAINED in audit storage for tracing
   - No new prefetch for old_key
   - If client requests old_key → return ERROR "Key rotated, use new version"

3. New Key Warming:
   - Pre-fetch new_key from KMS immediately
   - Store in L1 + L2 cache
   - Run updated ML model (retrained with latest patterns)
   - Prefetch "next keys" using new prediction context
   - Audit log: {timestamp, key_id: "user_123:key_456#v2", event: "CREATED"}

4. Scheduled Cleanup:
   - After grace period expires (7 days):
     - Remove old_key from audit storage (compress to archive)
     - Remove old_key from monitoring lists
     - Mark as "RETIRED"
```

### Rotation Example

```
Time: 2024-03-20 10:00:00 - Key created
  user_123:key_456#v1 ACTIVE
  Cached: v1 material in L1+L2

Time: 2024-03-20 10:01:00 - Rotation triggered
  Monitoring detects: v1 → ROTATED, v2 → ACTIVE
  
  PSKC Actions:
  ├─ Remove v1 from L1 cache
  ├─ Remove v1 from L2 (Redis)
  ├─ Fetch v2 from KMS
  ├─ Store v2 in L1+L2
  └─ Predictive prefetch v2+related keys

Time: 2024-03-22 - Client request v1
  Client: GET /keys/access?key_id=user_123:key_456#v1
  
  PSKC Response:
  ├─ Check L1 → MISS (removed)
  ├─ Check L2 → MISS (removed)
  ├─ Check KMS → ERROR: "Key rotated, use v2"
  └─ Return error to client

Time: 2024-03-27 10:01:00 - Grace period expires
  PSKC Actions:
  ├─ Archive v1 metadata → long-term storage
  ├─ Delete v1 from monitoring
  └─ Completion log
```

### Cache Coherence During Rotation

**Problem**: Multiple clients might have cached stale v1

**Solution**:
1. Invalidation broadcast via Redis pubsub channel
2. Each API server subscriber receives: "Invalidate user_123:key_456#v1"
3. Servers remove v1 from L1 local cache
4. Next request for v1 → serve error (not found in L2)

```python
# In redis-pubsub listener (runs in each API server):
redis_pubsub.subscribe("pskc:cache_invalidation")

# When rotation event arrives:
message = {
    "event": "KEY_ROTATED",
    "old_key_id": "user_123:key_456#v1",
    "new_key_id": "user_123:key_456#v2",
    "timestamp": 1711003260
}

# Clear L1 cache
local_cache.delete(message['old_key_id'])

# Result: All servers synchronized within milliseconds
```

---

## Stage 4: SCHEDULED EXPIRATION

### Expiration Tracking

**Configuration**:
```env
KEY_EXPIRATION_WARNING_DAYS=30       # Warn when < 30 days left
KEY_EXPIRATION_WARM_DAYS=7           # Warm cache when < 7 days
KEY_EXPIRATION_CRITICAL_HOURS=1      # Critical when < 1 hour
```

### Pre-Expiration Actions

**7 Days Before Expiration**:
```
Monitoring detects: key expires in 7 days

Actions:
  1. Audit log: "Key approaching expiration (7 days)"
  2. Increase cache TTL to maximum (keep warm)
  3. Set prefetch priority = HIGH
  4. If HMAC-based: Start rotation planning
  5. Alert ops team: "user_123:key_456 expires 2024-03-27"
```

**1 Hour Before Expiration**:
```
Actions:
  1. Audit log: CRITICAL - "Key expires in 1 hour"
  2. Request new key rotation (if auto-rotation enabled)
  3. Alert monitoring: "CRITICAL: user_123:key_456 expires soon"
  4. Increase prefetch aggressiveness (predict 30 keys, not 10)
  5. Mark as "DO_NOT_EVICT" (even if idle, keep in cache)
```

---

## Stage 5: REVOCATION (Emergency)

### Revocation Trigger

**Scenarios**:
- Key compromise detected
- Unauthorized access suspected
- Client explicitly revokes
- Security policy change

**Immediate Actions**:

```
Event: Revocation triggered

1. Timestamp: Now
   Audit log: {event: "REVOKED", timestamp, reason}

2. KMS Update:
   Key.status = "REVOKED"
   Key.revoked_at = Now()
   Key.revoked_reason = "Security incident"

3. PSKC Cache Invalidation:
   a) Remove from L1 (all API servers) → pubsub broadcast
   b) Remove from L2 (Redis) → DEL key
   c) Invalidate from data_collector (no more prefetch)
   d) Update monitoring (skip from health checks)

4. Downstream Handling:
   - Any in-flight requests: complete if < 100ms, else abort
   - Pending prefetch jobs: remove from queue
   - New requests: immediately return "Key revoked"

5. Audit Trail:
   Log all: when, who, why, impact (# of services affected)
```

### Revocation Example

```
Time: 2024-03-20 10:30:00 - Normal + Active
  user_123:key_456 accessed 1000 times today
  Cached everywhere, prefetch running

Time: 2024-03-20 10:30:45 - Revocation triggered
  Security team discovers unauthorized access
  Issue: /keys/revoke?key_id=user_123:key_456
  Reason: "Policy violation: too many accesses"

PSKC Actions (< 100ms):
  1. Broadcast pubsub: "Revoke user_123:key_456"
  2. DEL from Redis L2
  3. Each server: delete from L1 local cache
  4. DataCollector: stop collecting patterns for this key
  5. Prefetch worker: dequeue any pending jobs for this key
  6. ModelRegistry: mark key as "revoked" (no more retraining with it)

Impact:
  - All clients using old cached value: stale (won't know for ~100ms)
  - New requests after 100ms: immediately return "Key revoked"
  - Audit: 2500 accesses revoked, avg client delay 10ms

Time: 2024-03-20 10:31:00
  All servers synchronized, key fully revoked
  Monitoring alerts: "Critical revocation completed"
```

---

## Stage 6: EXPIRATION (Natural TTL)

### Expiration Process

**Timing**:
```
Key.expires_at = 2024-03-20T10:00:00Z

Time: 2024-03-20 09:59:00 (1 minute before expiry)
  If key in cache:
    - Cache TTL = 1 minute
    - Last access possible

Time: 2024-03-20 10:00:00 (Expiry time)
  Cache entry TTL ≤ 0 → evicted from L1+L2
  KMS reports: status = "EXPIRED"

Time: 2024-03-20 10:00:01 (After expiry)
  Client request: GET /keys/access?key_id=user_123:key_456
  
  PSKC:
    1. L1 cache: MISS (evicted)
    2. L2 cache: MISS (evicted)
    3. KMS fetch: ERROR "Key expired, cannot access"
    4. Return error to client
```

### Automatic Cleanup Post-Expiration

```
Cleanup Job (runs daily at 2 AM):
  1. Scan data/models/checksums.json
  2. For each key: check if expired
  3. If expired:
     a) Remove audit logs older than retention_days (default 90 days)
     b) Archive to cold storage
     c) Update monitoring
     d) Log cleanup event

Example:
  Key expired 90 days ago
  → Move audit trail to archive storage
  → Free up space in active audit logs
  → Keep in ModelRegistry for historical accuracy (can retrain)
```

---

## Stage 7: ARCHIVED (Compliance)

### Archive Storage

**Purpose**: Long-term retention for compliance/audit

**Storage Location**: `data/processed/archived_keys/`

**Format**:
```json
{
  "key_id": "user_123:key_456",
  "status": "ARCHIVED",
  "created_at": "2023-03-20T10:00:00Z",
  "expires_at": "2024-03-20T10:00:00Z",
  "revoked_at": null,
  "archived_at": "2024-06-20T02:00:00Z",
  "access_count": 15430,
  "cache_hit_count": 14200,
  "cache_hit_rate": 0.919,
  "last_accessed": "2024-03-20T10:59:00Z",
  "audit_log_hash": "sha256:xxxxx",
  "metadata": {
    "algorithm": "AES-256-GCM",
    "owner": "user_123",
    "service_tags": ["api-prod", "worker-batch"]
  }
}
```

**Retention Rules**:
```
Compliance retention = MAX(90 days, regulatory_requirement)
  - Default: 90 days after expiration
  - HIPAA: 6 years
  - GDPR: Right to be forgotten (delete after 30 days)
  - PCI-DSS: 1 year
  
After retention expires: Permanently delete from archive
```

**Access to Archived Keys**:
- Read-only (no new access)
- Audit trail only (for compliance inquiries)
- Cannot use in active PSKC operations

---

## Complete State Diagram

```
                    ┌─────────────┐
                    │   CREATED   │
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │   ACTIVE    │
                    └──────┬──────┘
             ┌─────────────┼─────────────┐
             │             │             │
          (rotate)    (expire TTL)   (revoke)
             │             │             │
             ▼             ▼             ▼
        ┌─────────┐  ┌──────────┐  ┌─────────┐
        │ ROTATED │  │ EXPIRED  │  │ REVOKED │
        └────┬────┘  └────┬─────┘  └────┬────┘
             │             │             │
          (7 days)     (archive)    (archive)
             │             │             │
             ▼             ▼             ▼
        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │ RETIRED  │  │ ARCHIVED │  │ ARCHIVED │
        └────┬─────┘  └────┬─────┘  └────┬─────┘
             │             │             │
          (forget)    (90+ days)    (90+ days)
             │             │             │
             └─────────────▼─────────────┘
                       │
                       ▼
               ┌────────────────┐
               │   FORGOTTEN    │
               │ (deleted)      │
               └────────────────┘
```

---

## Cache Coherence Protocol

### Cache Invalidation Broadcast

When key state changes (rotation, revocation, expiration):

```
1. Central event → Redis pubsub
2. All subscribers (API servers) → receive event
3. Local L1 cache → immediate delete
4. L2 (Redis) → immediate delete

Channel: "pskc:cache_invalidation"

Event format:
{
  "event_type": "ROTATE|REVOKE|EXPIRE",
  "key_id": "user_123:key_456",
  "timestamp": 1711003260,
  "new_version": "user_123:key_456#v2" (if ROTATE)
}

Handler in each API server:
def on_cache_invalidation(event):
  local_cache.delete(event['key_id'])
  # Also delete related prefetch jobs
  if event['event_type'] == 'REVOKE':
    prefetch_queue.remove_jobs_for_key(event['key_id'])
  elif event['event_type'] == 'ROTATE':
    # Maybe keep old version briefly for compatibility
    pass
```

### Propagation Latency

```
Rotation event at KMS API:         t=0000ms
Monitoring detects change:         t=0050ms
PSKC processes event:              t=0075ms
Redis pubsub broadcast:            t=0080ms
Each server receives:              t=0085-0150ms
  (depends on network latency to Redis)

Total time to full propagation: ~150ms

During this window:
  Some clients might still serve cached stale value
  Solution: Clients implement TTL, refresh after X minutes
```

---

## Key Versioning

### Key ID Format

```
Versionless key:
  "user_123:key_456"              # Latest version (should fail after rotate)

Versioned key (after rotation):
  "user_123:key_456#v1"           # Explicit version 1 (ROTATED)
  "user_123:key_456#v2"           # Explicit version 2 (ACTIVE)
  "user_123:key_456#v3"           # Explicit version 3 (if rotated again)

Version numbering:
  - Starts at v1 (first creation)
  - Increments on each rotation
  - Versions before current always <= N-1

KMS versioning API:
  GET /keys/user_123:key_456       # Returns latest version (v2)
  GET /keys/user_123:key_456/v1    # Returns old version (ERROR after grace)
  GET /keys/user_123:key_456/v2    # Returns current version
```

### Handling Version References

```python
# Client-side code example:

# Option 1: Use latest (automatic upgrade on rotation)
key = api.get_key("user_123:key_456")
# Returns v1, then v2 after rotation, then v3, etc.

# Option 2: Pin version (explicit)
key = api.get_key("user_123:key_456#v1")
# Always returns v1, error if rotated and grace period ended

# PSKC caching:
# Versioned access BYPASSES prefetch  (fixed, no predict needed)
# Versionless access USES prefetch    (dynamic prediction)
```

---

## Monitoring & Auditing

### Key State Monitoring

```python
# Runs every 5 minutes

def monitor_key_states():
    all_keys = get_monitored_keys()  # From KMS or config
    
    for key in all_keys:
        kms_metadata = kms_api.get_metadata(key.id)
        
        # Check state
        if kms_metadata.status == "ACTIVE":
            ttl_remaining = kms_metadata.expires_at - now()
            
            if ttl_remaining < timedelta(days=7):
                log.warning(f"Key {key.id} expires in {ttl_remaining}")
                trigger_prefetch_warmup(key.id)
            
            elif ttl_remaining < timedelta(hours=1):
                log.critical(f"Key {key.id} expires in {ttl_remaining}")
                alert_ops("CRITICAL_KEY_EXPIRATION", key.id)
        
        elif kms_metadata.status == "ROTATED":
            # Already handled by cache invalidation
            track_rotation_metrics()
        
        elif kms_metadata.status == "REVOKED":
            log.error(f"Key {key.id} was revoked")
            alert_security("KEY_REVOKED", key.id)
        
        # Update metrics
        prometheus.gauge(
            'key_state_active',
            value=count_active_keys()
        )
```

### Audit Logging

Every state change logged:

```
2024-03-20T10:00:00Z [INFO]  KEY_CREATE
  key_id: user_123:key_456
  ttl_days: 365
  owner_service: api-prod

2024-03-20T10:30:00Z [INFO]  KEY_ACCESS_CACHED
  key_id: user_123:key_456
  cache_layer: L1
  client_ip: 10.0.1.5

2024-03-20T10:31:00Z [WARN]  KEY_ROTATED
  old_key_id: user_123:key_456#v1
  new_key_id: user_123:key_456#v2
  action: cache_invalidate

2024-03-20T10:31:45Z [CRIT]  KEY_REVOKED
  key_id: user_123:key_456#v2
  reason: security_incident
  action: emergency_revoke
```

---

## Related Components

- **KeyFetcher**: `src/security/key_fetcher.py` - Fetches from KMS
- **SecureCacheManager**: `src/cache/secure_cache.py` - Manages L1+L2
- **DataCollector**: `src/ml/data_collector.py` - Tracks access patterns
- **ModelRegistry**: `src/ml/model_registry.py` - Stores trained models
- **AuditLogger**: `src/observability/audit_logger.py` - Compliance logging
