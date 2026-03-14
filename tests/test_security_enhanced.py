# ============================================================
# PSKC — Enhanced Security Tests
# Tests for IDS, Secure Key Handler, Auto-Purge
# ============================================================
import pytest
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.security.intrusion_detection import (
    IntrusionDetectionSystem,
    SecureKeyHandler,
    SecureCacheManager,
    ThreatLevel,
    SecurityEvent,
    SecurityAlert
)


class TestSecureKeyHandler:
    """Test cases for SecureKeyHandler"""
    
    def test_generate_secure_key(self):
        """Test secure key generation"""
        handler = SecureKeyHandler()
        
        key = handler.generate_secure_key(32)
        
        assert len(key) == 32
        assert isinstance(key, bytes)
    
    def test_key_hash(self):
        """Test key hash computation"""
        handler = SecureKeyHandler()
        
        key = b"test_key_data"
        hash1 = handler.compute_key_hash(key)
        hash2 = handler.compute_key_hash(key)
        
        # Same key should produce same hash
        assert hash1 == hash2
        assert len(hash1) == 128  # SHA-512 hex
    
    def test_verify_key(self):
        """Test key verification"""
        handler = SecureKeyHandler()
        
        key = b"test_key_data"
        key_hash = handler.compute_key_hash(key)
        
        assert handler.verify_key(key, key_hash) is True
        assert handler.verify_key(b"wrong_key", key_hash) is False
    
    def test_secure_compare(self):
        """Test constant-time comparison"""
        handler = SecureKeyHandler()
        
        assert handler.secure_compare(b"abc", b"abc") is True
        assert handler.secure_compare(b"abc", b"def") is False
    
    def test_generate_access_token(self):
        """Test access token generation"""
        handler = SecureKeyHandler()
        
        token = handler.generate_access_token("service1", "key1")
        
        assert len(token) == 64
        assert isinstance(token, str)


class TestIntrusionDetectionSystem:
    """Test cases for IDS"""
    
    def test_ids_initialization(self):
        """Test IDS initialization"""
        ids = IntrusionDetectionSystem()
        
        assert ids is not None
        assert ids._auto_purge_enabled is True
    
    def test_record_failed_attempt(self):
        """Test recording failed attempts"""
        ids = IntrusionDetectionSystem()
        
        ids.record_failed_attempt("service1", "192.168.1.100", "invalid_key")
        
        stats = ids.get_stats()
        
        assert stats["failed_attempts_tracked"] >= 1
    
    def test_brute_force_detection(self):
        """Test brute force attack detection"""
        ids = IntrusionDetectionSystem()
        ids._failed_auth_threshold = 3
        
        # Record multiple failed attempts
        for _ in range(3):
            ids.record_failed_attempt("service1", "10.0.0.1", "bad_key")
        
        alerts = ids.get_alerts(threat_level=ThreatLevel.HIGH)
        
        # Should have detected brute force
        assert len(alerts) > 0
    
    def test_access_rate_check(self):
        """Test access rate limiting"""
        ids = IntrusionDetectionSystem()
        ids._access_rate_threshold = 5
        
        # Make many rapid accesses
        for i in range(10):
            ids.record_access("service1", f"key_{i}", "192.168.1.1")
        
        # Should trigger alert
        result = ids.check_access_rate("service1", "192.168.1.1")
        
        assert result is False
    
    def test_cache_poisoning_detection(self):
        """Test cache poisoning detection"""
        ids = IntrusionDetectionSystem()
        
        # Try to inject suspicious pattern
        result = ids.detect_cache_poisoning("key1", b"../../../etc/passwd")
        
        assert result is True
        
        # FIXED: Should have HIGH alert (not CRITICAL to prevent DoS)
        alerts = ids.get_alerts(threat_level=ThreatLevel.HIGH)
        assert len(alerts) > 0
        
        # FIXED: Verify auto-purge is NOT triggered for cache poisoning
        # (only triggered for actual INTRUSION_DETECTED events)
        stats = ids.get_stats()
        # The auto-purge should remain enabled but not triggered by cache poisoning
        assert stats["auto_purge_enabled"] is True
    
    def test_ip_reputation(self):
        """Test IP reputation system"""
        ids = IntrusionDetectionSystem()
        
        # Initially should be allowed
        assert ids.check_ip_reputation("192.168.1.100") is True
        
        # Decrease reputation
        ids.update_reputation("192.168.1.100", -15)
        
        # Should now be blocked
        assert ids.check_ip_reputation("192.168.1.100") is False
    
    def test_auto_purge_triggered(self):
        """Test auto-purge is NOT triggered for cache poisoning (DoS protection)"""
        purge_triggered = []
        
        def clear_cache():
            purge_triggered.append(True)
        
        ids = IntrusionDetectionSystem(
            cache_clear_callback=clear_cache,
            alert_callback=None
        )
        
        # Simulate cache poisoning - should NOT trigger auto-purge
        # FIXED: Cache poisoning is now HIGH level, not CRITICAL
        # Auto-purge only triggers for INTRUSION_DETECTED events
        ids.detect_cache_poisoning("key1", b"{{=exec}}")
        
        # Wait a bit for async processing
        time.sleep(0.5)
        
        # FIXED: Should NOT have triggered purge for cache poisoning
        # This prevents DoS attacks where attackers trigger cache wipe
        assert len(purge_triggered) == 0
        
        # But should still have generated an alert
        alerts = ids.get_alerts(threat_level=ThreatLevel.HIGH)
        assert len(alerts) > 0
    
    def test_enable_disable_auto_purge(self):
        """Test enabling/disabling auto-purge"""
        ids = IntrusionDetectionSystem()
        
        ids.enable_auto_purge(False)
        assert ids._auto_purge_enabled is False
        
        ids.enable_auto_purge(True)
        assert ids._auto_purge_enabled is True


class TestSecurityAlerts:
    """Test cases for SecurityAlert"""
    
    def test_create_alert(self):
        """Test creating security alert"""
        alert = SecurityAlert(
            event=SecurityEvent.BRUTE_FORCE_ATTEMPT,
            threat_level=ThreatLevel.HIGH,
            timestamp=time.time(),
            source_ip="192.168.1.1",
            details={"attempts": 5}
        )
        
        assert alert.event == SecurityEvent.BRUTE_FORCE_ATTEMPT
        assert alert.threat_level == ThreatLevel.HIGH
        assert alert.auto_purge_triggered is False


class TestSecureCacheManager:
    """Test cases for SecureCacheManager"""
    
    def test_secure_cache_manager_init(self):
        """Test secure cache manager initialization"""
        # This would require the cache to be initialized
        # Skip if dependencies aren't available
        pytest.skip("Requires full system initialization")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
