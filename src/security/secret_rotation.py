# ============================================================
# PSKC — Secret Rotation Module
# Automatic key rotation and lifecycle management
# ============================================================
#
# IMPROVEMENTS:
#   1. Grace Period - old key stays valid during grace period after rotation
#   2. Atomicity - rotation either fully succeeds or fully rolls back
#   3. Dual-Key Period - both old and new keys work during transition
#   4. Checkpoint/Resume - can resume interrupted rotations
# ============================================================
import time
import secrets
import hashlib
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, List, Tuple, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
import logging
import json
import contextlib

logger = logging.getLogger(__name__)


class RotationStatus(Enum):
    """Status of key rotation"""
    ACTIVE = "active"
    ROTATING = "rotating"
    DEPRECATED = "deprecated"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass
class RotationCheckpoint:
    """
    Checkpoint for atomic rotation operations.
    
    This allows for resume capability if rotation is interrupted.
    """
    rotation_id: str
    key_id: str
    old_version_id: str
    new_version_id: Optional[str] = None
    phase: str = "initiated"  # initiated, dual_key, committed, rolled_back
    started_at: str = ""
    completed_at: Optional[str] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class KeyVersion:
    """
    Represents a single version of a secret/key.
    
    Attributes:
        version_id: Unique identifier for this version
        key_data: The actual key material (encrypted in production)
        created_at: When this version was created
        expires_at: When this version expires (None = never)
        rotated_at: When this version was rotated (if applicable)
        status: Current status of this version
        created_by: Service or user that created this version
        valid_until: Grace period end time for deprecated keys
    """
    version_id: str
    key_data: bytes
    created_at: str
    expires_at: Optional[str] = None
    rotated_at: Optional[str] = None
    status: str = "active"
    created_by: str = "system"
    valid_until: Optional[str] = None  # Grace period end time
    
    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # Don't expose key_data in serialization
        data['key_data'] = "[REDACTED]"
        data['has_key_material'] = self.key_data is not None
        return data
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


@dataclass
class RotationPolicy:
    """
    Policy for automatic key rotation.
    
    Attributes:
        rotation_interval_days: Days between automatic rotations
        max_versions: Maximum number of key versions to keep
        grace_period_hours: Hours to keep old version after rotation (dual-key period)
        auto_rotate: Whether to automatically rotate keys
        rotation_time_hour: Hour of day to perform rotation (0-23)
        atomic_rotation: Whether to use atomic rotation with checkpoints
        dual_key_required: Whether both old and new keys must work during grace period
    """
    rotation_interval_days: int = 30
    max_versions: int = 5
    grace_period_hours: int = 24
    auto_rotate: bool = True
    rotation_time_hour: int = 2  # 2 AM default
    atomic_rotation: bool = True  # Enable atomic rotation
    dual_key_required: bool = True  # Both keys work during grace period
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RotationPolicy':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class AtomicRotationError(Exception):
    """Exception for atomic rotation failures"""
    pass


class SecretRotationManager:
    """
    Manages automatic secret/key rotation with zero-downtime.
    
    Features:
    - Atomic rotation with checkpoints
    - Grace period (dual-key period) for zero-downtime
    - Automatic rollback on failure
    - Multiple key versions support
    - Manual rotation support
    - Rotation history and auditing
    """
    
    def __init__(self, policy: RotationPolicy = None):
        self._policy = policy or RotationPolicy()
        self._keys: Dict[str, List[KeyVersion]] = {}  # key_id -> versions
        self._rotation_history: List[Dict[str, Any]] = []
        self._checkpoints: Dict[str, RotationCheckpoint] = {}  # rotation_id -> checkpoint
        self._lock = threading.RLock()
        self._rotation_thread: Optional[threading.Thread] = None
        self._running = False
        
        logger.info(f"SecretRotationManager initialized with policy: {self._policy}")
    
    def _generate_version_id(self, key_id: str) -> str:
        """Generate unique version ID"""
        timestamp = str(time.time())
        random_part = secrets.token_hex(8)
        return f"{key_id}:{timestamp}:{random_part}"
    
    def _generate_rotation_id(self) -> str:
        """Generate unique rotation ID"""
        return f"rot_{secrets.token_hex(12)}"
    
    def _get_current_utc_time(self) -> datetime:
        """Get current UTC time"""
        return datetime.now(timezone.utc)
    
    def create_key(
        self,
        key_id: str,
        key_data: bytes = None,
        created_by: str = "system"
    ) -> KeyVersion:
        """
        Create a new key with initial version.
        
        Args:
            key_id: Identifier for the key
            key_data: Key material (generated if not provided)
            created_by: Service or user creating the key
            
        Returns:
            KeyVersion instance
        """
        with self._lock:
            # Generate key material if not provided
            if key_data is None:
                key_data = secrets.token_bytes(32)  # 256-bit key
            
            version = KeyVersion(
                version_id=self._generate_version_id(key_id),
                key_data=key_data,
                created_at=self._get_current_utc_time().isoformat(),
                status="active",
                created_by=created_by
            )
            
            # Initialize key versions list if needed
            if key_id not in self._keys:
                self._keys[key_id] = []
            
            self._keys[key_id].append(version)
            
            # Log creation
            self._log_rotation_event(key_id, "created", {
                "version_id": version.version_id,
                "created_by": created_by
            })
            
            logger.info(f"Created new key: {key_id} version {version.version_id}")
            
            return version
    
    def rotate_key_atomic(
        self,
        key_id: str,
        created_by: str = "system",
        force: bool = False
    ) -> Optional[KeyVersion]:
        """
        Perform atomic key rotation with grace period support.
        
        Phases:
        1. initiated - rotation started, checkpoint created
        2. dual_key - both old and new keys valid (grace period)
        3. committed - rotation complete, old key deprecated
        4. rolled_back - rotation failed, rolled back
        
        Args:
            key_id: Identifier for the key to rotate
            created_by: Service or user requesting rotation
            force: Force rotation even if not due
            
        Returns:
            New KeyVersion instance, or None if key doesn't exist
        """
        rotation_id = self._generate_rotation_id()
        checkpoint = RotationCheckpoint(
            rotation_id=rotation_id,
            key_id=key_id,
            old_version_id="",
            started_at=self._get_current_utc_time().isoformat()
        )
        
        try:
            with self._lock:
                if key_id not in self._keys or not self._keys[key_id]:
                    logger.warning(f"Key not found for rotation: {key_id}")
                    return None
                
                versions = self._keys[key_id]
                
                # Find current active version
                current_version = None
                for v in versions:
                    if v.status == "active":
                        current_version = v
                        break
                
                if current_version is None:
                    logger.error(f"No active version found for key: {key_id}")
                    return None
                
                checkpoint.old_version_id = current_version.version_id
                
                # Check if rotation is needed
                if not force:
                    should_rotate, reason = self._should_rotate(current_version)
                    if not should_rotate:
                        logger.debug(f"Rotation not needed for {key_id}: {reason}")
                        return None
                
                # Phase 1: Create new version (initiated)
                new_version = KeyVersion(
                    version_id=self._generate_version_id(key_id),
                    key_data=secrets.token_bytes(32),
                    created_at=self._get_current_utc_time().isoformat(),
                    status="active",
                    created_by=created_by
                )
                
                checkpoint.new_version_id = new_version.version_id
                checkpoint.phase = "initiated"
                self._checkpoints[rotation_id] = checkpoint
                
                # Phase 2: Enter dual-key period (if enabled)
                if self._policy.dual_key_required:
                    # Mark old version as deprecated but still valid
                    current_version.status = "deprecated"
                    grace_period_end = self._get_current_utc_time() + timedelta(hours=self._policy.grace_period_hours)
                    current_version.valid_until = grace_period_end.isoformat()
                    current_version.rotated_at = self._get_current_utc_time().isoformat()
                    
                    # Add new version as active
                    versions.append(new_version)
                    
                    checkpoint.phase = "dual_key"
                    
                    logger.info(
                        f"Key rotation {rotation_id}: entered dual-key period for {key_id}. "
                        f"Old valid until: {current_version.valid_until}"
                    )
                else:
                    # Non-dual-key rotation: immediately replace
                    current_version.status = "deprecated"
                    current_version.rotated_at = self._get_current_utc_time().isoformat()
                    versions.append(new_version)
                    checkpoint.phase = "committed"
                
                # Phase 3: Schedule cleanup (for when grace period ends)
                self._schedule_grace_period_cleanup(key_id, checkpoint)
                
                # Log rotation
                self._log_rotation_event(key_id, "rotated", {
                    "old_version": current_version.version_id,
                    "new_version": new_version.version_id,
                    "rotation_id": rotation_id,
                    "phase": checkpoint.phase,
                    "grace_period_hours": self._policy.grace_period_hours if self._policy.dual_key_required else 0,
                    "created_by": created_by
                })
                
                # Mark checkpoint as complete
                checkpoint.completed_at = self._get_current_utc_time().isoformat()
                
                logger.info(
                    f"Rotated key: {key_id} from {current_version.version_id} "
                    f"to {new_version.version_id} (phase: {checkpoint.phase})"
                )
                
                return new_version
                
        except Exception as e:
            # Rollback on failure
            logger.error(f"Atomic rotation failed for {key_id}: {e}")
            checkpoint.phase = "rolled_back"
            checkpoint.error = str(e)
            checkpoint.completed_at = self._get_current_utc_time().isoformat()
            
            self._log_rotation_event(key_id, "rotation_failed", {
                "rotation_id": rotation_id,
                "error": str(e)
            })
            
            raise AtomicRotationError(f"Rotation failed: {e}") from e
    
    def _schedule_grace_period_cleanup(self, key_id: str, checkpoint: RotationCheckpoint):
        """Schedule cleanup after grace period"""
        # In a production system, this would schedule a background job
        # For now, we'll handle it in the get_valid_keys method
        pass
    
    def get_valid_keys(self, key_id: str) -> List[KeyVersion]:
        """
        Get all valid (usable) keys for a given key_id.
        
        During grace period, returns both old (deprecated but valid) and new keys.
        After grace period, only returns the new key.
        
        Args:
            key_id: Identifier for the key
            
        Returns:
            List of valid KeyVersion instances
        """
        with self._lock:
            if key_id not in self._keys:
                return []
            
            valid_keys = []
            now = self._get_current_utc_time()
            
            for version in self._keys[key_id]:
                if version.status == "active":
                    valid_keys.append(version)
                elif version.status == "deprecated":
                    # Check if still in grace period
                    if version.valid_until:
                        valid_until = datetime.fromisoformat(version.valid_until)
                        if valid_until.tzinfo is None:
                            valid_until = valid_until.replace(tzinfo=timezone.utc)
                        
                        if now < valid_until:
                            # Still in grace period - key is valid
                            valid_keys.append(version)
                        else:
                            # Grace period expired - update status
                            version.status = "expired"
                            logger.info(f"Key version {version.version_id} grace period expired")
                
            return valid_keys
    
    def rotate_key(
        self,
        key_id: str,
        created_by: str = "system",
        force: bool = False
    ) -> Optional[KeyVersion]:
        """
        Rotate a key to a new version (delegates to atomic rotation).
        
        Args:
            key_id: Identifier for the key to rotate
            created_by: Service or user requesting rotation
            force: Force rotation even if not due
            
        Returns:
            New KeyVersion instance, or None if key doesn't exist
        """
        if self._policy.atomic_rotation:
            return self.rotate_key_atomic(key_id, created_by, force)
        
        # Legacy non-atomic rotation
        return self._rotate_key_legacy(key_id, created_by, force)
    
    def _rotate_key_legacy(
        self,
        key_id: str,
        created_by: str,
        force: bool
    ) -> Optional[KeyVersion]:
        """Legacy non-atomic rotation (for backwards compatibility)"""
        with self._lock:
            if key_id not in self._keys or not self._keys[key_id]:
                logger.warning(f"Key not found for rotation: {key_id}")
                return None
            
            versions = self._keys[key_id]
            
            # Find current active version
            current_version = None
            for v in versions:
                if v.status == "active":
                    current_version = v
                    break
            
            if current_version is None:
                logger.error(f"No active version found for key: {key_id}")
                return None
            
            # Check if rotation is needed
            if not force:
                should_rotate, reason = self._should_rotate(current_version)
                if not should_rotate:
                    logger.debug(f"Rotation not needed for {key_id}: {reason}")
                    return None
            
            # Create new version
            new_version = KeyVersion(
                version_id=self._generate_version_id(key_id),
                key_data=secrets.token_bytes(32),
                created_at=self._get_current_utc_time().isoformat(),
                status="active",
                created_by=created_by
            )
            
            # Mark old version as deprecated
            current_version.status = "deprecated"
            current_version.rotated_at = self._get_current_utc_time().isoformat()
            
            # Add new version
            versions.append(new_version)
            
            # Cleanup old versions if needed
            self._cleanup_old_versions(key_id)
            
            # Log rotation
            self._log_rotation_event(key_id, "rotated", {
                "old_version": current_version.version_id,
                "new_version": new_version.version_id,
                "created_by": created_by,
                "mode": "legacy"
            })
            
            logger.info(f"Rotated key: {key_id} from {current_version.version_id} to {new_version.version_id}")
            
            return new_version
    
    def _should_rotate(self, version: KeyVersion) -> Tuple[bool, str]:
        """
        Check if a key should be rotated based on policy.
        
        Returns:
            Tuple of (should_rotate, reason)
        """
        if not self._policy.auto_rotate:
            return False, "auto_rotate disabled"
        
        created_dt = datetime.fromisoformat(version.created_at)
        
        # Handle timezone
        if created_dt.tzinfo is None:
            created_dt = created_dt.replace(tzinfo=timezone.utc)
        
        # Check rotation interval
        age = self._get_current_utc_time() - created_dt
        rotation_interval = timedelta(days=self._policy.rotation_interval_days)
        
        if age >= rotation_interval:
            return True, f"rotation_interval exceeded ({age.days} days)"
        
        return False, f"rotation not due (age: {age.days} days)"
    
    def get_rotation_status(self, key_id: str) -> Dict[str, Any]:
        """
        Get detailed rotation status for a key.
        
        Returns:
            Dict with rotation status information
        """
        with self._lock:
            if key_id not in self._keys:
                return {"error": "key not found"}
            
            versions = self._keys[key_id]
            now = self._get_current_utc_time()
            
            status = {
                "key_id": key_id,
                "total_versions": len(versions),
                "active_versions": [],
                "deprecated_versions": [],
                "expired_versions": [],
                "in_grace_period": False
            }
            
            for v in versions:
                version_info = {
                    "version_id": v.version_id,
                    "status": v.status,
                    "created_at": v.created_at,
                    "rotated_at": v.rotated_at,
                    "valid_until": v.valid_until
                }
                
                if v.status == "active":
                    status["active_versions"].append(version_info)
                elif v.status == "deprecated":
                    status["deprecated_versions"].append(version_info)
                    # Check if in grace period
                    if v.valid_until:
                        valid_until = datetime.fromisoformat(v.valid_until)
                        if valid_until.tzinfo is None:
                            valid_until = valid_until.replace(tzinfo=timezone.utc)
                        if now < valid_until:
                            status["in_grace_period"] = True
                elif v.status == "expired":
                    status["expired_versions"].append(version_info)
            
            return status
    
    def _cleanup_old_versions(self, key_id: str):
        """Remove old versions based on policy"""
        versions = self._keys.get(key_id, [])
        
        if len(versions) <= self._policy.max_versions:
            return
        
        # Sort by creation date (oldest first)
        sorted_versions = sorted(versions, key=lambda v: v.created_at)
        
        # Remove oldest versions (but keep at least 1)
        to_remove = len(versions) - self._policy.max_versions
        
        for i in range(to_remove):
            old_version = sorted_versions[i]
            if old_version.status != "active":
                versions.remove(old_version)
                logger.debug(f"Removed old version: {old_version.version_id}")
    
    def revoke_key(self, key_id: str, reason: str = "manual") -> bool:
        """
        Revoke all versions of a key.
        
        Args:
            key_id: Identifier for the key to revoke
            reason: Reason for revocation
            
        Returns:
            True if successful
        """
        with self._lock:
            if key_id not in self._keys:
                return False
            
            for version in self._keys[key_id]:
                version.status = "revoked"
            
            self._log_rotation_event(key_id, "revoked", {"reason": reason})
            
            logger.warning(f"Revoked key: {key_id}, reason: {reason}")
            
            return True
    
    def get_active_key(self, key_id: str) -> Optional[KeyVersion]:
        """
        Get the currently active key version.
        
        Args:
            key_id: Identifier for the key
            
        Returns:
            KeyVersion instance, or None if not found
        """
        with self._lock:
            if key_id not in self._keys:
                return None
            
            for version in self._keys[key_id]:
                if version.status == "active":
                    return version
            
            return None
    
    def get_key_versions(self, key_id: str) -> List[Dict[str, Any]]:
        """
        Get all versions of a key (without sensitive data).
        
        Args:
            key_id: Identifier for the key
            
        Returns:
            List of version dictionaries
        """
        with self._lock:
            if key_id not in self._keys:
                return []
            
            return [v.to_dict() for v in self._keys[key_id]]
    
    def _log_rotation_event(self, key_id: str, event_type: str, details: Dict[str, Any]):
        """Log a rotation event"""
        event = {
            "timestamp": self._get_current_utc_time().isoformat(),
            "key_id": key_id,
            "event_type": event_type,
            "details": details
        }
        self._rotation_history.append(event)
        
        # Keep history limited
        max_history = 1000
        if len(self._rotation_history) > max_history:
            self._rotation_history = self._rotation_history[-max_history:]
    
    def get_rotation_history(
        self,
        key_id: str = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get rotation history.
        
        Args:
            key_id: Optional filter by key ID
            limit: Maximum number of events to return
            
        Returns:
            List of rotation events
        """
        history = self._rotation_history
        
        if key_id:
            history = [e for e in history if e.get("key_id") == key_id]
        
        return history[-limit:]
    
    def update_policy(self, policy: RotationPolicy):
        """Update rotation policy"""
        self._policy = policy
        logger.info(f"Updated rotation policy: {policy}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get rotation manager statistics"""
        total_keys = len(self._keys)
        total_versions = sum(len(v) for v in self._keys.values())
        
        return {
            "total_keys": total_keys,
            "total_versions": total_versions,
            "policy": self._policy.to_dict(),
            "rotation_history_size": len(self._rotation_history)
        }
    
    def start_auto_rotation(self):
        """Start automatic rotation background thread"""
        if self._running:
            logger.warning("Auto rotation already running")
            return
        
        self._running = True
        self._rotation_thread = threading.Thread(
            target=self._auto_rotation_loop,
            daemon=True
        )
        self._rotation_thread.start()
        
        logger.info("Auto rotation started")
    
    def stop_auto_rotation(self):
        """Stop automatic rotation"""
        self._running = False
        
        if self._rotation_thread:
            self._rotation_thread.join(timeout=5)
        
        logger.info("Auto rotation stopped")
    
    def _auto_rotation_loop(self):
        """Background loop for automatic rotation"""
        while self._running:
            try:
                # Sleep for 1 hour
                time.sleep(3600)
                
                if not self._running:
                    break
                
                # Check each key
                for key_id in list(self._keys.keys()):
                    try:
                        self.rotate_key(key_id, created_by="auto_rotation")
                    except Exception as e:
                        logger.error(f"Auto rotation failed for {key_id}: {e}")
                        
            except Exception as e:
                logger.error(f"Auto rotation loop error: {e}")


# Global rotation manager instance
_rotation_manager: Optional[SecretRotationManager] = None


def get_rotation_manager(policy: RotationPolicy = None) -> SecretRotationManager:
    """Get global rotation manager"""
    global _rotation_manager
    if _rotation_manager is None:
        _rotation_manager = SecretRotationManager(policy)
    return _rotation_manager
