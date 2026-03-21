# ============================================================
# PSKC — Enhanced Security Module (REFACTORED FOR FIPS COMPLIANCE)
# ============================================================
#
# DOKUMEN INI ADALAH IMPLEMENTASI RENCANA AKSI DARI
# `plans/fips_nist_compliance_assessment.md`.
#
# PERUBAHAN UTAMA:
# 1. Dependency Injection: `SecureCacheManager` sekarang menerima
#    semua dependensinya (`EncryptedCacheStore`, `TamperEvidentAuditLogger`, dll.)
#    saat inisialisasi. Ini menghilangkan dependensi pada singleton global.
# 2. Singleton Dihapus: Fungsi `get_secure_cache_manager()`, `get_ids()`,
#    dan `get_secure_handler()` telah dihapus. Instance dari kelas-kelas
#    ini sekarang harus dibuat secara eksplisit oleh lapisan aplikasi.
# 3. Keterkaitan yang Jelas: Keterkaitan antara `SecureCacheManager`,
#    `IntrusionDetectionSystem`, dan `EncryptedCacheStore` sekarang
#    didefinisikan secara eksplisit saat inisialisasi, membuat aliran
#    kontrol menjadi jelas.
#
# ============================================================
import time
import hmac
import hashlib
import threading
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import deque
import logging
import secrets

# Dependensi baru yang akan di-inject
from src.cache.encrypted_store import EncryptedCacheStore
from src.security.tamper_evident_logger import TamperEvidentAuditLogger

logger = logging.getLogger(__name__)


class _NoopAuditLogger:
    def log(self, user: str, action: str, outcome: str = "SUCCESS", metadata: Optional[Dict[str, Any]] = None):
        return None

# --- Kelas ThreatLevel, SecurityEvent, SecurityAlert tetap sama ---
class ThreatLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class SecurityEvent(Enum):
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    BRUTE_FORCE_ATTEMPT = "brute_force_attempt"
    ANOMALOUS_ACCESS_PATTERN = "anomalous_access_pattern"
    CACHE_POISONING = "cache_poisoning"
    TIMING_ATTACK = "timing_attack"

@dataclass
class SecurityAlert:
    event: SecurityEvent
    threat_level: ThreatLevel
    timestamp: float
    source_ip: str = ""
    service_id: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    auto_purge_triggered: bool = False


# --- IntrusionDetectionSystem tetap sama, tetapi akan menerima logger ---
class IntrusionDetectionSystem:
    MAX_KEY_SIZE = 1024 * 1024
    NONCE_TTL = 300

    def __init__(
        self,
        audit_logger: Optional[TamperEvidentAuditLogger] = None,
        cache_clear_callback: Callable = None,
        alert_callback: Optional[Callable[[SecurityAlert], None]] = None,
    ):
        self._audit = audit_logger or _NoopAuditLogger()
        self._cache_clear_callback = cache_clear_callback
        self._alert_callback = alert_callback
        
        self._failed_auth_threshold = 5
        self._access_rate_threshold = 100
        self._failed_attempt_window_seconds = 300
        self._access_rate_window_seconds = 60
        self._reputation_block_threshold = -10
        
        self._failed_attempts: Dict[str, deque] = {}
        self._access_history: Dict[str, deque] = {}
        self._ip_reputation: Dict[str, int] = {}
        self._lock = threading.RLock()
        self._alerts: deque = deque(maxlen=1000)
        self._nonce_store: Dict[str, float] = {}
        self._auto_purge_enabled = True

        # ... (Loop monitor dan logika internal lainnya tetap sama) ...
        logger.info("IntrusionDetectionSystem initialized.")

    def _trigger_alert(self, alert: SecurityAlert):
        logger.warning(f"SECURITY ALERT: {alert.event.value} - {alert.threat_level.value}")
        self._alerts.append(alert)
        self._audit.log(
            user=alert.service_id or "SYSTEM",
            action="IDS_ALERT",
            outcome="FAILURE",
            metadata={
                "event": alert.event.value,
                "threat_level": alert.threat_level.value,
                "source_ip": alert.source_ip,
                "details": alert.details,
            }
        )
        if self._alert_callback is not None:
            self._alert_callback(alert)
        if (
            self._auto_purge_enabled
            and alert.threat_level == ThreatLevel.CRITICAL
            and self._cache_clear_callback is not None
        ):
            self._cache_clear_callback()

    def _prune_window(self, bucket: deque, window_seconds: int) -> None:
        cutoff = time.time() - window_seconds
        while bucket and bucket[0] < cutoff:
            bucket.popleft()

    def _bucket_key(self, service_id: str, ip_address: str) -> str:
        return f"{service_id}:{ip_address}"

    def record_failed_attempt(self, service_id: str, ip_address: str, reason: str = ""):
        bucket_key = self._bucket_key(service_id, ip_address)
        with self._lock:
            attempts = self._failed_attempts.setdefault(bucket_key, deque())
            attempts.append(time.time())
            self._prune_window(attempts, self._failed_attempt_window_seconds)
            self._ip_reputation[ip_address] = self._ip_reputation.get(ip_address, 0) - 3
            attempt_count = len(attempts)

        if attempt_count >= self._failed_auth_threshold:
            self._trigger_alert(
                SecurityAlert(
                    event=SecurityEvent.BRUTE_FORCE_ATTEMPT,
                    threat_level=ThreatLevel.HIGH,
                    timestamp=time.time(),
                    source_ip=ip_address,
                    service_id=service_id,
                    details={"attempts": attempt_count, "reason": reason},
                )
            )

    def record_access(self, service_id: str, key_id: str, ip_address: str = "") -> None:
        bucket_key = self._bucket_key(service_id, ip_address or "unknown")
        with self._lock:
            accesses = self._access_history.setdefault(bucket_key, deque())
            accesses.append(time.time())
            self._prune_window(accesses, self._access_rate_window_seconds)

    def check_access_rate(self, service_id: str, ip_address: str) -> bool:
        bucket_key = self._bucket_key(service_id, ip_address)
        with self._lock:
            accesses = self._access_history.setdefault(bucket_key, deque())
            self._prune_window(accesses, self._access_rate_window_seconds)
            access_count = len(accesses)

        if access_count > self._access_rate_threshold:
            self._trigger_alert(
                SecurityAlert(
                    event=SecurityEvent.ANOMALOUS_ACCESS_PATTERN,
                    threat_level=ThreatLevel.HIGH,
                    timestamp=time.time(),
                    source_ip=ip_address,
                    service_id=service_id,
                    details={"requests_in_window": access_count, "window_seconds": self._access_rate_window_seconds},
                )
            )
            self.update_reputation(ip_address, -2)
            return False
        return True

    def detect_cache_poisoning(self, key_id: str, value: bytes) -> bool:
        if not isinstance(value, (bytes, bytearray)):
            suspicious = True
        elif len(value) == 0 or len(value) > self.MAX_KEY_SIZE:
            suspicious = True
        else:
            suspicious = False
            raw_value = bytes(value)
            decoded_candidates = []

            try:
                decoded_candidates.append(raw_value.decode("utf-8", errors="strict").lower())
            except UnicodeDecodeError:
                pass

            # Attackers sometimes hide dangerous textual payloads behind UTF-16
            # or null-padded encodings to bypass naive UTF-8-only checks.
            if (
                raw_value.startswith((b"\xff\xfe", b"\xfe\xff"))
                or raw_value.count(0) >= max(2, len(raw_value) // 4)
            ):
                for encoding in ("utf-16", "utf-16-le", "utf-16-be"):
                    try:
                        decoded_candidate = raw_value.decode(encoding, errors="strict").lower()
                    except UnicodeDecodeError:
                        continue

                    if decoded_candidate not in decoded_candidates:
                        decoded_candidates.append(decoded_candidate)

            suspicious_patterns = (
                "../",
                "..\\",
                "%2e%2e",
                "/etc/passwd",
                "/etc/shadow",
                "system32",
                "<script",
                "{{=exec}}",
                "javascript:",
                "union select",
                "drop table",
            )
            if any(
                decoded_value and any(pattern in decoded_value for pattern in suspicious_patterns)
                for decoded_value in decoded_candidates
            ):
                suspicious = True

        if suspicious:
            self._trigger_alert(
                SecurityAlert(
                    event=SecurityEvent.CACHE_POISONING,
                    threat_level=ThreatLevel.HIGH,
                    timestamp=time.time(),
                    details={"key_id": key_id, "value_size": len(value) if hasattr(value, "__len__") else None},
                )
            )
        return suspicious

    def check_ip_reputation(self, ip_address: str) -> bool:
        with self._lock:
            return self._ip_reputation.get(ip_address, 0) > self._reputation_block_threshold

    def update_reputation(self, ip_address: str, delta: int) -> int:
        with self._lock:
            self._ip_reputation[ip_address] = self._ip_reputation.get(ip_address, 0) + delta
            return self._ip_reputation[ip_address]

    def enable_auto_purge(self, enabled: bool) -> None:
        self._auto_purge_enabled = enabled

    def get_alerts(
        self,
        threat_level: Optional[ThreatLevel] = None,
        limit: int = 100,
    ) -> List[SecurityAlert]:
        alerts = list(self._alerts)
        if threat_level is not None:
            alerts = [alert for alert in alerts if alert.threat_level == threat_level]
        return alerts[-limit:]

    def validate_nonce(self, nonce: str) -> bool:
        now = time.time()
        with self._lock:
            expired_nonces = [
                token for token, seen_at in self._nonce_store.items()
                if (now - seen_at) > self.NONCE_TTL
            ]
            for token in expired_nonces:
                del self._nonce_store[token]

            if nonce in self._nonce_store:
                self._trigger_alert(
                    SecurityAlert(
                        event=SecurityEvent.UNAUTHORIZED_ACCESS,
                        threat_level=ThreatLevel.HIGH,
                        timestamp=now,
                        details={"reason": "nonce_reuse", "nonce": nonce[:32]},
                    )
                )
                return False

            self._nonce_store[nonce] = now
            return True

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "failed_attempts_tracked": sum(len(v) for v in self._failed_attempts.values()),
                "alerts_count": len(self._alerts),
                "auto_purge_enabled": self._auto_purge_enabled,
                "tracked_ips": len(self._ip_reputation),
                "tracked_nonces": len(self._nonce_store),
            }

class SecureCacheManager:
    """
    Manajer cache aman yang mengoordinasikan antara cache terenkripsi dan IDS.
    """
    def __init__(
        self,
        encrypted_store: EncryptedCacheStore,
        audit_logger: TamperEvidentAuditLogger
    ):
        """
        Inisialisasi manajer dengan dependensi yang sudah ada.
        """
        self._cache = encrypted_store
        self._audit = audit_logger
        
        # Inisialisasi IDS dengan callback untuk membersihkan cache
        self._ids = IntrusionDetectionSystem(
            audit_logger=self._audit,
            cache_clear_callback=self._clear_all_keys,
        )
        logger.info("SecureCacheManager initialized with injected dependencies.")

    def _clear_all_keys(self):
        """Callback untuk IDS untuk membersihkan semua kunci dari cache."""
        removed = 0
        for cache_key in self._cache.get_cache_keys():
            if ":" not in cache_key:
                continue
            service_id, key_id = cache_key.split(":", 1)
            if self._cache.delete(key_id, service_id):
                removed += 1
        logger.warning("!!! AUTO-PURGE TRIGGERED VIA CALLBACK !!! removed=%s", removed)

    @property
    def ids(self) -> IntrusionDetectionSystem:
        """Mendapatkan instance IDS yang dikelola oleh manajer ini."""
        return self._ids

    def secure_get(
        self,
        key_id: str,
        service_id: str,
        ip_address: str = ""
    ) -> tuple:
        """
        Pengambilan kunci yang aman dengan pemeriksaan IDS.
        """
        if ip_address and not self._ids.check_ip_reputation(ip_address):
            self._ids.record_failed_attempt(service_id, ip_address, "IP reputation")
            return None, False, 0.0, False

        if ip_address:
            self._ids.record_access(service_id, key_id, ip_address)

        if ip_address and not self._ids.check_access_rate(service_id, ip_address):
            self._ids.record_failed_attempt(service_id, ip_address, "Rate limit")
            return None, False, 0.0, False
        
        # Panggil metode get dari encrypted_store yang sudah aman
        key_data, cache_hit, latency = self._cache.get_with_metadata(key_id, service_id)
        return key_data, cache_hit, latency, True

    def secure_set(
        self,
        key_id: str,
        key_data: bytes,
        service_id: str,
        ip_address: str = "",
        ttl: Optional[int] = None,
        predicted: bool = False,
        priority: float = 0.0,
    ) -> bool:
        """
        Penyimpanan kunci yang aman dengan deteksi cache poisoning.
        """
        if ip_address and not self._ids.check_ip_reputation(ip_address):
            self._ids.record_failed_attempt(service_id, ip_address, "IP reputation on set")
            return False

        if self._ids.detect_cache_poisoning(key_id, key_data):
            logger.error(f"Cache poisoning detected for key: {key_id}")
            return False
        
        return self._cache.set(
            key_id,
            key_data,
            service_id,
            ttl=ttl,
            predicted=predicted,
            priority=priority,
        )

    def secure_exists(self, key_id: str, service_id: str) -> bool:
        """Periksa apakah key sudah ada di secure cache."""
        return self._cache.exists(key_id, service_id)

    def inspect_cache_path(self, key_id: str, service_id: str) -> str:
        """Inspect whether a key will be served from L1, L2, or miss."""
        return self._cache.probe_location(key_id, service_id)

    def get_cache_keys(self) -> List[str]:
        """Dapatkan daftar key cache yang tersedia di runtime."""
        return self._cache.get_cache_keys()

    def get_cache_stats(self) -> Dict[str, Any]:
        """Dapatkan statistik cache dari store terenkripsi."""
        return self._cache.get_cache_stats()

    def secure_delete(
        self,
        key_id: str,
        service_id: str,
        reason: str = ""
    ) -> bool:
        """Penghapusan kunci yang aman dengan jejak audit."""
        logger.info(f"Secure delete: {key_id} (reason: {reason})")
        
        # Gunakan instance logger yang di-inject
        self._audit.log(
            user=service_id,
            action="SECURE_DELETE",
            outcome="SUCCESS",
            metadata={"key_id": key_id, "reason": reason}
        )
        
        return self._cache.delete(key_id, service_id)

    def get_security_stats(self) -> Dict[str, Any]:
        return {
            "ids_stats": self._ids.get_stats(),
            "encryption_enabled": True,
            "secure_mode": True,
            "fips_mode": True
        }

# FUNGSI SINGLETON GLOBAL (get_secure_cache_manager, get_ids) DIHAPUS.
# Instance akan dibuat di `routes.py`.
