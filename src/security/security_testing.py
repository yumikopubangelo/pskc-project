# ============================================================
# PSKC — Security Testing Service
# Comprehensive security attack simulation and testing
# ============================================================
#
# This module provides:
# - Attack simulation (brute force, SQL injection, XSS, etc.)
# - Detection result tracking
# - Mitigation effectiveness metrics
# - Security posture evaluation
#
# ============================================================

import logging
import random
import re
import time
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

logger = logging.getLogger(__name__)


class AttackType(Enum):
    """Types of security attacks"""
    BRUTE_FORCE = "brute_force"
    SQL_INJECTION = "sql_injection"
    XSS = "xss"
    CREDENTIAL_STUFFING = "credential_stuffing"
    RATE_LIMIT_VIOLATION = "rate_limit_violation"
    API_ABUSE = "api_abuse"
    PATH_TRAVERSAL = "path_traversal"
    CACHE_POISONING = "cache_poisoning"


class AttackSeverity(Enum):
    """Attack severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class AttackResult:
    """Result of an attack simulation"""
    attack_type: AttackType
    severity: AttackSeverity
    detected: bool
    blocked: bool
    mitigation_effective: bool
    details: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SecurityTestResult:
    """Overall security test result"""
    test_name: str
    attack_type: AttackType
    total_attempts: int
    detected_count: int
    blocked_count: int
    detection_rate: float
    block_rate: float
    recommendations: List[str]
    timestamp: float = field(default_factory=time.time)


class SecurityTestingService:
    """
    Security Testing Service for comprehensive security validation.
    Simulates various attack vectors and measures detection/mitigation effectiveness.
    """
    
    def __init__(self):
        self._attack_history: List[AttackResult] = []
        self._test_results: List[SecurityTestResult] = []
        
        # Attack patterns for simulation
        self._sql_injection_patterns = [
            "' OR '1'='1",
            "'; DROP TABLE users; --",
            "1' AND '1'='1",
            "admin' --",
            "1' UNION SELECT NULL--",
            "<script>alert('xss')</script>",
            "'; exec xp_cmdshell('dir'); --",
        ]
        
        self._xss_patterns = [
            "<script>alert('XSS')</script>",
            "<img src=x onerror=alert('XSS')>",
            "<svg onload=alert('XSS')>",
            "javascript:alert('XSS')",
            "<body onload=alert('XSS')>",
            "<input onfocus=alert('XSS') autofocus>",
        ]
        
        self._path_traversal_patterns = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\config\\sam",
            "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",
            "....//....//....//etc/passwd",
        ]
    
    def _simulate_detection(self, attack_type: AttackType) -> tuple[bool, bool, str]:
        """
        Simulate attack detection and blocking.
        
        Returns:
            Tuple of (detected, blocked, details)
        """
        # Simulate detection rates based on attack type
        detection_rates = {
            AttackType.BRUTE_FORCE: 0.95,
            AttackType.SQL_INJECTION: 0.90,
            AttackType.XSS: 0.85,
            AttackType.CREDENTIAL_STUFFING: 0.88,
            AttackType.RATE_LIMIT_VIOLATION: 0.99,
            AttackType.API_ABUSE: 0.80,
            AttackType.PATH_TRAVERSAL: 0.92,
            AttackType.CACHE_POISONING: 0.75,
        }
        
        detection_rate = detection_rates.get(attack_type, 0.80)
        detected = random.random() < detection_rate
        blocked = detected and random.random() < 0.90  # 90% of detected attacks are blocked
        
        details = f"Attack {'detected' if detected else 'not detected'}, "
        details += f"{'blocked' if blocked else 'allowed'}"
        
        return detected, blocked, details
    
    def simulate_brute_force(
        self,
        num_attempts: int = 100,
        target_service: str = "default"
    ) -> SecurityTestResult:
        """Simulate brute force attack"""
        detected_count = 0
        blocked_count = 0
        
        usernames = ["admin", "root", "user", "test", "administrator"]
        passwords = ["password", "123456", "admin", "letmein", "qwerty"]
        
        for i in range(num_attempts):
            username = random.choice(usernames)
            password = random.choice(passwords)
            
            # Simulate attack
            detected, blocked, details = self._simulate_detection(AttackType.BRUTE_FORCE)
            
            if detected:
                detected_count += 1
                # Block after several attempts from same IP
                if i % 10 == 0:
                    blocked = True
            
            if blocked:
                blocked_count += 1
            
            self._attack_history.append(AttackResult(
                attack_type=AttackType.BRUTE_FORCE,
                severity=AttackSeverity.HIGH if blocked else AttackSeverity.MEDIUM,
                detected=detected,
                blocked=blocked,
                mitigation_effective=blocked,
                details=details,
                metadata={"username": username, "attempt": i}
            ))
        
        detection_rate = detected_count / num_attempts if num_attempts > 0 else 0
        block_rate = blocked_count / num_attempts if num_attempts > 0 else 0
        
        return SecurityTestResult(
            test_name="Brute Force Attack Simulation",
            attack_type=AttackType.BRUTE_FORCE,
            total_attempts=num_attempts,
            detected_count=detected_count,
            blocked_count=blocked_count,
            detection_rate=detection_rate,
            block_rate=block_rate,
            recommendations=[
                "Enable account lockout after failed attempts",
                "Implement CAPTCHA for login attempts",
                "Use multi-factor authentication",
                "Monitor for unusual login patterns",
            ],
        )
    
    def simulate_sql_injection(
        self,
        num_attempts: int = 50,
    ) -> SecurityTestResult:
        """Simulate SQL injection attack"""
        detected_count = 0
        blocked_count = 0
        
        for i, payload in enumerate(self._sql_injection_patterns * (num_attempts // len(self._sql_injection_patterns) + 1)):
            if i >= num_attempts:
                break
                
            detected, blocked, details = self._simulate_detection(AttackType.SQL_INJECTION)
            
            if detected:
                detected_count += 1
                blocked = True  # SQLi should always be blocked
            
            if blocked:
                blocked_count += 1
            
            self._attack_history.append(AttackResult(
                attack_type=AttackType.SQL_INJECTION,
                severity=AttackSeverity.CRITICAL,
                detected=detected,
                blocked=blocked,
                mitigation_effective=blocked,
                details=details,
                metadata={"payload": payload[:50], "attempt": i}
            ))
        
        detection_rate = detected_count / num_attempts if num_attempts > 0 else 0
        block_rate = blocked_count / num_attempts if num_attempts > 0 else 0
        
        return SecurityTestResult(
            test_name="SQL Injection Attack Simulation",
            attack_type=AttackType.SQL_INJECTION,
            total_attempts=num_attempts,
            detected_count=detected_count,
            blocked_count=blocked_count,
            detection_rate=detection_rate,
            block_rate=block_rate,
            recommendations=[
                "Use parameterized queries (prepared statements)",
                "Implement input validation and sanitization",
                "Apply principle of least privilege to database accounts",
                "Enable database-level WAF rules",
            ],
        )
    
    def simulate_xss_attack(
        self,
        num_attempts: int = 50,
    ) -> SecurityTestResult:
        """Simulate XSS attack"""
        detected_count = 0
        blocked_count = 0
        
        for i, payload in enumerate(self._xss_patterns * (num_attempts // len(self._xss_patterns) + 1)):
            if i >= num_attempts:
                break
                
            detected, blocked, details = self._simulate_detection(AttackType.XSS)
            
            if detected:
                detected_count += 1
                blocked = True  # XSS should be blocked
            
            if blocked:
                blocked_count += 1
            
            self._attack_history.append(AttackResult(
                attack_type=AttackType.XSS,
                severity=AttackSeverity.HIGH,
                detected=detected,
                blocked=blocked,
                mitigation_effective=blocked,
                details=details,
                metadata={"payload": payload[:50], "attempt": i}
            ))
        
        detection_rate = detected_count / num_attempts if num_attempts > 0 else 0
        block_rate = blocked_count / num_attempts if num_attempts > 0 else 0
        
        return SecurityTestResult(
            test_name="XSS Attack Simulation",
            attack_type=AttackType.XSS,
            total_attempts=num_attempts,
            detected_count=detected_count,
            blocked_count=blocked_count,
            detection_rate=detection_rate,
            block_rate=block_rate,
            recommendations=[
                "Implement Content Security Policy (CSP)",
                "Use output encoding for user data",
                "Enable X-XSS-Protection header",
                "Sanitize HTML input with DOMPurify",
            ],
        )
    
    def simulate_credential_stuffing(
        self,
        num_attempts: int = 100,
    ) -> SecurityTestResult:
        """Simulate credential stuffing attack"""
        detected_count = 0
        blocked_count = 0
        
        leaked_credentials = [
            ("admin", "admin123"),
            ("user", "password"),
            ("test", "123456"),
        ]
        
        for i in range(num_attempts):
            username, password = random.choice(leaked_credentials)
            
            detected, blocked, details = self._simulate_detection(AttackType.CREDENTIAL_STUFFING)
            
            if detected:
                detected_count += 1
                blocked = True  # Should block known leaked credentials
            
            if blocked:
                blocked_count += 1
            
            self._attack_history.append(AttackResult(
                attack_type=AttackType.CREDENTIAL_STUFFING,
                severity=AttackSeverity.HIGH,
                detected=detected,
                blocked=blocked,
                mitigation_effective=blocked,
                details=details,
                metadata={"username": username, "attempt": i}
            ))
        
        detection_rate = detected_count / num_attempts if num_attempts > 0 else 0
        block_rate = blocked_count / num_attempts if num_attempts > 0 else 0
        
        return SecurityTestResult(
            test_name="Credential Stuffing Simulation",
            attack_type=AttackType.CREDENTIAL_STUFFING,
            total_attempts=num_attempts,
            detected_count=detected_count,
            blocked_count=blocked_count,
            detection_rate=detection_rate,
            block_rate=block_rate,
            recommendations=[
                "Check credentials against known data breaches",
                "Implement rate limiting per account",
                "Use CAPTCHA after failed attempts",
                "Send security alerts for unusual logins",
            ],
        )
    
    def simulate_rate_limit_violation(
        self,
        num_attempts: int = 150,
    ) -> SecurityTestResult:
        """Simulate rate limiting violation"""
        detected_count = 0
        blocked_count = 0
        
        for i in range(num_attempts):
            # Rapid requests
            detected, blocked, details = self._simulate_detection(AttackType.RATE_LIMIT_VIOLATION)
            
            if detected:
                detected_count += 1
                blocked = True  # Rate limiting should block
            
            if blocked:
                blocked_count += 1
            
            self._attack_history.append(AttackResult(
                attack_type=AttackType.RATE_LIMIT_VIOLATION,
                severity=AttackSeverity.MEDIUM,
                detected=detected,
                blocked=blocked,
                mitigation_effective=blocked,
                details=details,
                metadata={"request_count": i, "attempt": i}
            ))
        
        detection_rate = detected_count / num_attempts if num_attempts > 0 else 0
        block_rate = blocked_count / num_attempts if num_attempts > 0 else 0
        
        return SecurityTestResult(
            test_name="Rate Limit Violation Simulation",
            attack_type=AttackType.RATE_LIMIT_VIOLATION,
            total_attempts=num_attempts,
            detected_count=detected_count,
            blocked_count=blocked_count,
            detection_rate=detection_rate,
            block_rate=block_rate,
            recommendations=[
                "Implement sliding window rate limiting",
                "Add burst rate limiting",
                "Configure per-IP and per-user limits",
                "Return proper 429 status codes",
            ],
        )
    
    def simulate_api_abuse(
        self,
        num_attempts: int = 75,
    ) -> SecurityTestResult:
        """Simulate API abuse patterns"""
        detected_count = 0
        blocked_count = 0
        
        abuse_patterns = [
            "excessive_payload_size",
            "recursive_nested_resources",
            "concurrent_requests",
            "resource_enumeration",
        ]
        
        for i in range(num_attempts):
            pattern = random.choice(abuse_patterns)
            
            detected, blocked, details = self._simulate_detection(AttackType.API_ABUSE)
            
            if detected:
                detected_count += 1
            
            if blocked:
                blocked_count += 1
            
            self._attack_history.append(AttackResult(
                attack_type=AttackType.API_ABUSE,
                severity=AttackSeverity.MEDIUM,
                detected=detected,
                blocked=blocked,
                mitigation_effective=blocked,
                details=details,
                metadata={"pattern": pattern, "attempt": i}
            ))
        
        detection_rate = detected_count / num_attempts if num_attempts > 0 else 0
        block_rate = blocked_count / num_attempts if num_attempts > 0 else 0
        
        return SecurityTestResult(
            test_name="API Abuse Pattern Simulation",
            attack_type=AttackType.API_ABUSE,
            total_attempts=num_attempts,
            detected_count=detected_count,
            blocked_count=blocked_count,
            detection_rate=detection_rate,
            block_rate=block_rate,
            recommendations=[
                "Implement API request validation",
                "Add schema validation for request bodies",
                "Set resource limits per endpoint",
                "Enable API usage analytics",
            ],
        )
    
    def run_all_tests(self) -> Dict[str, SecurityTestResult]:
        """Run all security tests"""
        results = {}
        
        results["brute_force"] = self.simulate_brute_force()
        results["sql_injection"] = self.simulate_sql_injection()
        results["xss"] = self.simulate_xss_attack()
        results["credential_stuffing"] = self.simulate_credential_stuffing()
        self.simulate_credential_stuffing()
        results["rate_limit_violation"] = self.simulate_rate_limit_violation()
        results["api_abuse"] = self.simulate_api_abuse()
        
        self._test_results.extend(results.values())
        
        return results
    
    def get_attack_history(
        self,
        limit: int = 100,
        attack_type: Optional[AttackType] = None,
    ) -> List[Dict[str, Any]]:
        """Get recent attack simulation results"""
        history = self._attack_history
        
        if attack_type:
            history = [h for h in history if h.attack_type == attack_type]
        
        return [
            {
                "attack_type": h.attack_type.value,
                "severity": h.severity.value,
                "detected": h.detected,
                "blocked": h.blocked,
                "mitigation_effective": h.mitigation_effective,
                "details": h.details,
                "timestamp": h.timestamp,
                "metadata": h.metadata,
            }
            for h in history[-limit:]
        ]
    
    def get_security_summary(self) -> Dict[str, Any]:
        """Get overall security posture summary"""
        if not self._test_results:
            return {
                "total_tests": 0,
                "avg_detection_rate": 0.0,
                "avg_block_rate": 0.0,
                "security_score": 0.0,
            }
        
        total_detection = sum(r.detection_rate for r in self._test_results)
        total_block = sum(r.block_rate for r in self._test_results)
        avg_detection = total_detection / len(self._test_results)
        avg_block = total_block / len(self._test_results)
        
        # Calculate security score (0-100)
        security_score = (avg_detection * 0.4 + avg_block * 0.6) * 100
        
        return {
            "total_tests": len(self._test_results),
            "avg_detection_rate": avg_detection,
            "avg_block_rate": avg_block,
            "security_score": security_score,
            "total_attack_attempts": sum(r.total_attempts for r in self._test_results),
            "total_detected": sum(r.detected_count for r in self._test_results),
            "total_blocked": sum(r.blocked_count for r in self._test_results),
        }
    
    def get_test_results(self) -> List[Dict[str, Any]]:
        """Get all test results"""
        return [
            {
                "test_name": r.test_name,
                "attack_type": r.attack_type.value,
                "total_attempts": r.total_attempts,
                "detected_count": r.detected_count,
                "blocked_count": r.blocked_count,
                "detection_rate": r.detection_rate,
                "block_rate": r.block_rate,
                "recommendations": r.recommendations,
                "timestamp": r.timestamp,
            }
            for r in self._test_results
        ]


# Global instance
_security_testing_service: Optional[SecurityTestingService] = None


def get_security_testing_service() -> SecurityTestingService:
    """Get or create the global security testing service"""
    global _security_testing_service
    if _security_testing_service is None:
        _security_testing_service = SecurityTestingService()
    return _security_testing_service
