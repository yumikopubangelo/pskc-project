# ============================================================
# PSKC — Auth Middleware Module (REFACTORED FOR FIPS COMPLIANCE)
# ============================================================
#
# DOKUMEN INI ADALAH IMPLEMENTASI RENCANA AKSI DARI
# `plans/fips_nist_compliance_assessment.md`.
#
# PERUBAHAN UTAMA:
# 1. Penghapusan State Internal: Middleware tidak lagi menyimpan instance
#    logger (`self._audit`). Panggilan `get_audit_logger()` di `__init__`
#    telah dihapus.
# 2. Akses State dari Request: Logger sekarang diakses secara dinamis dari
#    `request.app.state.audit_logger` di dalam metode `dispatch` dan
#    metode-metode lain yang menanganinya. Ini adalah pola yang benar
#    untuk middleware FastAPI, memastikan ia menggunakan instance yang
#    dikelola oleh siklus hidup aplikasi.
# 3. Adaptasi Panggilan Log: Panggilan logging telah diubah agar sesuai
#    dengan metode `.log()` dari `TamperEvidentAuditLogger` yang baru.
#
# ============================================================

import time
import asyncio
from typing import Optional, Callable
from dataclasses import dataclass
from fastapi import Request, Response, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import logging

# Dependensi yang menggunakan singleton global (akan direfaktor di masa depan jika perlu)
from src.auth.key_fetcher import fetch_key_with_cache
from src.auth.key_verifier import get_key_verifier, VerificationContext
from src.security.access_control import get_acl, Permission

# get_audit_logger sudah tidak digunakan lagi
# from src.security.audit_logger import get_audit_logger

logger = logging.getLogger(__name__)


@dataclass
class AuthResult:
    """Authentication result"""
    success: bool
    service_id: str
    key_id: Optional[str] = None
    latency_ms: float = 0.0
    cache_hit: bool = False
    error: Optional[str] = None


class PSKCAuthMiddleware(BaseHTTPMiddleware):
    """
    PSKC Authentication Middleware for FastAPI/Starlette.
    """
    
    def __init__(
        self,
        app,
        exclude_paths: list = None,
    ):
        super().__init__(app)
        self._exclude_paths = exclude_paths or ["/health", "/metrics", "/docs", "/openapi.json", "/"]
        
        # Dependensi yang belum direfaktor bisa tetap di sini untuk sekarang
        self._verifier = get_key_verifier()
        self._acl = get_acl()
        
        # self._audit telah dihapus dari sini.
        
        logger.info("PSKCAuthMiddleware initialized (stateless logger).")
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request through authentication pipeline"""
        
        if self._should_skip_auth(request.url.path):
            return await call_next(request)

        # Dapatkan logger dari state aplikasi via request
        # Ini memastikan kita menggunakan logger yang benar-benar diinisialisasi
        # oleh lifespan manager.
        audit_logger = request.app.state.audit_logger
        
        service_id = self._extract_service_id(request)
        
        if not service_id:
            audit_logger.log(user="ANONYMOUS", action="AUTH_ATTEMPT", outcome="FAILURE_NO_SERVICE_ID",
                             metadata={"path": request.url.path, "ip": request.client.host})
            return JSONResponse(status_code=401, content={"error": "Service identity not provided"})

        ip_address = request.client.host if request.client else "unknown"

        if not self._acl.check_permission(service_id, Permission.KEY_READ, ip_address=ip_address):
            audit_logger.log(user=service_id, action="AUTH_ATTEMPT", outcome="FAILURE_ACL_DENIED",
                             metadata={"path": request.url.path, "ip": ip_address})
            return JSONResponse(status_code=403, content={"error": "Access denied"})
        
        key_id = self._extract_key_id(request)
        
        if key_id:
            result = await self._authenticate_key(request, service_id, key_id)
            request.state.auth_result = result
            if not result.success:
                # Logging sudah dilakukan di dalam _authenticate_key
                return JSONResponse(status_code=401, content={"error": result.error or "Authentication failed"})
        
        response = await call_next(request)
        
        return response
    
    def _should_skip_auth(self, path: str) -> bool:
        """Check if path should skip authentication"""
        for exclude in self._exclude_paths:
            if path.startswith(exclude):
                return True
        return False
    
    def _extract_service_id(self, request: Request) -> Optional[str]:
        return request.headers.get("X-Service-ID")

    def _extract_key_id(self, request: Request) -> Optional[str]:
        return request.query_params.get("key_id") or request.headers.get("X-Key-ID")

    async def _authenticate_key(
        self,
        request: Request,
        service_id: str,
        key_id: str
    ) -> AuthResult:
        """Authenticate using key from cache or KMS"""
        start_time = time.time()
        
        # Dapatkan dependensi dari state aplikasi
        secure_manager = request.app.state.secure_cache_manager
        audit_logger = request.app.state.audit_logger
        ip_address = request.client.host or "unknown"
        
        try:
            # Gunakan secure_manager yang sudah terintegrasi dengan IDS
            key_data, cache_hit, latency, security_ok = secure_manager.secure_get(
                key_id, service_id, ip_address
            )

            if not security_ok:
                # secure_get sudah melakukan logging-nya
                return AuthResult(success=False, service_id=service_id, key_id=key_id, error="Access blocked by IDS")

            if key_data is None: # Cache miss
                key_data = await fetch_key_with_cache(key_id, service_id)
                if key_data is None:
                    audit_logger.log(user=service_id, action="AUTH_KEY", outcome="FAILURE_KEY_NOT_FOUND", metadata={"key_id": key_id})
                    return AuthResult(success=False, service_id=service_id, key_id=key_id, error="Key not found")
                
                # Set kunci ke cache yang aman
                secure_manager.secure_set(key_id, key_data, service_id)
            
            # Verifikasi kunci (opsional, tergantung pada alur)
            context = VerificationContext(key_id=key_id, service_id=service_id, timestamp=time.time())
            verification = await self._verifier.verify(key_id, key_data, context)
            
            if verification.result.value != "valid":
                audit_logger.log(user=service_id, action="AUTH_KEY", outcome="FAILURE_VERIFICATION_FAILED", metadata={"key_id": key_id})
                return AuthResult(success=False, service_id=service_id, key_id=key_id, error="Key verification failed")

            latency_total = (time.time() - start_time) * 1000
            audit_logger.log(user=service_id, action="AUTH_KEY", outcome="SUCCESS",
                             metadata={"key_id": key_id, "cache_hit": cache_hit, "latency_ms": latency_total})

            return AuthResult(
                success=True, service_id=service_id, key_id=key_id,
                latency_ms=latency_total, cache_hit=cache_hit
            )
            
        except Exception as e:
            logger.error(f"Authentication error for service '{service_id}': {e}")
            audit_logger.log(user=service_id, action="AUTH_KEY", outcome="FAILURE_EXCEPTION",
                             metadata={"key_id": key_id, "error": str(e)})
            return AuthResult(success=False, service_id=service_id, key_id=key_id, error=str(e))
