# Security Architecture

Dokumen ini menjelaskan layering keamanan komprehensif dalam PSKC, termasuk enkripsi, audit logging, intrusion detection, dan compliance.

## Ikhtisar Keamanan

PSKC mengimplementasikan defense-in-depth dengan multiple layers:

```
┌─────────────────────────────────────────────────────────┐
│                SECURITY LAYERING                        │
└─────────────────────────────────────────────────────────┘

LAYER 1: NETWORK BOUNDARY
  ├─ TLS 1.3 transport encryption
  ├─ Client authentication (mTLS)
  └─ Rate limiting → prevent brute force

LAYER 2: REQUEST PROCESSING
  ├─ Input validation (key format, access type)
  ├─ Authorization checks (client can access key?)
  └─ Intrusion detection (anomaly detection)

LAYER 3: CRYPTOGRAPHIC
  ├─ FIPS 140-2 module (approved algorithms)
  ├─ AES-256-GCM encryption (at rest + in transit)
  ├─ HKDF key derivation
  └─ HMAC authentication tags

LAYER 4: AUDIT & COMPLIANCE
  ├─ Tamper-evident audit logging (hash chain)
  ├─ Access control policy enforcement
  ├─ Key rotation tracking
  └─ Compliance reporting (PCI-DSS, HIPAA, GDPR)

LAYER 5: DATA INTEGRITY
  ├─ Checksum verification (SHA-256)
  ├─ Signature verification (HMAC-SHA256)
  └─ Model artifact signing (resistance to tampering)
```

---

## FIPS 140-2 Compliance

### FipsCryptographicModule

**File**: `src/security/fips_cryptographic_module.py`

**Purpose**: Provide Federal Information Processing Standards (FIPS) approved cryptographic operations

### Approved Algorithms

```python
class FipsCryptographicModule:
    """
    Only uses FIPS 140-2 Level 1 approved algorithms
    """
    
    APPROVED_ALGORITHMS = {
        'aes': {
            'key_sizes': [128, 192, 256],  # bits
            'modes': ['GCM', 'CBC'],       # AES-GCM preferred
            'approved': True
        },
        'sha': {
            'variants': ['SHA-256', 'SHA-384', 'SHA-512'],
            'approved': True
        },
        'hmac': {
            'hash_functions': ['SHA-256', 'SHA-384'],
            'approved': True
        },
        'hkdf': {
            'hash_function': 'SHA-256',
            'approved': True
        },
        'rng': {
            'type': 'CSPRNG',  # Cryptographically secure
            'approved': True
        }
    }
```

### Encryption Key Hierarchy

```
┌────────────────────────────────────┐
│ Master Key (KEK)                   │
│ - Stored in HSM or secure vault    │
│ - Rotated annually                 │
│ - Never stored on disk             │
└──────────────┬─────────────────────┘
               │
               ▼
┌────────────────────────────────────┐
│ Data Encryption Key (DEK)          │
│ - Derived from KEK via HKDF        │
│ - 256-bit AES key                  │
│ - Changed per key_id               │
└──────────────┬─────────────────────┘
               │
      ┌────────┴──────────┐
      │                   │
      ▼                   ▼
┌──────────────┐  ┌──────────────┐
│ Cache Layer  │  │ Audit Logs   │
│ (L1+L2)      │  │ (write)      │
│ Encrypted    │  │ Encrypted    │
└──────────────┘  └──────────────┘
```

### HKDF Key Derivation

```python
def derive_dek_from_kek(master_key, key_id, context):
    """
    HKDF-SHA256: Derive unique DEK for each key_id
    
    master_key: 32 bytes (256-bit KEK from secure storage)
    key_id: "user_123:key_456"
    context: Additional context (service_id, environment, etc.)
    """
    
    # Info parameter uniquely identifies this derivation
    info = f"pskc:dek:{key_id}:{context}".encode()
    
    # HKDF: Extract + Expand
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,  # 256-bit DEK
        salt=None,  # Can use random salt for additional security
        info=info,
        backend=default_backend()
    )
    
    dek = hkdf.derive(master_key)
    
    return dek
    # Each key_id gets unique, deterministic DEK
    # Impossible to derive without master_key
```

### Cryptographic Random Number Generation

```python
def generate_random_bytes(length):
    """FIPS approved: use os.urandom (backed by system CSPRNG)"""
    
    return os.urandom(length)
    
    # On Linux: /dev/urandom (backed by SHA-3 + ChaCha20)
    # On Windows: CryptGenRandom (Microsoft Crypto API)
    # Never use Python's random module!
```

---

## Encryption at Rest

### Cache Encryption (L1 + L2)

**Problem**: If disk stolen or Redis compromised, key material exposed

**Solution**: Encrypt before storing

```python
class SecureCacheManager:
    """Encrypt key material in cache"""
    
    def set(self, key_id, key_material, ttl_seconds):
        """
        1. Derive DEK from key_id
        2. Encrypt plaintext material
        3. Store ciphertext in cache
        """
        
        # Derive DEK
        dek = self.derive_dek(key_id)
        
        # Generate random IV (12 bytes for GCM)
        iv = os.urandom(12)
        
        # Encrypt with AES-256-GCM
        cipher = Cipher(
            AES(dek),
            GCM(iv),
            backend=default_backend()
        )
        encryptor = cipher.encryptor()
        
        # Add AAD (Additional Authenticated Data): key_id prevents misuse
        encryptor.authenticate_additional_data(key_id.encode())
        
        # Encrypt
        ciphertext = encryptor.update(key_material) + encryptor.finalize()
        
        # Package: [IV || tag || ciphertext]
        tag = encryptor.tag  # 16 bytes authentication tag
        package = iv + tag + ciphertext
        
        # Store in L1 and L2
        self.l1_local_cache[key_id] = {
            'package': package,
            'created_at': time.time(),
            'ttl': ttl_seconds
        }
        
        redis_client.setex(
            f"pskc:cache:{key_id}",
            ttl_seconds,
            package
        )
    
    def get(self, key_id):
        """
        1. Try L1 (local)
        2. Fallback to L2 (Redis)
        3. Decrypt
        """
        
        # Try L1 first
        if key_id in self.l1_local_cache:
            package = self.l1_local_cache[key_id]['package']
            cache_hit = 'L1'
        else:
            # Try L2
            package = redis_client.get(f"pskc:cache:{key_id}")
            cache_hit = 'L2' if package else 'MISS'
        
        if package is None:
            return None, cache_hit
        
        # Decrypt
        dek = self.derive_dek(key_id)
        
        # Extract components
        iv = package[:12]
        tag = package[12:28]
        ciphertext = package[28:]
        
        # Decrypt with GCM
        cipher = Cipher(
            AES(dek),
            GCM(iv, tag),
            backend=default_backend()
        )
        decryptor = cipher.decryptor()
        
        # Verify AAD
        decryptor.authenticate_additional_data(key_id.encode())
        
        try:
            plaintext = decryptor.update(ciphertext) + decryptor.finalize()
            return plaintext, cache_hit
        except cryptography.exceptions.InvalidTag:
            raise SecurityError(f"Cache corruption detected for {key_id}")
```

### Audit Log Encryption

**Problem**: Audit logs contain sensitive access patterns

**Solution**: Encrypt before writing to storage

```python
class AuditLogger:
    """Tamper-evident audit logging with encryption"""
    
    def __init__(self):
        self.master_key = load_master_key_from_vault()
        self.log_chain_hash = None  # For tamper detection
    
    def log_access(self, event):
        """
        event = {
            'timestamp': 1711003260,
            'key_id': 'user_123:key_456',
            'action': 'ACCESS',
            'client_ip': '10.0.1.5',
            'result': 'SUCCESS'
        }
        """
        
        # 1. Create hash chain entry (tamper detection)
        event_json = json.dumps(event, sort_keys=True)
        
        # Hash current entry with previous hash
        if self.log_chain_hash is None:
            self.log_chain_hash = hashlib.sha256(b"GENESIS").hexdigest()
        
        entry_hash = hashlib.sha256(
            (self.log_chain_hash + event_json).encode()
        ).hexdigest()
        
        # 2. Encrypt before storing
        dek = HKDF(self.master_key, context=f"audit:{event['key_id']}")
        
        iv = os.urandom(12)
        cipher_text = encrypt_aes_gcm(event_json.encode(), dek, iv)
        
        # 3. Write to immutable log
        log_entry = {
            'timestamp': event['timestamp'],
            'entry_hash': entry_hash,
            'previous_hash': self.log_chain_hash,
            'cipher_text': cipher_text,
            'iv': iv.hex(),
            'tag': tag.hex()
        }
        
        # Append to audit log file (immutable append-only)
        with open('data/audit.log', 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
        
        # Update chain hash
        self.log_chain_hash = entry_hash
        
        # Also: send to external system (syslog, Splunk, etc.)
        self.send_to_remote_log_server(log_entry)
    
    def verify_audit_integrity(self):
        """
        Check: Has audit log been tampered with?
        """
        
        previous_hash = "GENESIS"
        
        with open('data/audit.log', 'r') as f:
            for line in f:
                entry = json.loads(line)
                
                # Recompute: should match entry_hash
                event_json = json.dumps(entry['event'], sort_keys=True)
                computed_hash = hashlib.sha256(
                    (previous_hash + event_json).encode()
                ).hexdigest()
                
                if computed_hash != entry['entry_hash']:
                    raise SecurityError(f"Audit log tampered! Hash mismatch at {entry['timestamp']}")
                
                if entry['previous_hash'] != previous_hash:
                    raise SecurityError(f"Audit log tampered! Chain broken at {entry['timestamp']}")
                
                previous_hash = entry['entry_hash']
        
        return True  # All good
```

---

## Intrusion Detection System (IDS)

### Real-Time Anomaly Detection

**Goal**: Detect unusual access patterns (potential compromises)

```python
class IntrusionDetectionSystem:
    """
    Monitors real-time traffic for anomalies
    Uses statistical models to detect deviations
    """
    
    def __init__(self):
        # Baseline statistics (from historical data)
        self.baseline_stats = {
            'access_rate': {'mean': 100, 'std': 20},      # req/sec
            'unique_keys_per_user': {'mean': 50, 'std': 15},
            'avg_latency': {'mean': 5, 'std': 2},         # ms
            'cache_hit_rate': {'mean': 0.85, 'std': 0.05},
            'failed_access_rate': {'mean': 0.01, 'std': 0.005}
        }
        
        self.alert_threshold = 2.5  # Z-score
    
    def check_anomalies(self, current_metrics):
        """
        current_metrics = {
            'access_rate': 500,      # req/sec (massive spike!)
            'unique_keys': 5000,     # (accessing 100x more keys than usual)
            'cache_hit_rate': 0.20,  # (much lower than baseline 0.85)
        }
        """
        
        anomalies = []
        
        for metric, value in current_metrics.items():
            baseline = self.baseline_stats[metric]
            
            # Z-score: how many std deviations from mean?
            z_score = abs(value - baseline['mean']) / baseline['std']
            
            if z_score > self.alert_threshold:
                anomalies.append({
                    'metric': metric,
                    'value': value,
                    'baseline': baseline['mean'],
                    'z_score': z_score,
                    'severity': 'HIGH' if z_score > 4 else 'MEDIUM'
                })
        
        return anomalies
    
    def handle_anomaly(self, anomaly):
        """
        When anomaly detected: take action
        """
        
        if anomaly['severity'] == 'HIGH':
            # Immediate action: throttle or block
            logger.critical(f"HIGH SEVERITY ANOMALY: {anomaly}")
            
            # Action: rate limit client
            self.apply_rate_limit(client_ip=get_current_client_ip())
            
            # Alert security team
            send_alert_to_security_team(anomaly)
            
            # Log for forensics
            audit_logger.log_event({
                'event': 'INTRUSION_DETECTED',
                'anomaly': anomaly
            })
        
        elif anomaly['severity'] == 'MEDIUM':
            # Increase monitoring
            logger.warning(f"MEDIUM ANOMALY: {anomaly}")
            self.increase_monitoring_frequency()
```

### Example Anomaly: Bulk Key Access

```
Baseline: User typically accesses 3-5 keys per session
Observed: User accessing 1000 keys in 5 minute window

Detection:
└─ Z-score = (1000 - 50) / 15 = 63 (massive!)
└─ Alert: HIGH
└─ Action: Block user, investigate credential compromise
```

### Example Anomaly: Low Cache Hit Rate

```
Baseline: Cache hit rate 85% ± 5%
Observed: Cache hit rate dropped to 10%

Possible causes:
├─ Cache evicted (too much traffic)
├─ Attacker accessing random keys (wants traffic analysis)
└─ Legitimate: keys rotated, old versions deleted

Detection:
└─ Z-score = abs(0.10 - 0.85) / 0.05 = 15 (anomalous)
└─ Alert: MEDIUM
└─ Action: Investigate; check for key rotation events
```

---

## Access Control

### Key-Level Permissions

**Problem**: Need to prevent unauthorized clients from accessing keys

**Solution**: Authorization check before cache access

```python
class AccessControl:
    """
    Enforce: "Who can access what keys?"
    """
    
    def __init__(self):
        # Load access control policy
        self.acl = load_acl_policy()
        # Format: {service_id: {client_group: [allowed_key_patterns]}}
    
    def can_access(self, client_id, key_id, action='read'):
        """
        Check: Does client have permission for this key + action?
        """
        
        service_id = client_id.split(':')[0]  # Extract service from client ID
        
        # Find policy for this service
        if service_id not in self.acl:
            return False, "Service not in ACL"
        
        service_policy = self.acl[service_id]
        
        # Check if client group allowed for this key pattern
        for allowed_pattern in service_policy.get(client_id, []):
            if fnmatch.fnmatch(key_id, allowed_pattern):
                # Pattern matches
                return True, "Access allowed"
        
        return False, f"Client {client_id} not allowed to access {key_id}"
    
    def enforce_access_control(self, request, handler):
        """
        Middleware: Check every request
        """
        
        client_id = request.headers.get('X-Client-ID')
        key_id = request.path_params.get('key_id')
        action = request.method  # GET=read, POST=write
        
        allowed, reason = self.can_access(client_id, key_id, action)
        
        if not allowed:
            audit_logger.log_event({
                'event': 'ACCESS_DENIED',
                'client_id': client_id,
                'key_id': key_id,
                'reason': reason
            })
            
            raise HTTPException(
                status_code=403,
                detail=f"Access denied: {reason}"
            )
        
        # Access allowed, continue
        return handler(request)
```

### ACL Format

```json
{
  "api-prod": {
    "client:mobile-app": [
      "user_*:key_*",      // Wildcard patterns
      "system:config_*"
    ],
    "client:web-app": [
      "user_*:key_*",
      "!user_admin:*"      // Negative pattern (deny)
    ],
    "client:batch-job": [
      "user_*:*",
      "system:*"
    ]
  },
  "api-testing": {
    "client:test-runner": [
      "test_*:*"           // Only test keys
    ]
  }
}
```

---

## Certificate Management (mTLS)

### Client Authentication

**Problem**: How do we know client is legitimate (not impersonator)?

**Solution**: Mutual TLS (mTLS) with client certificates

```python
from fastapi import FastAPI
from fastapi.security import HTTPBearer
import ssl

# Server configuration (in main.py):
ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)

# Load server certificate + key
ssl_context.load_cert_chain(
    certfile='certs/pskc-server.crt',
    keyfile='certs/pskc-server.key'
)

# Load trusted client CAs
ssl_context.load_verify_locations('certs/client-ca.crt')

# Require + verify client certificate
ssl_context.verify_mode = ssl.CERT_REQUIRED

# Start HTTPS server
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=443,
        ssl_keyfile="certs/pskc-server.key",
        ssl_certfile="certs/pskc-server.crt",
        ssl_version=ssl.PROTOCOL_TLSv1_3,
        ssl_cert_reqs=ssl.CERT_REQUIRED,
        ssl_ca_certs="certs/client-ca.crt"
    )

# Extract client identity from certificate
def get_client_from_cert(request: Request) -> str:
    """Extract subject CN from client certificate"""
    
    # FastAPI middleware to extract cert
    try:
        cert = request.client.certificate  # Requires SSL context setup
        subject = dict(x[0] for x in cert['subject'])
        client_cn = subject['commonName']
        return client_cn
    except Exception:
        return None
```

### Certificate Rotation

```
Certificate Lifecycle:
  Issued:       2024-03-01
  Valid:        365 days
  Expires:      2025-03-01
  Renewal:      2025-02-01 (30 days before expiry)
  Grace period: 14 days after expiry

Rotation process (every 90 days minimum):
  1. Generate new CSR (certificate signing request)
  2. Sign with Root CA
  3. Deploy new cert (rolling update)
  4. Old cert remains valid (grace period)
  5. Clients auto-update (or manually rotate)
```

---

## Secret Management

### Master Key Storage

**Requirement**: Master key must be protected at rest + in transit

```python
class SecretVault:
    """
    Interface to external secret management (HashiCorp Vault, AWS Secrets Manager, etc.)
    """
    
    def __init__(self):
        self.vault_client = load_vault_client()
    
    def get_master_key(self):
        """
        Retrieve master key from secure vault
        Never store on disk unencrypted
        """
        
        secret = self.vault_client.read_secret_version(
            path='pskc/master-key'
        )
        
        key_bytes = bytes.fromhex(secret['data']['value'])
        
        return key_bytes
    
    def rotate_master_key(self):
        """
        Periodic master key rotation (annually)
        """
        
        old_key = self.get_master_key()
        
        # Generate new master key
        new_key = os.urandom(32)  # 256-bit
        
        # 1. Re-encrypt all cache with new key
        self._reencrypt_cache(old_key, new_key)
        
        # 2. Re-encrypt audit logs
        self._reencrypt_audit_logs(old_key, new_key)
        
        # 3. Store new key in vault
        self.vault_client.update_secret(
            path='pskc/master-key',
            value=new_key.hex()
        )
        
        # 4. Mark rotation complete
        audit_logger.log_event({
            'event': 'MASTER_KEY_ROTATED',
            'timestamp': time.time()
        })
```

---

## Compliance Requirements

### PCI-DSS (Payment Card Industry)

**Requirement 3.4**: Encryption of stored cardholder data

```yaml
PSKC Compliance:
  ✅ Requirement 3.2.1: AES-256-GCM encryption (FIPS approved)
  ✅ Requirement 3.5: Key management procedures
     - Keys stored in secure vault (not on disk)
     - Keys rotated annually (or quarterly)
  ✅ Requirement 10: Logging + audit trails
     - Tamper-evident audit logs
     - Hash chain prevents modification
  ✅ Requirement 12: Access control policy
     - client: authentication (mTLS)
     - Authorization: ACL-based
```

### HIPAA (Health Insurance Portability)

**Requirement**: Encryption of patient health information (PHI)

```yaml
PSKC Compliance:
  ✅ Technical Safeguards: Encryption
     - AES-256-GCM at rest
     - TLS 1.3 in transit
  ✅ Access Controls
     - Client authentication (mTLS)
     - Authorization (ACL)
     - Audit logging (immutable)
  ✅ Audit Controls
     - Comprehensive audit logs
     - Integrity verification
     - Retention (6+ years)
```

### GDPR (General Data Protection Regulation)

**Right to be Forgotten**: Ability to delete personal data

```python
def gdpr_delete_user_data(user_id):
    """
    Right to be forgotten: delete all user data
    """
    
    # 1. Find all keys associated with user
    user_keys = find_keys_by_owner(user_id)
    # Result: [user_123:key_456, user_123:key_789, ...]
    
    # 2. Delete from cache
    for key_id in user_keys:
        cache_manager.delete(key_id)  # L1 + L2
    
    # 3. Delete from KMS
    for key_id in user_keys:
        kms.revoke_key(key_id)
    
    # 4. Delete from audit logs (after retention)
    # Note: Can't delete audit logs immediately (compliance)
    # But can anonymize personal identifiers
    anonymize_audit_logs_for_user(user_id)
    
    # 5. Verify deletion
    assert len(find_keys_by_owner(user_id)) == 0
    
    # 6. Log deletion event
    audit_logger.log_event({
        'event': 'GDPR_DELETE_REQUEST_PROCESSED',
        'user_id': user_id,
        'keys_deleted': len(user_keys)
    })
```

---

## Security Monitoring

### Real-Time Detection Rules

```yaml
Security Rules (Prometheus):
  - alert: UnauthorizedAccessAttempt
    expr: increase(access_denied_total[5m]) > 10
    action: Block client IP, alert security team
  
  - alert: HighFailureRate
    expr: rate(request_errors_total[5m]) > 0.05  # 5%
    action: Investigate code issue or attack
  
  - alert: CertificateExpiringSoon
    expr: (ssl_certificate_expiry_timestamp - time()) < (30*24*3600)
    action: Rotate certificate
  
  - alert: AuditLogTamper
    expr: audit_integrity_check_failures_total > 0
    action: CRITICAL - Investigate immediately
  
  - alert: KeyRotationFailed
    expr: increase(key_rotation_failures_total[1h]) > 0
    action: High priority - keys at risk
```

---

## Incident Response

### Breach Detected

```
Timeline: Attacker compromised client certificate

T+0m: IDS detects anomaly (high access rate)
  Action:
  ├─ Block client IP
  ├─ Alert security team (PagerDuty)
  └─ Audit log entry

T+5m: Security team investigates
  Action:
  ├─ Review access logs for compromised client
  ├─ Identify keys accessed (scope of breach)
  ├─ Check if cache encrypted (good!)
  └─ Revoke client certificate

T+10m: Contain breach
  Action:
  ├─ Revoke all accessed keys (older versions in grace period)
  ├─ Force key rotation
  ├─ Notify downstream systems
  └─ Block related IPs

T+30m: Recovery
  Action:
  ├─ Generate new client certificates
  ├─ Restart affected services
  ├─ Verify audit logs still intact
  └─ Prepare incident report

T+4h: Post-incident
  Action:
  ├─ Root cause analysis
  ├─ Implement preventive measures
  ├─ Regulatory notification (if required)
  └─ Document lessons learned
```

### Audit Log Compromise

**Scenario**: Attacker tries to modify audit logs to hide malicious activity

**Detection**:
```python
# Tamper detection via hash chain
verification_result = audit_logger.verify_audit_integrity()

if not verification_result:
    # Hash mismatch detected → log was modified
    logger.critical("AUDIT LOG TAMPERING DETECTED!")
    
    # Actions:
    # 1. Isolate system (don't trust it)
    # 2. Alert security + compliance teams
    # 3. Restore from backup (external log server)
    # 4. Forensic analysis
```

---

## Configuration

### Security Settings

```env
# TLS
TLS_VERSION=1.3
TLS_CERT_PATH=certs/pskc-server.crt
TLS_KEY_PATH=certs/pskc-server.key
TLS_CLIENT_CA_PATH=certs/client-ca.crt
TLS_REQUIRE_CLIENT_CERT=true

# Encryption
ENCRYPTION_ALGORITHM=AES-256-GCM
MASTER_KEY_SOURCE=vault             # vault|hsm|env
MASTER_KEY_ROTATION_DAYS=365

# Intrusion Detection
IDS_ENABLED=true
IDS_ANOMALY_THRESHOLD_ZSCORE=2.5
IDS_CHECK_INTERVAL_SECONDS=60

# Audit Logging
AUDIT_LOG_ENABLED=true
AUDIT_LOG_PATH=data/audit.log
AUDIT_LOG_ENCRYPTION=true
AUDIT_LOG_RETENTION_DAYS=2555        # 7 years

# Rate Limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_PER_SECOND=1000           # Per client
RATE_LIMIT_BURST=10000               # Per minute
RATE_LIMIT_BLOCK_DURATION_SECONDS=3600

# Compliance
COMPLIANCE_LEVEL=pci-dss             # pci-dss|hipaa|gdpr
CERTIFICATE_ROTATION_DAYS=90
```

---

## Testing Security

### Security Test Suite

```python
# tests/test_security_comprehensive.py

def test_encryption_at_rest():
    """Verify: encrypted cache can't be read without DEK"""
    
    # 1. Store encrypted value
    cache.set('test_key', b'secret_value', ttl=3600)
    
    # 2. Read raw bytes from Redis
    raw_bytes = redis.get('pskc:cache:test_key')
    
    # 3. Verify not plaintext (no "secret_value" visible)
    assert b'secret_value' not in raw_bytes
    
    # 4. Decrypt with correct DEK → success
    plaintext = cache.decrypt(raw_bytes, 'test_key')
    assert plaintext == b'secret_value'
    
    # 5. Decrypt with wrong DEK → failure
    with pytest.raises(SecurityError):
        cache.decrypt(raw_bytes, 'wrong_key_id')

def test_audit_log_integrity():
    """Verify: audit log can't be tampered"""
    
    # Log 10 events
    for i in range(10):
        audit_logger.log_event({
            'event': f'TEST_{i}',
            'index': i
        })
    
    # Verify integrity while file intact
    assert audit_logger.verify_audit_integrity() == True
    
    # Tamper: change one event in file
    with open('data/audit.log', 'r') as f:
        lines = f.readlines()
    
    # Modify middle entry
    entry = json.loads(lines[5])
    entry['cipher_text'] = 'TAMPERED'
    lines[5] = json.dumps(entry) + '\n'
    
    with open('data/audit.log', 'w') as f:
        f.writelines(lines)
    
    # Verify integrity check now fails
    with pytest.raises(SecurityError):
        audit_logger.verify_audit_integrity()

def test_access_control_enforcement():
    """Verify: clients only access allowed keys"""
    
    # Client api-prod/mobile-app only allowed user_* keys
    acl = AccessControl()
    
    # Allowed access
    assert acl.can_access('api-prod/mobile-app', 'user_123/key_1')[0] == True
    
    # Denied access
    assert acl.can_access('api-prod/mobile-app', 'admin/secret')[0] == False
    
    # Verify middleware rejects non-allowed
    with pytest.raises(HTTPException) as exc:
        access_control_middleware(
            request=MockRequest(client_id='api-prod/mobile-app', key_id='admin/secret'),
            handler=lambda x: x
        )
    
    assert exc.value.status_code == 403  # Forbidden
```

---

## Related Components

- **FipsCryptographicModule**: `src/security/fips_cryptographic_module.py`
- **AuditLogger**: `src/observability/audit_logger.py`
- **IntrusionDetectionSystem**: `src/security/intrusion_detection.py`
- **SecureCacheManager**: `src/cache/secure_cache_manager.py`
- **KeyFetcher**: `src/security/key_fetcher.py`
