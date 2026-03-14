# ============================================================
# PSKC — Key Verifier Module
# Verify cryptographic keys with expiry handling
# ============================================================
import hashlib
import hmac
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
import logging
import json

logger = logging.getLogger(__name__)


class VerificationResult(Enum):
    """Key verification results"""
    VALID = "valid"
    INVALID = "invalid"
    EXPIRED = "expired"
    NOT_FOUND = "not_found"
    INACTIVE = "inactive"
    ERROR = "error"


class KeyStatus(Enum):
    """Key status states"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass
class KeyMetadata:
    """
    Key metadata with full lifecycle tracking.
    
    Attributes:
        created_at: ISO 8601 timestamp when key was created
        expiry_date: ISO 8601 timestamp when key expires (None = never expires)
        last_used: ISO 8601 timestamp of last key usage
        status: Current key status (active/inactive/expired/revoked)
        max_age_seconds: Maximum key age in seconds (for auto-expiry)
    """
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expiry_date: Optional[str] = None
    last_used: Optional[str] = None
    status: str = "active"
    max_age_seconds: Optional[int] = None
    version: int = 1
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return asdict(self)
    
    def to_json(self) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict())
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'KeyMetadata':
        """Create from dictionary"""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
    
    @classmethod
    def from_json(cls, json_str: str) -> 'KeyMetadata':
        """Create from JSON string"""
        try:
            data = json.loads(json_str)
            return cls.from_dict(data)
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"Failed to parse key metadata: {e}")
            raise ValueError(f"Invalid metadata JSON: {e}")


@dataclass
class VerificationContext:
    """Context for key verification"""
    key_id: str
    service_id: str
    timestamp: float
    nonce: Optional[str] = None
    signature: Optional[str] = None


@dataclass
class VerificationReport:
    """Detailed verification report"""
    result: VerificationResult
    key_id: str
    latency_ms: float
    timestamp: float
    details: str = ""
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class KeyVerifier:
    """
    Verifies cryptographic keys and signatures.
    Provides multiple verification methods with proper expiry checking.
    """
    
    def __init__(self):
        # Verification metrics
        self._total_verifications = 0
        self._successful_verifications = 0
        self._failed_verifications = 0
        
        # Default settings
        self._default_max_age_seconds = 86400  # 24 hours
        self._grace_period_seconds = 300  # 5 minute grace period
        
        logger.info("KeyVerifier initialized")
    
    def _parse_iso_timestamp(self, timestamp_str: str) -> Optional[datetime]:
        """
        Parse ISO 8601 timestamp string to datetime object.
        
        Handles multiple formats:
        - With timezone: "2024-01-15T10:30:00+00:00"
        - Without timezone (assumed UTC): "2024-01-15T10:30:00"
        - With 'Z' suffix: "2024-01-15T10:30:00Z"
        
        Returns:
            datetime object in UTC, or None if parsing fails
        """
        if not timestamp_str:
            return None
        
        try:
            # Handle 'Z' suffix (UTC)
            if timestamp_str.endswith('Z'):
                timestamp_str = timestamp_str[:-1] + '+00:00'
            
            # Try parsing with timezone first
            if '+' in timestamp_str or timestamp_str.count('-') > 2:
                return datetime.fromisoformat(timestamp_str)
            else:
                # Assume UTC if no timezone specified
                dt = datetime.fromisoformat(timestamp_str)
                return dt.replace(tzinfo=timezone.utc)
                
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to parse timestamp '{timestamp_str}': {e}")
            return None
    
    def _get_current_utc_time(self) -> datetime:
        """Get current UTC time"""
        return datetime.now(timezone.utc)
    
    def verify_key_expiry(
        self,
        key_metadata: KeyMetadata = None,
        max_age_seconds: int = None
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Verify key hasn't expired based on metadata.
        
        Checks:
        1. Key status (must be 'active')
        2. Expiry date (if set)
        3. Max age (if set)
        
        Args:
            key_metadata: Key metadata containing expiry information
            max_age_seconds: Maximum age in seconds (overrides metadata)
            
        Returns:
            Tuple of (is_valid, reason, metadata_dict)
        """
        # Handle missing metadata
        if key_metadata is None:
            logger.warning("No metadata provided, assuming valid (legacy key)")
            return True, "no_metadata", None
        
        # Convert metadata to dict for reporting
        metadata_dict = key_metadata.to_dict()
        
        # Check 1: Key status
        if key_metadata.status.lower() != "active":
            if key_metadata.status.lower() == "expired":
                return False, "key_status_expired", metadata_dict
            elif key_metadata.status.lower() == "revoked":
                return False, "key_status_revoked", metadata_dict
            elif key_metadata.status.lower() == "inactive":
                return False, "key_status_inactive", metadata_dict
            else:
                return False, f"key_status_{key_metadata.status}", metadata_dict
        
        # Check 2: Explicit expiry_date
        if key_metadata.expiry_date:
            expiry_dt = self._parse_iso_timestamp(key_metadata.expiry_date)
            
            if expiry_dt is None:
                # Invalid date format - fail closed (deny access)
                logger.error(f"Invalid expiry_date format: {key_metadata.expiry_date}")
                return False, "invalid_expiry_format", metadata_dict
            
            current_time = self._get_current_utc_time()
            
            # Compare in UTC
            if expiry_dt.tzinfo is None:
                expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
            
            if current_time > expiry_dt:
                # Key has expired
                time_diff = current_time - expiry_dt
                logger.warning(f"Key expired at {expiry_dt} (expired {time_diff.total_seconds():.0f}s ago)")
                return False, "key_expired", metadata_dict
        
        # Check 3: Max age (from metadata or parameter)
        effective_max_age = max_age_seconds or key_metadata.max_age_seconds or self._default_max_age_seconds
        
        if effective_max_age:
            created_dt = self._parse_iso_timestamp(key_metadata.created_at)
            
            if created_dt is None:
                logger.warning("Invalid created_at format, skipping max_age check")
            else:
                current_time = self._get_current_utc_time()
                
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=timezone.utc)
                
                key_age = (current_time - created_dt).total_seconds()
                
                # Apply grace period
                if key_age > (effective_max_age + self._grace_period_seconds):
                    logger.warning(f"Key age {key_age}s exceeds max {effective_max_age}s")
                    return False, "key_max_age_exceeded", metadata_dict
        
        # All checks passed - key is valid
        return True, "valid", metadata_dict
    
    def update_last_used(self, key_metadata: KeyMetadata) -> KeyMetadata:
        """Update last_used timestamp to current time"""
        key_metadata.last_used = self._get_current_utc_time().isoformat()
        return key_metadata
    
    def create_key_metadata(
        self,
        expiry_days: int = None,
        max_age_seconds: int = None,
        status: str = "active"
    ) -> KeyMetadata:
        """
        Create new key metadata with specified settings.
        
        Args:
            expiry_days: Days until key expires (None = no expiry date)
            max_age_seconds: Maximum key age in seconds
            status: Initial key status
            
        Returns:
            KeyMetadata instance
        """
        created_at = self._get_current_utc_time()
        
        expiry_date = None
        if expiry_days is not None:
            expiry_dt = created_at + timedelta(days=expiry_days)
            expiry_date = expiry_dt.isoformat()
        
        return KeyMetadata(
            created_at=created_at.isoformat(),
            expiry_date=expiry_date,
            last_used=None,
            status=status,
            max_age_seconds=max_age_seconds
        )
    
    def verify_key_integrity(
        self,
        key_data: bytes,
        expected_hash: str = None
    ) -> Tuple[bool, str]:
        """
        Verify key data integrity using SHA-256 hash.
        
        Args:
            key_data: Raw key bytes
            expected_hash: Expected hash (hex string)
            
        Returns:
            Tuple of (is_valid, hash_value)
        """
        actual_hash = hashlib.sha256(key_data).hexdigest()
        
        if expected_hash is None:
            return True, actual_hash
        
        is_valid = hmac.compare_digest(actual_hash, expected_hash)
        
        if not is_valid:
            logger.warning(f"Key integrity check failed: expected={expected_hash}, got={actual_hash}")
        
        return is_valid, actual_hash
    
    def verify_signature(
        self,
        message: bytes,
        signature: bytes,
        key_data: bytes,
        algorithm: str = "hmac-sha256"
    ) -> bool:
        """
        Verify message signature.
        
        Args:
            message: Message that was signed
            signature: Signature to verify
            key_data: Key used for signature
            algorithm: Signature algorithm
            
        Returns:
            True if signature is valid
        """
        try:
            if algorithm == "hmac-sha256":
                expected = hmac.new(key_data, message, hashlib.sha256).digest()
                return hmac.compare_digest(signature, expected)
            else:
                logger.warning(f"Unsupported algorithm: {algorithm}")
                return False
                
        except Exception as e:
            logger.error(f"Signature verification error: {e}")
            return False
    
    def _hmac_sign(self, message: bytes, key: bytes) -> bytes:
        """
        Create HMAC signature (for testing compatibility).
        
        Args:
            message: Message to sign
            key: Key to use for signing
            
        Returns:
            HMAC signature bytes
        """
        return hmac.new(key, message, hashlib.sha256).digest()
    
    def verify_key_format(
        self,
        key_data: bytes,
        expected_length: int = 32,
        expected_format: str = "raw"
    ) -> Tuple[bool, str]:
        """
        Verify key format and length.
        
        Args:
            key_data: Key bytes to verify
            expected_length: Expected key length in bytes
            expected_format: Expected format (raw, base64, hex)
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if len(key_data) != expected_length:
            return False, f"Invalid key length: {len(key_data)} (expected {expected_length})"
        
        if expected_format == "raw":
            # Check for null bytes (suspicious)
            if b'\x00' in key_data:
                return False, "Key contains null bytes"
        
        return True, ""
    
    async def verify(
        self,
        key_data: bytes,
        context: VerificationContext = None,
        options: Dict[str, Any] = None
    ) -> VerificationReport:
        """
        Comprehensive key verification.
        
        Args:
            key_data: Key bytes to verify
            context: Verification context (contains key_id)
            options: Verification options
            
        Returns:
            VerificationReport with results
        """
        start_time = time.time()
        options = options or {}
        
        # Extract key_id from context or use default
        key_id = "unknown"
        if context is not None:
            key_id = getattr(context, 'key_id', 'unknown')
        
        self._total_verifications += 1
        
        try:
            # Format verification
            if options.get("check_format", True):
                is_valid, error = self.verify_key_format(
                    key_data,
                    expected_length=options.get("expected_length", 32)
                )
                if not is_valid:
                    self._failed_verifications += 1
                    return VerificationReport(
                        result=VerificationResult.INVALID,
                        key_id=key_id,
                        latency_ms=(time.time() - start_time) * 1000,
                        timestamp=time.time(),
                        details=error
                    )
            
            # Integrity verification
            if options.get("check_integrity", False):
                expected_hash = options.get("expected_hash")
                is_valid, _ = self.verify_key_integrity(key_data, expected_hash)
                if not is_valid:
                    self._failed_verifications += 1
                    return VerificationReport(
                        result=VerificationResult.INVALID,
                        key_id=key_id,
                        latency_ms=(time.time() - start_time) * 1000,
                        timestamp=time.time(),
                        details="Integrity check failed"
                    )
            
            # Expiry verification (with metadata)
            if options.get("check_expiry", True):
                key_metadata = options.get("key_metadata")
                is_valid, reason, metadata_dict = self.verify_key_expiry(
                    key_metadata=key_metadata,
                    max_age_seconds=options.get("max_age_seconds")
                )
                
                if not is_valid:
                    self._failed_verifications += 1
                    
                    # Map reason to VerificationResult
                    if "expired" in reason or "exceeded" in reason:
                        result = VerificationResult.EXPIRED
                    elif "inactive" in reason or "revoked" in reason:
                        result = VerificationResult.INACTIVE
                    else:
                        result = VerificationResult.INVALID
                    
                    return VerificationReport(
                        result=result,
                        key_id=key_id,
                        latency_ms=(time.time() - start_time) * 1000,
                        timestamp=time.time(),
                        details=reason,
                        metadata=metadata_dict
                    )
            
            # All checks passed
            self._successful_verifications += 1
            
            return VerificationReport(
                result=VerificationResult.VALID,
                key_id=key_id,
                latency_ms=(time.time() - start_time) * 1000,
                timestamp=time.time(),
                details="All verifications passed"
            )
            
        except Exception as e:
            self._failed_verifications += 1
            logger.error(f"Verification error for {key_id}: {e}")
            
            return VerificationReport(
                result=VerificationResult.ERROR,
                key_id=key_id,
                latency_ms=(time.time() - start_time) * 1000,
                timestamp=time.time(),
                details=str(e)
            )
    
    def get_stats(self) -> Dict[str, Any]:
        """Get verification statistics"""
        total = self._total_verifications
        success_rate = self._successful_verifications / total if total > 0 else 0.0
        
        return {
            "total_verifications": total,
            "successful": self._successful_verifications,
            "failed": self._failed_verifications,
            "success_rate": success_rate,
            "default_max_age_seconds": self._default_max_age_seconds,
            "grace_period_seconds": self._grace_period_seconds
        }


# Global verifier instance
_verifier_instance: Optional[KeyVerifier] = None


def get_key_verifier() -> KeyVerifier:
    """Get global key verifier"""
    global _verifier_instance
    if _verifier_instance is None:
        _verifier_instance = KeyVerifier()
    return _verifier_instance
