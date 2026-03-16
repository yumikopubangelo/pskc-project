# ============================================================
# PSKC — Key Lifecycle Manager
# Unified key management with cache integration and complete lifecycle
# ============================================================
#
# FEATURES:
#   1. Unified Workflow - create → rotate → revoke → expire in one system
#   2. Cache Integration - automatic cache invalidation on key changes
#   3. Secure Store - encrypted key storage with rotation support
#   4. Expiration - automatic key expiration with grace period
#   5. Lifecycle Events - hooks for key lifecycle events
#   6. Audit Trail - complete audit logging for compliance
# ============================================================
import time
import secrets
import hashlib
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, List, Tuple, Any, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
import logging
import json

logger = logging.getLogger(__name__)


class LifecycleEvent(Enum):
    """Key lifecycle events"""
    CREATED = "created"
    ROTATED = "rotated"
    REVOKED = "revoked"
    EXPIRED = "expired"
    ACCESSED = "accessed"
    CACHE_INVALIDATED = "cache_invalidated"
    CACHE_HIT = "cache_hit"
    CACHE_MISS = "cache_miss"


class KeyStatus(Enum):
    """Key status states"""
    PENDING = "pending"
    ACTIVE = "active"
    ROTATING = "rotating"
    DEPRECATED = "deprecated"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass
class KeyMetadata:
    """Metadata for a managed key"""
    key_id: str
    key_type: str  # encryption, signing, auth, etc.
    status: str
    created_at: str
    expires_at: Optional[str] = None
    last_rotated_at: Optional[str] = None
    last_accessed_at: Optional[str] = None
    rotation_count: int = 0
    created_by: str = "system"
    description: str = ""
    tags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LifecycleEventRecord:
    """Record of a lifecycle event"""
    event_id: str
    key_id: str
    event_type: LifecycleEvent
    timestamp: str
    details: Dict[str, Any]
    user: str = "system"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "key_id": self.key_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "details": self.details,
            "user": self.user
        }


@dataclass
class LifecyclePolicy:
    """
    Policy for key lifecycle management.
    
    Attributes:
        rotation_interval_days: Days between automatic rotations
        max_versions: Maximum number of key versions to keep
        grace_period_hours: Hours to keep old key after rotation
        auto_rotate: Whether to automatically rotate keys
        auto_expire: Whether to automatically expire keys after expiration_date
        cache_ttl_seconds: Cache TTL for key material
        cache_enabled: Whether to cache key material
        rotation_time_hour: Hour of day to perform rotation
        dual_key_required: Whether both old and new keys work during grace
    """
    rotation_interval_days: int = 30
    max_versions: int = 5
    grace_period_hours: int = 24
    auto_rotate: bool = True
    auto_expire: bool = True
    cache_ttl_seconds: int = 300  # 5 minutes default
    cache_enabled: bool = True
    rotation_time_hour: int = 2
    dual_key_required: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class KeyCacheInterface:
    """
    Interface for key caching.
    Implement this to integrate with your specific cache (Redis, Memcached, etc.)
    """
    
    def __init__(self):
        self._cache: Dict[str, Tuple[bytes, datetime]] = {}
        self._lock = threading.RLock()
    
    def get(self, key_id: str) -> Optional[bytes]:
        """Get key material from cache"""
        with self._lock:
            if key_id in self._cache:
                value, expires_at = self._cache[key_id]
                if datetime.now(timezone.utc) < expires_at:
                    return value
                else:
                    del self._cache[key_id]
            return None
    
    def set(self, key_id: str, value: bytes, ttl_seconds: int):
        """Set key material in cache"""
        with self._lock:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
            self._cache[key_id] = (value, expires_at)
    
    def invalidate(self, key_id: str):
        """Invalidate a key in cache"""
        with self._lock:
            if key_id in self._cache:
                del self._cache[key_id]
    
    def invalidate_pattern(self, pattern: str):
        """Invalidate all keys matching pattern"""
        with self._lock:
            keys_to_delete = [k for k in self._cache.keys() if pattern in k]
            for key in keys_to_delete:
                del self._cache[key]
    
    def clear(self):
        """Clear entire cache"""
        with self._lock:
            self._cache.clear()


class SecureKeyStoreInterface:
    """
    Interface for secure key storage.
    Implement this to integrate with your specific secure store (HSM, Vault, etc.)
    """
    
    def __init__(self):
        self._store: Dict[str, bytes] = {}
        self._lock = threading.RLock()
    
    def store(self, key_id: str, key_material: bytes):
        """Store key material securely"""
        with self._lock:
            self._store[key_id] = key_material
    
    def retrieve(self, key_id: str) -> Optional[bytes]:
        """Retrieve key material"""
        with self._lock:
            return self._store.get(key_id)
    
    def delete(self, key_id: str):
        """Delete key material"""
        with self._lock:
            if key_id in self._store:
                del self._store[key_id]
    
    def exists(self, key_id: str) -> bool:
        """Check if key exists"""
        with self._lock:
            return key_id in self._store


class LifecycleEventHandler:
    """Handler for key lifecycle events"""
    
    def __init__(self):
        self._handlers: Dict[LifecycleEvent, List[Callable]] = {
            event: [] for event in LifecycleEvent
        }
    
    def register(self, event: LifecycleEvent, handler: Callable):
        """Register a handler for an event"""
        self._handlers[event].append(handler)
    
    def trigger(self, event: LifecycleEvent, key_id: str, details: Dict[str, Any]):
        """Trigger all handlers for an event"""
        for handler in self._handlers[event]:
            try:
                handler(key_id, details)
            except Exception as e:
                logger.error(f"Event handler error for {event.value}: {e}")


class KeyLifecycleManager:
    """
    Unified Key Lifecycle Manager.
    
    Provides complete workflow: create → rotate → revoke → expire
    with integrated caching and secure storage.
    
    Features:
    - Cache integration with automatic invalidation
    - Secure store for key material
    - Automatic rotation with grace period
    - Automatic expiration
    - Lifecycle event hooks
    - Complete audit trail
    """
    
    def __init__(
        self,
        policy: LifecyclePolicy = None,
        cache: KeyCacheInterface = None,
        secure_store: SecureKeyStoreInterface = None
    ):
        self._policy = policy or LifecyclePolicy()
        self._cache = cache or KeyCacheInterface()
        self._secure_store = secure_store or SecureKeyStoreInterface()
        self._event_handler = LifecycleEventHandler()
        
        # Key metadata storage
        self._metadata: Dict[str, KeyMetadata] = {}
        
        # Lifecycle events
        self._events: List[LifecycleEventRecord] = []
        
        # Lock for thread safety
        self._lock = threading.RLock()
        
        # Background thread for auto-rotation/expiration
        self._running = False
        self._background_thread: Optional[threading.Thread] = None
        
        logger.info(f"KeyLifecycleManager initialized with policy: {self._policy}")
    
    def _generate_event_id(self) -> str:
        """Generate unique event ID"""
        return f"evt_{secrets.token_hex(12)}"
    
    def _get_current_utc_time(self) -> datetime:
        """Get current UTC time"""
        return datetime.now(timezone.utc)
    
    def _log_event(
        self,
        key_id: str,
        event_type: LifecycleEvent,
        details: Dict[str, Any],
        user: str = "system"
    ):
        """Log a lifecycle event"""
        event = LifecycleEventRecord(
            event_id=self._generate_event_id(),
            key_id=key_id,
            event_type=event_type,
            timestamp=self._get_current_utc_time().isoformat(),
            details=details,
            user=user
        )
        self._events.append(event)
        
        # Keep history limited
        max_history = 10000
        if len(self._events) > max_history:
            self._events = self._events[-max_history:]
        
        # Trigger event handlers
        self._event_handler.trigger(event_type, key_id, details)
    
    def register_event_handler(self, event: LifecycleEvent, handler: Callable):
        """Register a handler for lifecycle events"""
        self._event_handler.register(event, handler)
    
    # ============================================================
    # CREATE OPERATIONS
    # ============================================================
    
    def create_key(
        self,
        key_id: str,
        key_type: str = "encryption",
        key_material: bytes = None,
        created_by: str = "system",
        description: str = "",
        tags: List[str] = None,
        expires_in_days: int = None
    ) -> KeyMetadata:
        """
        Create a new key with complete lifecycle management.
        
        Args:
            key_id: Unique identifier for the key
            key_type: Type of key (encryption, signing, auth, etc.)
            key_material: Key material (generated if not provided)
            created_by: Service or user creating the key
            description: Human-readable description
            tags: Tags for categorization
            expires_in_days: Days until key expires (None = no expiration)
            
        Returns:
            KeyMetadata instance
        """
        with self._lock:
            # Check if key already exists
            if key_id in self._metadata:
                raise ValueError(f"Key already exists: {key_id}")
            
            # Generate key material if not provided
            if key_material is None:
                key_material = secrets.token_bytes(32)  # 256-bit key
            
            # Store in secure store
            self._secure_store.store(key_id, key_material)
            
            # Cache if enabled
            if self._policy.cache_enabled:
                self._cache.set(key_id, key_material, self._policy.cache_ttl_seconds)
            
            # Calculate expiration
            expires_at = None
            if expires_in_days is not None:
                expires_at = (self._get_current_utc_time() + timedelta(days=expires_in_days)).isoformat()
            
            # Create metadata
            metadata = KeyMetadata(
                key_id=key_id,
                key_type=key_type,
                status=KeyStatus.ACTIVE.value,
                created_at=self._get_current_utc_time().isoformat(),
                expires_at=expires_at,
                created_by=created_by,
                description=description,
                tags=tags or []
            )
            
            self._metadata[key_id] = metadata
            
            # Log event
            self._log_event(key_id, LifecycleEvent.CREATED, {
                "key_type": key_type,
                "created_by": created_by,
                "expires_at": expires_at,
                "tags": metadata.tags
            })
            
            logger.info(f"Created key: {key_id} (type: {key_type})")
            
            return metadata
    
    # ============================================================
    # ACCESS OPERATIONS (with caching)
    # ============================================================
    
    def get_key_material(self, key_id: str, use_cache: bool = True) -> Optional[bytes]:
        """
        Get key material with caching support.
        
        Args:
            key_id: Key identifier
            use_cache: Whether to use cache
            
        Returns:
            Key material bytes, or None if not found
        """
        with self._lock:
            # Check metadata exists
            if key_id not in self._metadata:
                logger.warning(f"Key not found: {key_id}")
                return None
            
            metadata = self._metadata[key_id]
            
            # Check if key is in valid state
            if metadata.status in [KeyStatus.REVOKED.value, KeyStatus.EXPIRED.value]:
                logger.warning(f"Key is {metadata.status}: {key_id}")
                return None
            
            # Try cache first
            if use_cache and self._policy.cache_enabled:
                cached = self._cache.get(key_id)
                if cached is not None:
                    # Update last accessed
                    metadata.last_accessed_at = self._get_current_utc_time().isoformat()
                    self._log_event(key_id, LifecycleEvent.CACHE_HIT, {"key_id": key_id})
                    return cached
            
            # Get from secure store
            key_material = self._secure_store.retrieve(key_id)
            
            if key_material is not None:
                # Update access time
                metadata.last_accessed_at = self._get_current_utc_time().isoformat()
                
                # Cache for next time
                if self._policy.cache_enabled:
                    self._cache.set(key_id, key_material, self._policy.cache_ttl_seconds)
                    self._log_event(key_id, LifecycleEvent.CACHE_MISS, {"key_id": key_id})
                
                self._log_event(key_id, LifecycleEvent.ACCESSED, {"key_id": key_id})
            
            return key_material
    
    def get_key_metadata(self, key_id: str) -> Optional[KeyMetadata]:
        """Get key metadata"""
        with self._lock:
            return self._metadata.get(key_id)
    
    # ============================================================
    # ROTATE OPERATIONS
    # ============================================================
    
    def rotate_key(
        self,
        key_id: str,
        created_by: str = "system",
        force: bool = False
    ) -> KeyMetadata:
        """
        Rotate a key to a new version.
        
        Args:
            key_id: Key identifier
            created_by: Service or user requesting rotation
            force: Force rotation even if not due
            
        Returns:
            Updated KeyMetadata
        """
        with self._lock:
            if key_id not in self._metadata:
                raise ValueError(f"Key not found: {key_id}")
            
            metadata = self._metadata[key_id]
            
            # Check if rotation is needed
            if not force and self._policy.auto_rotate:
                should_rotate, reason = self._should_rotate(metadata)
                if not should_rotate:
                    logger.debug(f"Rotation not needed for {key_id}: {reason}")
                    return metadata
            
            # Invalidate cache (will be refreshed with new key)
            if self._policy.cache_enabled:
                self._cache.invalidate(key_id)
                self._log_event(key_id, LifecycleEvent.CACHE_INVALIDATED, {
                    "reason": "rotation"
                })
            
            # Generate new key material
            new_key_material = secrets.token_bytes(32)
            
            # Store new key material
            if self._policy.dual_key_required:
                # Keep old key material for grace period
                old_key_material = self._secure_store.retrieve(key_id)
                # Store with version suffix
                version_suffix = f"_v{metadata.rotation_count + 1}"
                self._secure_store.store(f"{key_id}{version_suffix}", old_key_material)
            
            # Update secure store with new material
            self._secure_store.store(key_id, new_key_material)
            
            # Cache new material
            if self._policy.cache_enabled:
                self._cache.set(key_id, new_key_material, self._policy.cache_ttl_seconds)
            
            # Update metadata
            metadata.status = KeyStatus.ACTIVE.value
            metadata.last_rotated_at = self._get_current_utc_time().isoformat()
            metadata.rotation_count += 1
            
            # Log event
            self._log_event(key_id, LifecycleEvent.ROTATED, {
                "rotation_count": metadata.rotation_count,
                "created_by": created_by,
                "dual_key_period": self._policy.grace_period_hours if self._policy.dual_key_required else 0
            })
            
            logger.info(f"Rotated key: {key_id} (count: {metadata.rotation_count})")
            
            return metadata
    
    def _should_rotate(self, metadata: KeyMetadata) -> Tuple[bool, str]:
        """Check if key should be rotated"""
        if not self._policy.auto_rotate:
            return False, "auto_rotate disabled"
        
        # Check last rotation
        if metadata.last_rotated_at:
            last_rotated = datetime.fromisoformat(metadata.last_rotated_at)
            if last_rotated.tzinfo is None:
                last_rotated = last_rotated.replace(tzinfo=timezone.utc)
            
            age = self._get_current_utc_time() - last_rotated
            rotation_interval = timedelta(days=self._policy.rotation_interval_days)
            
            if age >= rotation_interval:
                return True, f"rotation_interval exceeded ({age.days} days)"
        
        # Check if never rotated and creation is old enough
        created_at = datetime.fromisoformat(metadata.created_at)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        
        age = self._get_current_utc_time() - created_at
        rotation_interval = timedelta(days=self._policy.rotation_interval_days)
        
        if age >= rotation_interval:
            return True, f"rotation_interval exceeded ({age.days} days)"
        
        return False, f"rotation not due"
    
    # ============================================================
    # REVOKE OPERATIONS
    # ============================================================
    
    def revoke_key(
        self,
        key_id: str,
        reason: str = "manual",
        invalidated_by: str = "system"
    ) -> bool:
        """
        Revoke a key immediately.
        
        Args:
            key_id: Key identifier
            reason: Reason for revocation
            invalidated_by: User or service revoking the key
            
        Returns:
            True if successful
        """
        with self._lock:
            if key_id not in self._metadata:
                return False
            
            metadata = self._metadata[key_id]
            old_status = metadata.status
            
            # Update status
            metadata.status = KeyStatus.REVOKED.value
            
            # Invalidate cache
            if self._policy.cache_enabled:
                self._cache.invalidate(key_id)
                self._log_event(key_id, LifecycleEvent.CACHE_INVALIDATED, {
                    "reason": "revocation"
                })
            
            # Log event
            self._log_event(key_id, LifecycleEvent.REVOKED, {
                "reason": reason,
                "invalidated_by": invalidated_by,
                "previous_status": old_status
            })
            
            logger.warning(f"Revoked key: {key_id}, reason: {reason}")
            
            return True
    
    # ============================================================
    # EXPIRE OPERATIONS
    # ============================================================
    
    def expire_key(self, key_id: str) -> bool:
        """
        Mark a key as expired (called by background process or manually).
        
        Args:
            key_id: Key identifier
            
        Returns:
            True if key was expired
        """
        with self._lock:
            if key_id not in self._metadata:
                return False
            
            metadata = self._metadata[key_id]
            
            # Check if already expired or revoked
            if metadata.status in [KeyStatus.EXPIRED.value, KeyStatus.REVOKED.value]:
                return False
            
            # Update status
            metadata.status = KeyStatus.EXPIRED.value
            
            # Invalidate cache
            if self._policy.cache_enabled:
                self._cache.invalidate(key_id)
                self._log_event(key_id, LifecycleEvent.CACHE_INVALIDATED, {
                    "reason": "expiration"
                })
            
            # Log event
            self._log_event(key_id, LifecycleEvent.EXPIRED, {
                "created_at": metadata.created_at,
                "rotation_count": metadata.rotation_count
            })
            
            logger.info(f"Expired key: {key_id}")
            
            return True
    
    def check_and_expire_keys(self) -> List[str]:
        """
        Check all keys for expiration and expire if needed.
        
        Returns:
            List of expired key IDs
        """
        if not self._policy.auto_expire:
            return []
        
        expired_keys = []
        now = self._get_current_utc_time()
        
        with self._lock:
            for key_id, metadata in self._metadata.items():
                if metadata.status not in [KeyStatus.ACTIVE.value, KeyStatus.DEPRECATED.value]:
                    continue
                
                if metadata.expires_at:
                    expires_at = datetime.fromisoformat(metadata.expires_at)
                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=timezone.utc)
                    
                    if now >= expires_at:
                        if self.expire_key(key_id):
                            expired_keys.append(key_id)
        
        return expired_keys
    
    # ============================================================
    # BACKGROUND OPERATIONS
    # ============================================================
    
    def start_background_tasks(self):
        """Start background tasks for auto-rotation and expiration"""
        if self._running:
            logger.warning("Background tasks already running")
            return
        
        self._running = True
        self._background_thread = threading.Thread(
            target=self._background_loop,
            daemon=True
        )
        self._background_thread.start()
        
        logger.info("Background lifecycle tasks started")
    
    def stop_background_tasks(self):
        """Stop background tasks"""
        self._running = False
        
        if self._background_thread:
            self._background_thread.join(timeout=5)
        
        logger.info("Background lifecycle tasks stopped")
    
    def _background_loop(self):
        """Background loop for lifecycle management"""
        while self._running:
            try:
                # Sleep for 1 hour
                time.sleep(3600)
                
                if not self._running:
                    break
                
                # Check for expirations
                expired = self.check_and_expire_keys()
                if expired:
                    logger.info(f"Background task: expired {len(expired)} keys")
                
                # Check for rotations
                if self._policy.auto_rotate:
                    for key_id in list(self._metadata.keys()):
                        try:
                            metadata = self._metadata.get(key_id)
                            if metadata and metadata.status == KeyStatus.ACTIVE.value:
                                should_rotate, _ = self._should_rotate(metadata)
                                if should_rotate:
                                    self.rotate_key(key_id, created_by="auto_rotation")
                        except Exception as e:
                            logger.error(f"Auto rotation failed for {key_id}: {e}")
                
            except Exception as e:
                logger.error(f"Background loop error: {e}")
    
    # ============================================================
    # QUERY OPERATIONS
    # ============================================================
    
    def list_keys(
        self,
        status: str = None,
        key_type: str = None,
        tags: List[str] = None
    ) -> List[KeyMetadata]:
        """
        List keys with optional filters.
        
        Args:
            status: Filter by status
            key_type: Filter by key type
            tags: Filter by tags
            
        Returns:
            List of KeyMetadata
        """
        with self._lock:
            results = list(self._metadata.values())
            
            if status:
                results = [m for m in results if m.status == status]
            
            if key_type:
                results = [m for m in results if m.key_type == key_type]
            
            if tags:
                results = [m for m in results if any(t in m.tags for t in tags)]
            
            return results
    
    def get_lifecycle_events(
        self,
        key_id: str = None,
        event_type: LifecycleEvent = None,
        limit: int = 100
    ) -> List[LifecycleEventRecord]:
        """
        Get lifecycle events.
        
        Args:
            key_id: Filter by key ID
            event_type: Filter by event type
            limit: Maximum events to return
            
        Returns:
            List of LifecycleEventRecord
        """
        with self._lock:
            results = self._events
            
            if key_id:
                results = [e for e in results if e.key_id == key_id]
            
            if event_type:
                results = [e for e in results if e.event_type == event_type]
            
            return results[-limit:]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get lifecycle manager statistics"""
        with self._lock:
            status_counts = {}
            for metadata in self._metadata.values():
                status_counts[metadata.status] = status_counts.get(metadata.status, 0) + 1
            
            return {
                "total_keys": len(self._metadata),
                "status_counts": status_counts,
                "total_events": len(self._events),
                "policy": self._policy.to_dict()
            }
    
    # ============================================================
    # WORKFLOW OPERATIONS
    # ============================================================
    
    def execute_workflow(
        self,
        workflow: str,
        key_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute a predefined workflow.
        
        Args:
            workflow: Workflow name (create_rotate, rotate_revoke, etc.)
            key_id: Key identifier
            **kwargs: Additional parameters
            
        Returns:
            Workflow result
        """
        workflows = {
            "create_rotate": self._workflow_create_rotate,
            "rotate_revoke": self._workflow_rotate_revoke,
            "create_expire": self._workflow_create_expire,
            "full_lifecycle": self._workflow_full_lifecycle
        }
        
        if workflow not in workflows:
            raise ValueError(f"Unknown workflow: {workflow}")
        
        return workflows[workflow](key_id, **kwargs)
    
    def _workflow_create_rotate(self, key_id: str, **kwargs) -> Dict[str, Any]:
        """Create key and immediately rotate"""
        created = self.create_key(key_id, **kwargs)
        rotated = self.rotate_key(key_id, **kwargs)
        return {
            "status": "success",
            "created": created.to_dict(),
            "rotated": rotated.to_dict()
        }
    
    def _workflow_rotate_revoke(self, key_id: str, **kwargs) -> Dict[str, Any]:
        """Rotate key then revoke"""
        rotated = self.rotate_key(key_id, **kwargs)
        revoked = self.revoke_key(key_id, **kwargs)
        return {
            "status": "success",
            "rotated": rotated.to_dict() if rotated else None,
            "revoked": revoked
        }
    
    def _workflow_create_expire(self, key_id: str, **kwargs) -> Dict[str, Any]:
        """Create key with expiration"""
        created = self.create_key(key_id, expires_in_days=kwargs.get("expires_in_days", 30), **kwargs)
        # Check expiration immediately
        self.check_and_expire_keys()
        metadata = self.get_key_metadata(key_id)
        return {
            "status": "success",
            "created": created.to_dict(),
            "expires_at": metadata.expires_at if metadata else None
        }
    
    def _workflow_full_lifecycle(
        self,
        key_id: str,
        rotate_count: int = 2,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute full lifecycle: create -> rotate multiple -> revoke"""
        # Create
        created = self.create_key(key_id, **kwargs)
        events = ["created"]
        
        # Rotate multiple times
        for i in range(rotate_count):
            self.rotate_key(key_id, **kwargs)
            events.append(f"rotated_{i+1}")
        
        # Revoke
        self.revoke_key(key_id, **kwargs)
        events.append("revoked")
        
        return {
            "status": "success",
            "key_id": key_id,
            "events": events,
            "final_metadata": self.get_key_metadata(key_id).to_dict()
        }


# Global lifecycle manager instance
_lifecycle_manager: Optional[KeyLifecycleManager] = None


def get_lifecycle_manager(
    policy: LifecyclePolicy = None,
    cache: KeyCacheInterface = None,
    secure_store: SecureKeyStoreInterface = None
) -> KeyLifecycleManager:
    """Get global lifecycle manager"""
    global _lifecycle_manager
    if _lifecycle_manager is None:
        _lifecycle_manager = KeyLifecycleManager(policy, cache, secure_store)
    return _lifecycle_manager
