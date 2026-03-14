# ============================================================
# PSKC — Security Module Tests
# ============================================================
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.security.encryption import AES256Encryptor, KeyDerivation, EncryptionContext
from src.security.access_control import AccessControlList, ServicePrincipal, Permission
from src.security.audit_logger import AuditLogger, AuditEvent, AuditEventType


class TestAES256Encryption:
    """Test cases for AES-256 encryption"""
    
    def test_encrypt_decrypt(self):
        """Test encryption and decryption"""
        key = "test_key_32_characters_long!!"
        encryptor = AES256Encryptor(key)
        
        plaintext = b"Hello, PSKC!"
        
        ciphertext, iv = encryptor.encrypt(plaintext)
        
        assert ciphertext != plaintext
        assert len(iv) == 16
        
        decrypted = encryptor.decrypt(ciphertext, iv)
        
        assert decrypted == plaintext
    
    def test_encrypt_hex(self):
        """Test hex encoding"""
        key = "test_key_32_characters_long!!"
        encryptor = AES256Encryptor(key)
        
        plaintext = b"Test data"
        
        encrypted_hex = encryptor.encrypt_hex(plaintext)
        decrypted = encryptor.decrypt_hex(encrypted_hex)
        
        assert decrypted == plaintext
    
    def test_key_derivation(self):
        """Test key derivation from password"""
        password = "secure_password"
        
        key, salt = KeyDerivation.derive_key_from_password(password)
        
        assert len(key) == 32
        assert len(salt) == 16
    
    def test_random_key_generation(self):
        """Test random key generation"""
        key = KeyDerivation.generate_random_key(32)
        
        assert len(key) == 32
    
    def test_encryption_context(self):
        """Test encryption context"""
        key = "test_key_32_characters_long!!"
        
        context = EncryptionContext(key)
        
        assert context.encryptor is not None
        
        # Test key rotation
        new_key = "new_key_32_characters_long!!!"
        new_context = context.rotate_key(new_key)
        
        assert new_context.encryptor is not None


class TestAccessControl:
    """Test cases for Access Control"""
    
    def test_acl_initialization(self):
        """Test ACL initialization"""
        acl = AccessControlList()
        
        assert acl._default_policy is not None
    
    def test_register_service(self):
        """Test service registration"""
        acl = AccessControlList()
        
        principal = acl.register_service(
            service_id="test_service",
            permissions={Permission.KEY_READ},
            allowed_networks=["10.0.0.0/8"]
        )
        
        assert principal is not None
        assert principal.service_id == "test_service"
    
    def test_check_permission(self):
        """Test permission check"""
        acl = AccessControlList()
        
        # Default services should have permissions
        has_permission = acl.check_permission(
            "api-gateway",
            Permission.KEY_READ
        )
        
        assert has_permission is True
    
    def test_check_permission_denied(self):
        """Test permission denied"""
        acl = AccessControlList()
        
        # Non-existent service should be denied
        has_permission = acl.check_permission(
            "unknown_service",
            Permission.ADMIN
        )
        
        assert has_permission is False
    
    def test_service_principal(self):
        """Test ServicePrincipal"""
        principal = ServicePrincipal(
            service_id="test_service",
            permissions={Permission.KEY_READ, Permission.KEY_WRITE},
            allowed_networks=["192.168.1.0/24"]
        )
        
        assert principal.has_permission(Permission.KEY_READ)
        assert principal.has_permission(Permission.KEY_WRITE)
        assert not principal.has_permission(Permission.ADMIN)
    
    def test_ip_allowed(self):
        """Test IP-based access"""
        principal = ServicePrincipal(
            service_id="test_service",
            permissions={Permission.KEY_READ},
            allowed_networks=["192.168.1.0/24"]
        )
        
        assert principal.is_network_allowed("192.168.1.100")
        assert not principal.is_network_allowed("10.0.0.1")


class TestAuditLogger:
    """Test cases for Audit Logger"""
    
    def test_logger_initialization(self):
        """Test logger initialization"""
        logger = AuditLogger(max_events=1000)
        
        assert logger is not None
    
    def test_log_key_access(self):
        """Test logging key access"""
        logger = AuditLogger(max_events=1000)
        
        logger.log_key_access(
            key_id="key1",
            service_id="service1",
            cache_hit=True,
            latency_ms=5.0
        )
        
        stats = logger.get_event_counts()
        
        assert stats.get("key_cache_hit", 0) > 0
    
    def test_log_auth_success(self):
        """Test logging successful auth"""
        logger = AuditLogger(max_events=1000)
        
        logger.log_auth(
            service_id="service1",
            success=True
        )
        
        stats = logger.get_event_counts()
        
        assert stats.get("auth_success", 0) > 0
    
    def test_log_auth_failure(self):
        """Test logging failed auth"""
        logger = AuditLogger(max_events=1000)
        
        logger.log_auth(
            service_id="service1",
            success=False,
            reason="Invalid key"
        )
        
        stats = logger.get_event_counts()
        
        assert stats.get("auth_failure", 0) > 0
    
    def test_get_cache_hit_rate(self):
        """Test cache hit rate calculation"""
        logger = AuditLogger(max_events=1000)
        
        # Log some hits and misses
        for _ in range(8):
            logger.log_key_access("key1", "service1", True, 5.0)
        
        for _ in range(2):
            logger.log_key_access("key2", "service1", False, 50.0)
        
        hit_rate = logger.get_cache_hit_rate()
        
        assert hit_rate == 0.8
    
    def test_get_average_latency(self):
        """Test average latency calculation"""
        logger = AuditLogger(max_events=1000)
        
        logger.log_key_access("key1", "service1", True, 10.0)
        logger.log_key_access("key2", "service1", False, 20.0)
        
        avg_latency = logger.get_average_latency()
        
        assert avg_latency == 15.0
    
    def test_get_recent_events(self):
        """Test getting recent events"""
        logger = AuditLogger(max_events=1000)
        
        logger.log_key_access("key1", "service1", True, 5.0)
        
        events = logger.get_recent_events(limit=10)
        
        assert len(events) > 0
    
    def test_security_violation_logging(self):
        """Test security violation logging"""
        logger = AuditLogger(max_events=1000)
        
        logger.log_security_violation(
            service_id="test_service",
            violation_type="unauthorized_access",
            details={"path": "/admin", "ip": "10.0.0.1"}
        )
        
        events = logger.get_recent_events(event_type=AuditEventType.SECURITY_VIOLATION)
        
        assert len(events) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
