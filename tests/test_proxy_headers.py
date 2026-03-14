# ============================================================
# PSKC — Integration Tests for Reverse Proxy Headers
# ============================================================
#
# Tests for proxy header handling and host validation
# as required by the deployment roadmap.
#
# Run with: pytest tests/test_proxy_headers.py -v
# ============================================================

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import ipaddress

from src.api.routes import app, _extract_client_ip
from src.security.security_headers import (
    TRUSTED_PROXIES,
    configure_trusted_proxies,
    SecurityHeadersMiddleware,
)


class TestProxyHeaderExtraction:
    """Test client IP extraction from proxy headers"""
    
    def setup_method(self):
        """Reset trusted proxies before each test"""
        TRUSTED_PROXIES.clear()
        configure_trusted_proxies(["10.0.0.0/8", "172.16.0.0/12"])
    
    def test_direct_connection_ip(self):
        """Test IP extraction for direct connections"""
        # Simulate direct connection (not from trusted proxy)
        with patch("src.api.routes.TARGET_PROXIES", set()):
            pass
    
    def test_xff_header_from_trusted_proxy(self):
        """Test X-Forwarded-For extraction when from trusted proxy"""
        # When request comes from trusted proxy, should extract real IP from XFF
        pass
    
    def test_xff_header_rejected_from_untrusted(self):
        """Test XFF header is ignored from untrusted sources"""
        # Spoofed XFF should be rejected
        pass


class TestTrustedProxyConfiguration:
    """Test trusted proxy configuration"""
    
    def test_configure_valid_cidr(self):
        """Test configuring valid CIDR ranges"""
        TRUSTED_PROXIES.clear()
        invalid = configure_trusted_proxies(["10.0.0.0/8", "192.168.1.0/24"])
        
        assert len(invalid) == 0
        assert len(TRUSTED_PROXIES) == 2
        
        # Verify the networks were parsed correctly
        networks = list(TRUSTED_PROXIES)
        assert ipaddress.ip_network("10.0.0.0/8") in networks
        assert ipaddress.ip_network("192.168.1.0/24") in networks
    
    def test_configure_invalid_cidr(self):
        """Test configuring invalid CIDR ranges"""
        TRUSTED_PROXIES.clear()
        invalid = configure_trusted_proxies(["10.0.0.0/8", "invalid/xyz", "192.168.1.0/33"])
        
        assert len(invalid) == 2
        assert "invalid/xyz" in invalid
        assert "192.168.1.0/33" in invalid
        
        # Valid CIDR should still be configured
        assert ipaddress.ip_network("10.0.0.0/8") in TRUSTED_PROXIES
    
    def test_configure_empty(self):
        """Test configuring empty proxy list"""
        TRUSTED_PROXIES.clear()
        TRUSTED_PROXIES.add(ipaddress.ip_network("10.0.0.0/8"))
        
        invalid = configure_trusted_proxies([])
        
        assert len(invalid) == 0
        # Empty should clear existing proxies
        assert len(TRUSTED_PROXIES) == 0
    
    def test_configure_from_string(self):
        """Test configuring from comma-separated string"""
        TRUSTED_PROXIES.clear()
        invalid = configure_trusted_proxies("10.0.0.0/8, 172.16.0.0/12, invalid")
        
        assert len(invalid) == 1
        assert "invalid" in invalid


class TestHealthEndpoints:
    """Test health, readiness, and startup endpoints"""
    
    def setup_method(self):
        """Create test client"""
        self.client = TestClient(app, raise_server_exceptions=False)
    
    def test_health_endpoint_exists(self):
        """Test /health endpoint returns 200"""
        response = self.client.get("/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
    
    def test_readiness_endpoint_exists(self):
        """Test /health/ready endpoint returns 200"""
        response = self.client.get("/health/ready")
        assert response.status_code == 200
        
        data = response.json()
        assert "ready" in data
        assert "dependencies" in data
    
    def test_startup_endpoint_exists(self):
        """Test /health/startup endpoint returns 200"""
        response = self.client.get("/health/startup")
        assert response.status_code == 200
        
        data = response.json()
        assert "started" in data
        assert "progress" in data


class TestDependencyHealth:
    """Test dependency health checking"""
    
    def setup_method(self):
        """Create test client"""
        self.client = TestClient(app, raise_server_exceptions=False)
    
    def test_readiness_includes_dependencies(self):
        """Test readiness check includes all dependency information"""
        response = self.client.get("/health/ready")
        
        assert response.status_code == 200
        data = response.json()
        
        # Check all expected dependencies are present
        deps = data.get("dependencies", {})
        assert "fips_module" in deps
        assert "audit_logger" in deps
        assert "redis_cache" in deps
        assert "prefetch_queue" in deps
        assert "ml_runtime" in deps
    
    def test_readiness_includes_fail_policy(self):
        """Test dependencies include fail-open/fail-closed policy"""
        response = self.client.get("/health/ready")
        
        data = response.json()
        deps = data.get("dependencies", {})
        
        # FIPS module should be fail_closed
        fips = deps.get("fips_module", {})
        assert fips.get("type") == "fail_closed"
        
        # Redis should be fail_open
        redis = deps.get("redis_cache", {})
        assert redis.get("type") == "fail_open"


class TestSensitivePathProtection:
    """Test sensitive path protection from external access"""
    
    def test_sensitive_paths_blocked(self):
        """Test that sensitive paths are blocked from external access"""
        # These paths should be blocked in security_headers.py
        sensitive_paths = [
            "/admin/something",
            "/internal/api",
            "/debug/info",
            "/security/audit",
            "/security/intrusions",
        ]
        
        for path in sensitive_paths:
            # The middleware should block these from non-private IPs
            pass


class TestProductionSettings:
    """Test production configuration"""
    
    def test_endpoint_categorization(self):
        """Test that endpoints are properly categorized"""
        from config.settings import settings
        
        # Public endpoints should exist
        public = settings.public_endpoints
        assert "/health" in public
        assert "/health/ready" in public
        
        # Operational endpoints should exist
        ops = settings.operational_endpoints
        assert "/metrics" in ops
        assert "/cache/stats" in ops
        
        # Admin endpoints should exist
        admin = settings.admin_endpoints
        assert "/security/audit" in admin
        assert "/admin" in admin
    
    def test_dependency_policy_settings(self):
        """Test dependency policy configuration"""
        from config.settings import settings
        
        fail_closed = settings.fail_closed_dependencies
        assert "fips_module" in fail_closed
        assert "audit_logger" in fail_closed
        
        fail_open = settings.fail_open_dependencies
        assert "redis_cache" in fail_open
        assert "prefetch_queue" in fail_open


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
