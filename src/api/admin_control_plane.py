# ============================================================
# PSKC — Admin and Ops Control Plane
# Provides operator control without direct shell/file system access
# ============================================================

import logging
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class AdminRole(Enum):
    """Admin role levels"""
    OBSERVER = "observer"      # Read-only access
    OPERATOR = "operator"      # Can manage cache and view all
    ADMIN = "admin"            # Full access including security


@dataclass
class AdminUser:
    """Admin user with role"""
    user_id: str
    role: AdminRole
    allowed_services: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


@dataclass
class AdminAuditEntry:
    """Audit entry for admin actions"""
    timestamp: float
    user_id: str
    action: str
    target: str
    outcome: str
    details: Dict[str, Any] = field(default_factory=dict)


class AdminAuthManager:
    """
    Manages authentication and authorization for admin endpoints.
    """
    
    def __init__(self):
        self._users: Dict[str, AdminUser] = {}
        self._api_keys: Dict[str, AdminUser] = {}
        self._audit_log: List[AdminAuditEntry] = []
        self._max_audit_entries = 10000
        
        # Default admin user for development
        self._add_default_users()
    
    def _add_default_users(self):
        """Add default admin users"""
        # Default admin - in production, this should be from config/secret
        self.register_user(
            user_id="admin",
            role=AdminRole.ADMIN,
            api_key="pskc-admin-key-dev",
            allowed_services=["*"]
        )
        self.register_user(
            user_id="operator",
            role=AdminRole.OPERATOR,
            api_key="pskc-operator-key-dev",
            allowed_services=["*"]
        )
        self.register_user(
            user_id="observer",
            role=AdminRole.OBSERVER,
            api_key="pskc-observer-key-dev",
            allowed_services=["*"]
        )
    
    def register_user(
        self,
        user_id: str,
        role: AdminRole,
        api_key: str,
        allowed_services: Optional[List[str]] = None
    ) -> bool:
        """Register a new admin user"""
        user = AdminUser(
            user_id=user_id,
            role=role,
            allowed_services=allowed_services or []
        )
        self._users[user_id] = user
        self._api_keys[api_key] = user
        logger.info(f"Registered admin user: {user_id} with role {role.value}")
        return True
    
    def authenticate(self, api_key: str) -> Optional[AdminUser]:
        """Authenticate using API key"""
        return self._api_keys.get(api_key)
    
    def authorize(
        self,
        user: AdminUser,
        required_role: AdminRole,
        target_service: Optional[str] = None
    ) -> bool:
        """Check if user has required role"""
        role_hierarchy = {
            AdminRole.OBSERVER: 0,
            AdminRole.OPERATOR: 1,
            AdminRole.ADMIN: 2,
        }
        
        # Check role hierarchy
        if role_hierarchy.get(user.role, 0) < role_hierarchy.get(required_role, 0):
            return False
        
        # Check service-level authorization
        if target_service and user.allowed_services:
            if "*" not in user.allowed_services:
                if target_service not in user.allowed_services:
                    return False
        
        return True
    
    def log_action(
        self,
        user_id: str,
        action: str,
        target: str,
        outcome: str,
        details: Optional[Dict[str, Any]] = None
    ):
        """Log admin action"""
        entry = AdminAuditEntry(
            timestamp=time.time(),
            user_id=user_id,
            action=action,
            target=target,
            outcome=outcome,
            details=details or {}
        )
        self._audit_log.append(entry)
        
        # Trim if too large
        if len(self._audit_log) > self._max_audit_entries:
            self._audit_log = self._audit_log[-self._max_audit_entries:]
    
    def get_audit_log(
        self,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get admin audit log"""
        results = self._audit_log
        
        if user_id:
            results = [e for e in results if e.user_id == user_id]
        if action:
            results = [e for e in results if e.action == action]
        
        results = results[-limit:]
        
        return [
            {
                "timestamp": e.timestamp,
                "user_id": e.user_id,
                "action": e.action,
                "target": e.target,
                "outcome": e.outcome,
                "details": e.details,
            }
            for e in results
        ]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get admin manager stats"""
        return {
            "total_users": len(self._users),
            "total_api_keys": len(self._api_keys),
            "audit_entries": len(self._audit_log),
            "roles": {
                "admin": sum(1 for u in self._users.values() if u.role == AdminRole.ADMIN),
                "operator": sum(1 for u in self._users.values() if u.role == AdminRole.OPERATOR),
                "observer": sum(1 for u in self._users.values() if u.role == AdminRole.OBSERVER),
            }
        }


class CacheAdminManager:
    """
    Admin operations for cache management.
    """
    
    def __init__(self, cache_manager=None):
        self._cache_manager = cache_manager
    
    def get_cache_summary(self) -> Dict[str, Any]:
        """Get comprehensive cache summary"""
        if not self._cache_manager:
            return {"error": "Cache manager not available"}
        
        try:
            stats = self._cache_manager.get_cache_stats()
            keys = self._cache_manager.get_cache_keys()
            
            # Group keys by service
            service_counts: Dict[str, int] = {}
            for key in keys:
                if ":" in key:
                    service_id, _ = key.split(":", 1)
                    service_counts[service_id] = service_counts.get(service_id, 0) + 1
            
            return {
                "total_keys": len(keys),
                "by_service": service_counts,
                "stats": stats,
                "timestamp": time.time(),
            }
        except Exception as e:
            logger.error(f"Error getting cache summary: {e}")
            return {"error": str(e)}
    
    def invalidate_by_prefix(self, prefix: str, service_id: Optional[str] = None) -> Dict[str, Any]:
        """Invalidate all keys matching prefix"""
        if not self._cache_manager:
            return {"error": "Cache manager not available"}
        
        try:
            keys = self._cache_manager.get_cache_keys()
            matching_keys = []
            
            for key in keys:
                # Match prefix
                if prefix and not key.startswith(prefix):
                    continue
                
                # Match service if specified
                if service_id:
                    if ":" not in key:
                        continue
                    key_service, _ = key.split(":", 1)
                    if key_service != service_id:
                        continue
                
                matching_keys.append(key)
            
            # Delete matching keys
            deleted = 0
            for key in matching_keys:
                if ":" in key:
                    _, key_id = key.split(":", 1)
                    key_service, _ = key.split(":", 1)
                    if self._cache_manager.secure_delete(key_id, key_service, "admin_invalidate_prefix"):
                        deleted += 1
            
            return {
                "prefix": prefix,
                "service_id": service_id,
                "matched": len(matching_keys),
                "deleted": deleted,
                "timestamp": time.time(),
            }
        except Exception as e:
            logger.error(f"Error invalidating by prefix: {e}")
            return {"error": str(e)}
    
    def inspect_key_ttl(self, key_id: str, service_id: str) -> Dict[str, Any]:
        """Inspect TTL of a specific key"""
        if not self._cache_manager:
            return {"error": "Cache manager not available"}
        
        try:
            # Get from encrypted store
            key_data, cache_hit, latency = self._cache_manager.secure_get(key_id, service_id)
            
            if not cache_hit:
                return {
                    "key_id": key_id,
                    "service_id": service_id,
                    "exists": False,
                    "timestamp": time.time(),
                }
            
            # TTL info - approximate based on implementation
            return {
                "key_id": key_id,
                "service_id": service_id,
                "exists": True,
                "cache_hit": cache_hit,
                "latency_ms": latency,
                "timestamp": time.time(),
            }
        except Exception as e:
            logger.error(f"Error inspecting key TTL: {e}")
            return {"error": str(e)}
    
    def get_warmup_status(self) -> Dict[str, Any]:
        """Get cache warmup status"""
        # This would typically track prefetch/warmup status
        return {
            "warmup_enabled": True,
            "last_warmup": time.time() - 3600,  # Mock - 1 hour ago
            "keys_warmed": 0,
            "status": "idle",
            "timestamp": time.time(),
        }
    
    def trigger_warmup(self, service_id: Optional[str] = None) -> Dict[str, Any]:
        """Trigger cache warmup"""
        # This would typically trigger prefetch workers
        return {
            "service_id": service_id or "all",
            "warmup_triggered": True,
            "estimated_duration_seconds": 60,
            "timestamp": time.time(),
        }


class ModelAdminManager:
    """
    Admin operations for model management.
    """
    
    def __init__(self, model_registry=None):
        self._registry = model_registry
    
    def get_versions_by_stage(self) -> Dict[str, Any]:
        """Get model versions by stage"""
        if not self._registry:
            return {"error": "Model registry not available"}
        
        try:
            # Get all models from registry
            models = self._registry.list_models()
            
            stages = {}
            for model in models:
                stage = model.get("stage", "unknown")
                if stage not in stages:
                    stages[stage] = []
                stages[stage].append(model)
            
            return {
                "stages": stages,
                "timestamp": time.time(),
            }
        except Exception as e:
            logger.error(f"Error getting versions by stage: {e}")
            return {"error": str(e)}
    
    def get_active_version_history(self, model_name: str) -> Dict[str, Any]:
        """Get history of active version changes"""
        if not self._registry:
            return {"error": "Model registry not available"}
        
        try:
            # Get lifecycle events for the model
            lifecycle = self._registry.get_lifecycle_events(model_name)
            
            # Filter for promotion/rollback events
            history = [
                e for e in lifecycle 
                if e.get("event_type") in ["PROMOTION", "ROLLBACK", "CREATED"]
            ]
            
            return {
                "model_name": model_name,
                "history": history,
                "total_changes": len(history),
                "timestamp": time.time(),
            }
        except Exception as e:
            logger.error(f"Error getting active version history: {e}")
            return {"error": str(e)}
    
    def compare_registry_entries(
        self,
        version1: str,
        version2: str,
        model_name: str
    ) -> Dict[str, Any]:
        """Compare two model registry entries"""
        if not self._registry:
            return {"error": "Model registry not available"}
        
        try:
            # Get both versions
            v1 = self._registry.get_model(model_name, version1)
            v2 = self._registry.get_model(model_name, version2)
            
            if not v1 or not v2:
                return {"error": "One or both versions not found"}
            
            # Compare key fields
            comparisons = {}
            for key in ["created_at", "accuracy", "stage", "checksum"]:
                v1_val = v1.get(key)
                v2_val = v2.get(key)
                comparisons[key] = {
                    "version1": v1_val,
                    "version2": v2_val,
                    "different": v1_val != v2_val,
                }
            
            return {
                "model_name": model_name,
                "version1": version1,
                "version2": version2,
                "comparisons": comparisons,
                "timestamp": time.time(),
            }
        except Exception as e:
            logger.error(f"Error comparing registry entries: {e}")
            return {"error": str(e)}
    
    def export_lifecycle_summary(self, model_name: str) -> Dict[str, Any]:
        """Export full lifecycle summary for a model"""
        if not self._registry:
            return {"error": "Model registry not available"}
        
        try:
            lifecycle = self._registry.get_lifecycle_events(model_name)
            
            # Summarize by event type
            event_counts = {}
            for event in lifecycle:
                event_type = event.get("event_type", "unknown")
                event_counts[event_type] = event_counts.get(event_type, 0) + 1
            
            return {
                "model_name": model_name,
                "total_events": len(lifecycle),
                "event_counts": event_counts,
                "events": lifecycle,
                "timestamp": time.time(),
            }
        except Exception as e:
            logger.error(f"Error exporting lifecycle summary: {e}")
            return {"error": str(e)}


class SecurityAdminManager:
    """
    Admin operations for security management.
    """
    
    def __init__(self, ids=None, audit_logger=None):
        self._ids = ids
        self._audit_logger = audit_logger
    
    def get_intrusion_summary(self) -> Dict[str, Any]:
        """Get intrusion detection summary"""
        if not self._ids:
            return {"error": "IDS not available"}
        
        try:
            stats = self._ids.get_stats()
            alerts = self._ids.get_alerts(limit=100)
            
            # Count by threat level
            threat_counts = {}
            for alert in alerts:
                level = alert.threat_level.value
                threat_counts[level] = threat_counts.get(level, 0) + 1
            
            # Count by event type
            event_counts = {}
            for alert in alerts:
                event = alert.event.value
                event_counts[event] = event_counts.get(event, 0) + 1
            
            return {
                "stats": stats,
                "threat_counts": threat_counts,
                "event_counts": event_counts,
                "recent_alerts": len(alerts),
                "timestamp": time.time(),
            }
        except Exception as e:
            logger.error(f"Error getting intrusion summary: {e}")
            return {"error": str(e)}
    
    def get_blocked_ips(self) -> Dict[str, Any]:
        """Get list of currently blocked IPs"""
        if not self._ids:
            return {"error": "IDS not available"}
        
        try:
            with self._ids._lock:
                blocked = [
                    {
                        "ip": ip,
                        "reputation": rep,
                        "blocked": rep <= self._ids._reputation_block_threshold,
                    }
                    for ip, rep in self._ids._ip_reputation.items()
                    if rep <= self._ids._reputation_block_threshold
                ]
            
            return {
                "blocked_ips": blocked,
                "total_blocked": len(blocked),
                "threshold": self._ids._reputation_block_threshold,
                "timestamp": time.time(),
            }
        except Exception as e:
            logger.error(f"Error getting blocked IPs: {e}")
            return {"error": str(e)}
    
    def get_reputation_view(self) -> Dict[str, Any]:
        """Get IP reputation overview"""
        if not self._ids:
            return {"error": "IDS not available"}
        
        try:
            with self._ids._lock:
                reputations = list(self._ids._ip_reputation.items())
            
            # Sort by reputation
            reputations.sort(key=lambda x: x[1])
            
            # Get extremes
            worst = reputations[:10] if len(reputations) >= 10 else reputations
            best = reputations[-10:] if len(reputations) >= 10 else reputations
            
            return {
                "total_tracked": len(reputations),
                "worst_reputation": [{"ip": ip, "score": score} for ip, score in worst],
                "best_reputation": [{"ip": ip, "score": score} for ip, score in best],
                "threshold_block": self._ids._reputation_block_threshold,
                "timestamp": time.time(),
            }
        except Exception as e:
            logger.error(f"Error getting reputation view: {e}")
            return {"error": str(e)}
    
    def get_audit_recovery_history(self) -> Dict[str, Any]:
        """Get audit log recovery history"""
        # This would typically check for audit log gaps/fixes
        return {
            "recoveries": [],
            "gaps_detected": 0,
            "last_check": time.time(),
            "timestamp": time.time(),
        }
    
    def unblock_ip(self, ip_address: str) -> Dict[str, Any]:
        """Unblock a specific IP"""
        if not self._ids:
            return {"error": "IDS not available"}
        
        try:
            old_reputation = self._ids._ip_reputation.get(ip_address, 0)
            self._ids.update_reputation(ip_address, -old_reputation + 1)  # Reset to neutral
            new_reputation = self._ids._ip_reputation.get(ip_address, 0)
            
            return {
                "ip_address": ip_address,
                "old_reputation": old_reputation,
                "new_reputation": new_reputation,
                "unblocked": True,
                "timestamp": time.time(),
            }
        except Exception as e:
            logger.error(f"Error unblocking IP: {e}")
            return {"error": str(e)}


# Global instances
_admin_auth_manager: Optional[AdminAuthManager] = None
_cache_admin_manager: Optional[CacheAdminManager] = None
_model_admin_manager: Optional[ModelAdminManager] = None
_security_admin_manager: Optional[SecurityAdminManager] = None


def get_admin_auth_manager() -> AdminAuthManager:
    """Get or create admin auth manager"""
    global _admin_auth_manager
    if _admin_auth_manager is None:
        _admin_auth_manager = AdminAuthManager()
    return _admin_auth_manager


def get_cache_admin_manager(cache_manager=None) -> CacheAdminManager:
    """Get or create cache admin manager"""
    global _cache_admin_manager
    if _cache_admin_manager is None:
        _cache_admin_manager = CacheAdminManager(cache_manager)
    return _cache_admin_manager


def get_model_admin_manager(model_registry=None) -> ModelAdminManager:
    """Get or create model admin manager"""
    global _model_admin_manager
    if _model_admin_manager is None:
        _model_admin_manager = ModelAdminManager(model_registry)
    return _model_admin_manager


def get_security_admin_manager(ids=None, audit_logger=None) -> SecurityAdminManager:
    """Get or create security admin manager"""
    global _security_admin_manager
    if _security_admin_manager is None:
        _security_admin_manager = SecurityAdminManager(ids, audit_logger)
    return _security_admin_manager


def initialize_admin_managers(
    cache_manager=None,
    model_registry=None,
    ids=None,
    audit_logger=None
):
    """Initialize all admin managers with dependencies"""
    global _cache_admin_manager, _model_admin_manager, _security_admin_manager
    
    _cache_admin_manager = CacheAdminManager(cache_manager)
    _model_admin_manager = ModelAdminManager(model_registry)
    _security_admin_manager = SecurityAdminManager(ids, audit_logger)
    
    logger.info("Admin managers initialized")
