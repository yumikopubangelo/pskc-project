# ============================================================
# PSKC — Security Audit Trail (FILE BARU)
# src/security/security_audit.py
# ============================================================
#
# File ini melengkapi audit_logger.py yang sudah ada dengan
# fokus khusus pada:
#
#   1. Tamper-evident audit log — setiap entry di-chain dengan
#      HMAC dari entry sebelumnya (mirip blockchain sederhana).
#      Jika log dimodifikasi, chain akan break.
#
#   2. Security event severity classification — CRITICAL events
#      langsung trigger alert, bukan hanya dicatat.
#
#   3. Audit log integrity verification — script untuk memverifikasi
#      bahwa log chain tidak rusak/dimodifikasi.
#
#   4. Structured log format (JSONL) — kompatibel dengan SIEM tools
#      seperti Splunk, Elastic, Datadog.
# ============================================================

import os
import json
import hmac
import time
import hashlib
import secrets
import threading
from enum import Enum
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


# ============================================================
# Event Classification
# ============================================================

class SecurityEventType(Enum):
    # Authentication events
    AUTH_SUCCESS          = "auth.success"
    AUTH_FAILURE          = "auth.failure"
    AUTH_BRUTE_FORCE      = "auth.brute_force"
    AUTH_CREDENTIAL_STUFFING = "auth.credential_stuffing"

    # Key access events
    KEY_ACCESS_HIT        = "key.cache_hit"
    KEY_ACCESS_MISS       = "key.cache_miss"
    KEY_ACCESS_DENIED     = "key.access_denied"
    KEY_REVOKED           = "key.revoked"
    KEY_ROTATION          = "key.rotation"
    KEY_FETCH_KMS         = "key.fetch_kms"

    # Encryption events
    ENCRYPTION_OK         = "crypto.encrypt_ok"
    DECRYPTION_OK         = "crypto.decrypt_ok"
    DECRYPTION_FAILED     = "crypto.decrypt_failed"  # Tag mismatch = tampering!
    KEY_DERIVATION        = "crypto.key_derivation"

    # Intrusion / attack events
    RATE_LIMIT_HIT        = "attack.rate_limit"
    PATH_TRAVERSAL        = "attack.path_traversal"
    CACHE_POISONING       = "attack.cache_poisoning"
    REPLAY_ATTACK         = "attack.replay"
    ANOMALOUS_PATTERN     = "attack.anomalous_pattern"
    IP_BLOCKED            = "attack.ip_blocked"
    HOST_HEADER_INJECTION = "attack.host_injection"

    # System events
    SERVICE_START         = "system.start"
    SERVICE_STOP          = "system.stop"
    CONFIG_CHANGE         = "system.config_change"
    AUDIT_INTEGRITY_CHECK = "system.audit_integrity_check"


class Severity(Enum):
    INFO     = "INFO"
    WARNING  = "WARNING"
    HIGH     = "HIGH"
    CRITICAL = "CRITICAL"


# Mapping event → severity
EVENT_SEVERITY: Dict[SecurityEventType, Severity] = {
    SecurityEventType.AUTH_SUCCESS:              Severity.INFO,
    SecurityEventType.AUTH_FAILURE:              Severity.WARNING,
    SecurityEventType.AUTH_BRUTE_FORCE:          Severity.CRITICAL,
    SecurityEventType.AUTH_CREDENTIAL_STUFFING:  Severity.CRITICAL,
    SecurityEventType.KEY_ACCESS_HIT:            Severity.INFO,
    SecurityEventType.KEY_ACCESS_MISS:           Severity.INFO,
    SecurityEventType.KEY_ACCESS_DENIED:         Severity.HIGH,
    SecurityEventType.KEY_REVOKED:               Severity.HIGH,
    SecurityEventType.KEY_ROTATION:              Severity.HIGH,
    SecurityEventType.KEY_FETCH_KMS:             Severity.INFO,
    SecurityEventType.ENCRYPTION_OK:             Severity.INFO,
    SecurityEventType.DECRYPTION_OK:             Severity.INFO,
    SecurityEventType.DECRYPTION_FAILED:         Severity.CRITICAL,
    SecurityEventType.KEY_DERIVATION:            Severity.INFO,
    SecurityEventType.RATE_LIMIT_HIT:            Severity.WARNING,
    SecurityEventType.PATH_TRAVERSAL:            Severity.CRITICAL,
    SecurityEventType.CACHE_POISONING:           Severity.CRITICAL,
    SecurityEventType.REPLAY_ATTACK:             Severity.CRITICAL,
    SecurityEventType.ANOMALOUS_PATTERN:         Severity.HIGH,
    SecurityEventType.IP_BLOCKED:                Severity.HIGH,
    SecurityEventType.HOST_HEADER_INJECTION:     Severity.HIGH,
    SecurityEventType.SERVICE_START:             Severity.INFO,
    SecurityEventType.SERVICE_STOP:              Severity.INFO,
    SecurityEventType.CONFIG_CHANGE:             Severity.HIGH,
    SecurityEventType.AUDIT_INTEGRITY_CHECK:     Severity.INFO,
}


# ============================================================
# Audit Entry
# ============================================================

@dataclass
class AuditEntry:
    """Single audit log entry."""
    event_type:  str
    severity:    str
    timestamp:   str
    service_id:  Optional[str]
    ip_address:  Optional[str]
    key_id:      Optional[str]
    request_id:  Optional[str]
    details:     Dict[str, Any]
    sequence_no: int
    prev_hmac:   str          # HMAC of previous entry — tamper detection chain
    entry_hmac:  str = ""     # HMAC of this entry (computed after creation)

    def to_dict(self) -> Dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


# ============================================================
# Tamper-Evident Audit Logger
# ============================================================

class TamperEvidentAuditLogger:
    """
    Append-only audit log dengan HMAC chaining.

    Cara kerja chain:
        entry[0].prev_hmac = HMAC("genesis")
        entry[0].entry_hmac = HMAC(entry[0].content || entry[0].prev_hmac)
        entry[1].prev_hmac = entry[0].entry_hmac
        entry[1].entry_hmac = HMAC(entry[1].content || entry[1].prev_hmac)
        ...

    Jika ada yang memodifikasi entry[0], semua entry setelahnya akan
    memiliki chain yang broken saat di-verify.

    Log key (untuk HMAC) di-derive dari CACHE_ENCRYPTION_KEY via HKDF
    dengan info context berbeda — jadi berbeda dari encryption key.
    """

    GENESIS_HMAC = "0" * 64  # Starting sentinel

    def __init__(
        self,
        log_path: str = "data/security/audit.jsonl",
        alert_callback=None,
        max_memory_entries: int = 10_000,
    ):
        self._log_path = log_path
        self._alert_callback = alert_callback
        self._max_memory_entries = max_memory_entries

        self._sequence_no = 0
        self._last_hmac = self.GENESIS_HMAC
        self._lock = threading.Lock()

        # In-memory ring buffer untuk recent events (query tanpa disk I/O)
        self._memory_entries: List[AuditEntry] = []

        # Derive log signing key
        self._signing_key = self._derive_signing_key()

        # Ensure log directory exists
        os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)

        # Load last HMAC dari file jika ada (untuk chain continuity)
        self._load_last_state()

        logger.info(f"TamperEvidentAuditLogger initialized: {log_path}")

    def _derive_signing_key(self) -> bytes:
        """Derive HMAC signing key dari encryption key via HKDF."""
        try:
            from src.security.encryption import KeyDerivation
            from config.settings import settings

            raw = settings.cache_encryption_key or secrets.token_hex(32)
            return KeyDerivation.derive_from_secret(
                raw,
                info="pskc-audit-log-signing-key-v1",
            )
        except Exception:
            # Fallback ke random key (tidak persistent — chain restart)
            logger.warning("Could not derive signing key from settings — using random key")
            return secrets.token_bytes(32)

    def _compute_hmac(self, content: str) -> str:
        """Compute HMAC-SHA256 dari content string."""
        return hmac.new(
            self._signing_key,
            content.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _load_last_state(self) -> None:
        """Load last sequence_no dan last_hmac dari log file."""
        if not os.path.exists(self._log_path):
            return

        try:
            last_line = None
            with open(self._log_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        last_line = line

            if last_line:
                entry = json.loads(last_line)
                self._sequence_no = entry.get("sequence_no", 0) + 1
                self._last_hmac = entry.get("entry_hmac", self.GENESIS_HMAC)
                logger.debug(
                    f"Resumed audit chain at seq={self._sequence_no}, "
                    f"last_hmac={self._last_hmac[:16]}..."
                )
        except Exception as e:
            logger.warning(f"Could not load last audit state: {e}")

    def log(
        self,
        event_type: SecurityEventType,
        service_id: str = None,
        ip_address: str = None,
        key_id: str = None,
        request_id: str = None,
        details: Dict[str, Any] = None,
    ) -> AuditEntry:
        """
        Write a tamper-evident audit entry.

        Returns:
            The created AuditEntry.
        """
        severity = EVENT_SEVERITY.get(event_type, Severity.INFO)

        with self._lock:
            seq = self._sequence_no
            prev_hmac = self._last_hmac

            entry = AuditEntry(
                event_type=event_type.value,
                severity=severity.value,
                timestamp=datetime.now(timezone.utc).isoformat(),
                service_id=service_id,
                ip_address=ip_address,
                key_id=key_id,
                request_id=request_id,
                details=details or {},
                sequence_no=seq,
                prev_hmac=prev_hmac,
                entry_hmac="",
            )

            # Compute HMAC over entry content + prev_hmac
            content = json.dumps({
                k: v for k, v in entry.to_dict().items() if k != "entry_hmac"
            }, sort_keys=True)
            entry.entry_hmac = self._compute_hmac(content + prev_hmac)

            # Update chain state
            self._sequence_no += 1
            self._last_hmac = entry.entry_hmac

            # Write to disk
            self._write_entry(entry)

            # Add to memory buffer
            self._memory_entries.append(entry)
            if len(self._memory_entries) > self._max_memory_entries:
                self._memory_entries.pop(0)

        # Log to Python logger (outside lock)
        log_fn = {
            Severity.INFO:     logger.info,
            Severity.WARNING:  logger.warning,
            Severity.HIGH:     logger.error,
            Severity.CRITICAL: logger.critical,
        }.get(severity, logger.info)

        log_fn(
            f"[AUDIT] [{severity.value}] {event_type.value} | "
            f"service={service_id} ip={ip_address} key={key_id} | "
            f"seq={seq}"
        )

        # Trigger alert callback untuk HIGH/CRITICAL
        if severity in (Severity.HIGH, Severity.CRITICAL) and self._alert_callback:
            try:
                self._alert_callback(entry)
            except Exception as e:
                logger.error(f"Alert callback failed: {e}")

        return entry

    def _write_entry(self, entry: AuditEntry) -> None:
        """Append entry ke log file."""
        try:
            with open(self._log_path, "a") as f:
                f.write(entry.to_json() + "\n")
        except Exception as e:
            logger.error(f"Failed to write audit entry: {e}")

    # ----------------------------------------------------------
    # Integrity Verification
    # ----------------------------------------------------------

    def verify_integrity(self) -> Dict[str, Any]:
        """
        Verifikasi bahwa audit log chain tidak rusak.

        Returns:
            Report dengan status dan detail jika ada anomali.
        """
        self.log(
            SecurityEventType.AUDIT_INTEGRITY_CHECK,
            details={"log_path": self._log_path},
        )

        if not os.path.exists(self._log_path):
            return {"status": "no_log_file", "entries_checked": 0}

        entries_checked = 0
        errors = []
        last_hmac = self.GENESIS_HMAC

        try:
            with open(self._log_path, "r") as f:
                for line_no, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        entry_dict = json.loads(line)
                    except json.JSONDecodeError as e:
                        errors.append({
                            "line": line_no,
                            "error": f"Invalid JSON: {e}",
                        })
                        continue

                    # Verify sequence continuity
                    expected_seq = entries_checked
                    actual_seq = entry_dict.get("sequence_no", -1)
                    if actual_seq != expected_seq:
                        errors.append({
                            "line": line_no,
                            "seq": actual_seq,
                            "expected_seq": expected_seq,
                            "error": "Sequence number gap — possible entry deletion",
                        })

                    # Verify prev_hmac chain
                    prev_hmac_in_entry = entry_dict.get("prev_hmac", "")
                    if not hmac.compare_digest(prev_hmac_in_entry, last_hmac):
                        errors.append({
                            "line": line_no,
                            "seq": actual_seq,
                            "error": "HMAC chain broken — entry may have been modified or deleted",
                        })

                    # Verify entry_hmac
                    stored_hmac = entry_dict.get("entry_hmac", "")
                    check_content = json.dumps(
                        {k: v for k, v in entry_dict.items() if k != "entry_hmac"},
                        sort_keys=True,
                    )
                    expected_hmac = self._compute_hmac(check_content + prev_hmac_in_entry)

                    if not hmac.compare_digest(stored_hmac, expected_hmac):
                        errors.append({
                            "line": line_no,
                            "seq": actual_seq,
                            "error": "Entry HMAC mismatch — entry content has been tampered",
                        })

                    last_hmac = stored_hmac
                    entries_checked += 1

        except Exception as e:
            return {"status": "error", "error": str(e), "entries_checked": entries_checked}

        status = "ok" if not errors else "INTEGRITY_VIOLATION"

        if errors:
            logger.critical(
                f"AUDIT LOG INTEGRITY VIOLATION: {len(errors)} anomalies found! "
                f"Log file may have been tampered with."
            )

        return {
            "status":          status,
            "entries_checked": entries_checked,
            "errors_found":    len(errors),
            "errors":          errors[:10],  # Limit output
            "log_path":        self._log_path,
        }

    # ----------------------------------------------------------
    # Query Interface
    # ----------------------------------------------------------

    def get_recent_events(
        self,
        limit: int = 100,
        severity_filter: Optional[Severity] = None,
        event_type_filter: Optional[SecurityEventType] = None,
    ) -> List[Dict]:
        """Query recent events dari memory buffer."""
        with self._lock:
            entries = list(reversed(self._memory_entries))

        if severity_filter:
            entries = [e for e in entries if e.severity == severity_filter.value]
        if event_type_filter:
            entries = [e for e in entries if e.event_type == event_type_filter.value]

        return [e.to_dict() for e in entries[:limit]]

    def get_stats(self) -> Dict[str, Any]:
        """Summary statistics dari memory buffer."""
        with self._lock:
            entries = list(self._memory_entries)

        from collections import Counter
        severity_counts = Counter(e.severity for e in entries)
        event_counts = Counter(e.event_type for e in entries)

        return {
            "total_in_memory": len(entries),
            "sequence_no":     self._sequence_no,
            "log_path":        self._log_path,
            "severity_breakdown": dict(severity_counts),
            "top_events": dict(event_counts.most_common(10)),
        }


# ============================================================
# Convenience shortcut methods
# ============================================================

class SecurityAudit:
    """
    High-level wrapper dengan shortcut methods untuk event-event yang umum.
    Ini yang seharusnya dipakai oleh module lain (bukan langsung TamperEvidentAuditLogger).
    """

    def __init__(self, logger_instance: TamperEvidentAuditLogger = None):
        self._logger = logger_instance or get_security_audit()

    def auth_success(self, service_id: str, ip: str, request_id: str = None):
        self._logger.log(SecurityEventType.AUTH_SUCCESS, service_id=service_id,
                         ip_address=ip, request_id=request_id)

    def auth_failure(self, service_id: str, ip: str, reason: str, request_id: str = None):
        self._logger.log(SecurityEventType.AUTH_FAILURE, service_id=service_id,
                         ip_address=ip, request_id=request_id,
                         details={"reason": reason})

    def brute_force_detected(self, service_id: str, ip: str, attempt_count: int):
        self._logger.log(SecurityEventType.AUTH_BRUTE_FORCE, service_id=service_id,
                         ip_address=ip, details={"attempt_count": attempt_count})

    def decryption_failed(self, key_id: str, service_id: str = None):
        self._logger.log(SecurityEventType.DECRYPTION_FAILED, service_id=service_id,
                         key_id=key_id,
                         details={"warning": "Possible tampering or wrong key"})

    def key_access_denied(self, key_id: str, service_id: str, ip: str, reason: str):
        self._logger.log(SecurityEventType.KEY_ACCESS_DENIED, service_id=service_id,
                         ip_address=ip, key_id=key_id, details={"reason": reason})

    def rate_limit_hit(self, ip: str, path: str, count: int):
        self._logger.log(SecurityEventType.RATE_LIMIT_HIT, ip_address=ip,
                         details={"path": path, "request_count": count})

    def path_traversal(self, ip: str, path: str, request_id: str = None):
        self._logger.log(SecurityEventType.PATH_TRAVERSAL, ip_address=ip,
                         request_id=request_id, details={"attempted_path": path})

    def cache_poisoning(self, key_id: str, pattern: str, ip: str = None):
        self._logger.log(SecurityEventType.CACHE_POISONING, ip_address=ip,
                         key_id=key_id, details={"pattern": pattern})

    def replay_attack(self, nonce: str, ip: str, service_id: str = None):
        self._logger.log(SecurityEventType.REPLAY_ATTACK, service_id=service_id,
                         ip_address=ip, details={"nonce": nonce[:16] + "..."})

    def key_rotation(self, rotation_id: str, entries_rotated: int):
        self._logger.log(SecurityEventType.KEY_ROTATION,
                         details={"rotation_id": rotation_id,
                                  "entries_rotated": entries_rotated})

    def verify_integrity(self) -> Dict:
        return self._logger.verify_integrity()

    def get_stats(self) -> Dict:
        return self._logger.get_stats()


# ============================================================
# Global Singleton
# ============================================================

_audit_instance: Optional[TamperEvidentAuditLogger] = None
_audit_lock = threading.Lock()


def get_security_audit() -> TamperEvidentAuditLogger:
    global _audit_instance
    if _audit_instance is None:
        with _audit_lock:
            if _audit_instance is None:
                _audit_instance = TamperEvidentAuditLogger()
    return _audit_instance