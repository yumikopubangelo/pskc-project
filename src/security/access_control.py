# ============================================================
# PSKC — Access Control Module
# Network-level access control and authorization
# ============================================================
import ipaddress
from typing import List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class Permission(Enum):
    """Available permissions in PSKC"""
    KEY_READ = "key:read"
    KEY_WRITE = "key:write"
    KEY_DELETE = "key:delete"
    CACHE_READ = "cache:read"
    CACHE_WRITE = "cache:write"
    CACHE_DELETE = "cache:delete"
    ML_PREDICT = "ml:predict"
    ML_TRAIN = "ml:train"
    ADMIN = "admin"


@dataclass
class ServicePrincipal:
    """Represents a service/microservice identity"""
    service_id: str
    permissions: Set[Permission] = field(default_factory=set)
    allowed_networks: List[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    
    def has_permission(self, permission: Permission) -> bool:
        return permission in self.permissions
    
    def is_network_allowed(self, ip_address: str) -> bool:
        if not self.allowed_networks:
            return True  # No restrictions
        
        try:
            client_ip = ipaddress.ip_address(ip_address)
            for network in self.allowed_networks:
                if client_ip in ipaddress.ip_network(network):
                    return True
            return False
        except ValueError:
            logger.warning(f"Invalid IP address: {ip_address}")
            return False


@dataclass
class AccessPolicy:
    """Access control policy"""
    name: str
    principals: List[ServicePrincipal]
    default_permissions: Set[Permission] = field(default_factory=set)
    deny_by_default: bool = False
    
    def check_access(
        self, 
        service_id: str, 
        permission: Permission, 
        ip_address: str = None
    ) -> bool:
        """Check if a service has permission"""
        # Find principal
        principal = None
        for p in self.principals:
            if p.service_id == service_id:
                principal = p
                break
        
        if principal is None:
            return not self.deny_by_default
        
        # Check IP if provided
        if ip_address and not principal.is_network_allowed(ip_address):
            logger.warning(f"IP {ip_address} not allowed for service {service_id}")
            return False
        
        # Check permission
        return principal.has_permission(permission)


class AccessControlList:
    """Main access control implementation"""
    
    def __init__(self):
        self._policies: List[AccessPolicy] = []
        self._default_policy: Optional[AccessPolicy] = None
        self._initialize_default_policy()
    
    def _initialize_default_policy(self):
        """Setup default policy"""
        # Default service principals
        api_gateway = ServicePrincipal(
            service_id="api-gateway",
            permissions={
                Permission.KEY_READ,
                Permission.CACHE_READ,
                Permission.CACHE_WRITE,
                Permission.ML_PREDICT,
            },
            allowed_networks=["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
        )
        
        ml_service = ServicePrincipal(
            service_id="ml-service",
            permissions={
                Permission.KEY_READ,
                Permission.ML_PREDICT,
                Permission.ML_TRAIN,
            },
            allowed_networks=["10.0.0.0/8"]
        )
        
        admin_service = ServicePrincipal(
            service_id="admin-service",
            permissions={
                Permission.KEY_READ,
                Permission.KEY_WRITE,
                Permission.KEY_DELETE,
                Permission.CACHE_READ,
                Permission.CACHE_WRITE,
                Permission.CACHE_DELETE,
                Permission.ML_PREDICT,
                Permission.ML_TRAIN,
                Permission.ADMIN,
            },
            allowed_networks=["10.0.0.0/8"]
        )
        
        self._default_policy = AccessPolicy(
            name="default",
            principals=[api_gateway, ml_service, admin_service],
            deny_by_default=True
        )
    
    def register_service(
        self,
        service_id: str,
        permissions: Set[Permission],
        allowed_networks: List[str] = None
    ) -> ServicePrincipal:
        """Register a new service"""
        principal = ServicePrincipal(
            service_id=service_id,
            permissions=permissions,
            allowed_networks=allowed_networks or []
        )
        
        if self._default_policy:
            self._default_policy.principals.append(principal)
        
        logger.info(f"Registered service: {service_id}")
        return principal
    
    def check_permission(
        self,
        service_id: str,
        permission: Permission,
        ip_address: str = None
    ) -> bool:
        """Check if service has permission"""
        if self._default_policy:
            return self._default_policy.check_access(service_id, permission, ip_address)
        
        # No policy - deny by default
        return False
    
    def get_service(self, service_id: str) -> Optional[ServicePrincipal]:
        """Get service principal by ID"""
        if self._default_policy:
            for p in self._default_policy.principals:
                if p.service_id == service_id:
                    return p
        return None


# Global ACL instance
_acl_instance: Optional[AccessControlList] = None


def get_acl() -> AccessControlList:
    """Get global ACL instance"""
    global _acl_instance
    if _acl_instance is None:
        _acl_instance = AccessControlList()
    return _acl_instance


def check_permission(service_id: str, permission: Permission, ip_address: str = None) -> bool:
    """Convenience function to check permission"""
    return get_acl().check_permission(service_id, permission, ip_address)
