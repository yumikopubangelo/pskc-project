# ============================================================
# PSKC — Security Headers Middleware (FILE BARU)
# ============================================================
#
# File ini TIDAK ADA sebelumnya — ini adalah lapisan keamanan
# HTTP yang sangat penting tapi sering dilupakan.
#
# Apa yang dilindungi:
#   - HSTS: mencegah downgrade ke HTTP di browser
#   - CSP: mencegah XSS di frontend dashboard
#   - X-Frame-Options: mencegah clickjacking
#   - X-Content-Type-Options: mencegah MIME sniffing
#   - Referrer-Policy: mencegah kebocoran URL sensitif di referrer header
#   - Permissions-Policy: disable fitur browser yang tidak dipakai
#   - Request ID: setiap request dapat unique ID untuk tracing
#   - Request size limiting: mencegah request body yang terlalu besar
#   - Path traversal detection: blokir ../ dan %2e%2e di URL
#   - Sensitive path protection: /admin, /internal hanya dari private IP
# ============================================================

import ipaddress
import logging
import time
import uuid
from typing import Callable, Optional, Set

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

logger = logging.getLogger(__name__)


# ============================================================
# Network Configuration for Security
# ============================================================

# Private IP ranges for internal endpoint protection
PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]

# CRITICAL: Configure this list with the IP addresses of your trusted reverse proxies.
# If this list is empty, X-Forwarded-For headers will NOT be trusted.
TRUSTED_PROXIES: Set[ipaddress.IPv4Network | ipaddress.IPv6Network] = set()


def configure_trusted_proxies(proxy_networks: Optional[list[str] | str]) -> list[str]:
    """
    Configure the trusted proxy CIDR set from settings.

    Returns any invalid entries so the caller can log them.
    """
    TRUSTED_PROXIES.clear()

    if not proxy_networks:
        return []

    if isinstance(proxy_networks, str):
        candidates = [entry.strip() for entry in proxy_networks.split(",") if entry.strip()]
    else:
        candidates = [entry.strip() for entry in proxy_networks if entry and entry.strip()]

    invalid_entries: list[str] = []
    for entry in candidates:
        try:
            TRUSTED_PROXIES.add(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            invalid_entries.append(entry)

    return invalid_entries


def _is_private_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
        return any(ip in net for net in PRIVATE_NETWORKS)
    except ValueError:
        return False


# ============================================================
# Path Traversal Detector
# ============================================================

# Pola yang mengindikasikan path traversal attempt
TRAVERSAL_PATTERNS = (
    "../", "..\\", "%2e%2e", "%2e.", ".%2e",
    "%252e%252e",  # Double-encoded
    "....//",      # Filter bypass variant
)

SENSITIVE_PATH_PREFIXES = (
    "/admin",
    "/internal",
    "/debug",
    "/metrics",    # Prometheus metrics — internal only
    "/_internal",
    "/security/audit",  # Security audit logs - internal only
    "/security/intrusions",  # Intrusion detection - internal only
)


def _has_path_traversal(path: str) -> bool:
    path_lower = path.lower()
    return any(p in path_lower for p in TRAVERSAL_PATTERNS)


def _is_sensitive_path(path: str) -> bool:
    return any(path.startswith(p) for p in SENSITIVE_PATH_PREFIXES)


# ============================================================
# Security Headers Middleware
# ============================================================

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware yang menambahkan HTTP security headers ke setiap response
    dan memvalidasi setiap incoming request untuk pola berbahaya.

    Cara pasang di FastAPI (di src/api/routes.py atau main.py):

        from src.security.security_headers import SecurityHeadersMiddleware
        app.add_middleware(SecurityHeadersMiddleware)
    """

    def __init__(
        self,
        app,
        hsts_max_age: int = 31_536_000,          # 1 tahun
        csp_policy: Optional[str] = None,
        max_request_body_bytes: int = 10 * 1024 * 1024,  # 10 MB
        allowed_methods: Set[str] = None,
        block_sensitive_from_external: bool = True,
    ):
        super().__init__(app)
        self.hsts_max_age = hsts_max_age
        self.max_request_body_bytes = max_request_body_bytes
        self.block_sensitive_from_external = block_sensitive_from_external
        self.allowed_methods = allowed_methods or {
            "GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"
        }

        # Content Security Policy default — ketat untuk API server
        self.csp_policy = csp_policy or (
            "default-src 'none'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self';"
        )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = str(uuid.uuid4())
        start_time = time.time()

        # ── 1. Method validation ────────────────────────────────
        if request.method not in self.allowed_methods:
            logger.warning(
                f"[{request_id}] Blocked disallowed method: {request.method} {request.url.path}"
            )
            return JSONResponse(
                status_code=405,
                content={"error": "Method not allowed"},
            )

        # ── 2. Path traversal detection ─────────────────────────
        if _has_path_traversal(str(request.url.path)):
            client_ip = self._get_client_ip(request)
            logger.warning(
                f"[{request_id}] Path traversal attempt blocked: "
                f"{request.url.path} from {client_ip}"
            )
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid request path"},
            )

        # ── 3. Sensitive path protection ────────────────────────
        if self.block_sensitive_from_external and _is_sensitive_path(request.url.path):
            client_ip = self._get_client_ip(request)
            if client_ip and not _is_private_ip(client_ip):
                logger.warning(
                    f"[{request_id}] External access to sensitive path blocked: "
                    f"{request.url.path} from {client_ip}"
                )
                return JSONResponse(
                    status_code=403,
                    content={"error": "Access denied"},
                )

        # ── 4. Request size check ────────────────────────────────
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                size = int(content_length)
                if size > self.max_request_body_bytes:
                    logger.warning(
                        f"[{request_id}] Request body too large: {size} bytes "
                        f"(max {self.max_request_body_bytes})"
                    )
                    return JSONResponse(
                        status_code=413,
                        content={"error": "Request body too large"},
                    )
            except ValueError:
                pass

        # ── 5. Host header validation ────────────────────────────
        host = request.headers.get("host", "")
        if self._is_suspicious_host(host):
            logger.warning(f"[{request_id}] Suspicious Host header: {host!r}")
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid Host header"},
            )

        # ── 6. Attach request ID ke state ────────────────────────
        request.state.request_id = request_id

        # ── 7. Process request ───────────────────────────────────
        try:
            response = await call_next(request)
        except Exception as e:
            logger.error(f"[{request_id}] Unhandled error: {e}", exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"error": "Internal server error"},
            )

        # ── 8. Inject security headers ke response ───────────────
        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        self._inject_security_headers(response, request_id, elapsed_ms)

        return response

    # ----------------------------------------------------------
    # Security Headers Injection
    # ----------------------------------------------------------

    def _inject_security_headers(
        self,
        response: Response,
        request_id: str,
        elapsed_ms: float,
    ) -> None:
        h = response.headers

        # Strict Transport Security — force HTTPS, 1 tahun
        h["Strict-Transport-Security"] = (
            f"max-age={self.hsts_max_age}; includeSubDomains; preload"
        )

        # Prevents XSS via script injection
        h["Content-Security-Policy"] = self.csp_policy

        # Prevent MIME type sniffing
        h["X-Content-Type-Options"] = "nosniff"

        # Prevent clickjacking
        h["X-Frame-Options"] = "DENY"

        # Minimal referrer info
        h["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Disable dangerous browser features
        h["Permissions-Policy"] = (
            "geolocation=(), camera=(), microphone=(), "
            "payment=(), usb=(), bluetooth=(), "
            "interest-cohort=()"
        )

        # Remove server fingerprint
        h["Server"] = "PSKC"
        if "X-Powered-By" in h:
            del h["X-Powered-By"]

        # Tracing headers
        h["X-Request-ID"] = request_id
        h["X-Response-Time"] = f"{elapsed_ms}ms"

        # Cache control untuk API responses — jangan cache key material
        if "Cache-Control" not in h:
            h["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
        h["Pragma"] = "no-cache"

        # Cross-Origin policies
        h["Cross-Origin-Embedder-Policy"] = "require-corp"
        h["Cross-Origin-Opener-Policy"] = "same-origin"
        h["Cross-Origin-Resource-Policy"] = "same-origin"

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------

    def _get_client_ip(self, request: Request) -> Optional[str]:
        """
        Extract the client IP address, handling reverse proxies safely.
        Vulnerability fix for CWE-290: Authentication Bypass by Spoofing.
        Trusts X-Forwarded-For only if the request comes from a trusted proxy.
        """
        # Direct connection IP
        client_host = request.client.host if request.client else None
        if not client_host:
            return None

        # Check if the connection is from a trusted proxy
        try:
            is_trusted = any(ipaddress.ip_address(client_host) in net for net in TRUSTED_PROXIES)
        except ValueError:
            is_trusted = False

        forwarded_for = request.headers.get("X-Forwarded-For")
        if is_trusted and forwarded_for:
            # If from a trusted proxy, the client IP is the first in the list.
            return forwarded_for.split(",")[0].strip()

        # If not from a trusted proxy, or no XFF header, use the direct connection IP.
        # This also safely handles a spoofed XFF from an untrusted source.
        return client_host

    def _is_suspicious_host(self, host: str) -> bool:
        """
        Deteksi Host header injection.
        Attacker kadang set Host: evil.com untuk poison cache atau logs.
        """
        if not host:
            return False
        # Strip port
        hostname = host.split(":")[0]
        # Karakter yang tidak boleh ada di hostname
        suspicious_chars = ["<", ">", "'", '"', ";", "(", ")", "{", "}", "\\", "\n", "\r"]
        return any(c in hostname for c in suspicious_chars)


# ============================================================
# Rate Limiter Middleware (sliding window per IP)
# ============================================================

import threading
from collections import defaultdict, deque


class SlidingWindowRateLimiter(BaseHTTPMiddleware):
    """
    Per-IP sliding window rate limiter.

    SEBELUMNYA: Rate limiting ada di IDS tapi tidak di middleware level —
    request yang melebihi rate masih diproses sampai handler sebelum diblokir.
    SEKARANG: Blokir di middleware, sebelum request diproses sama sekali.

    Cara pasang (sebelum SecurityHeadersMiddleware):
        app.add_middleware(SlidingWindowRateLimiter, max_requests=100, window_seconds=60)
        app.add_middleware(SecurityHeadersMiddleware)
    """

    def __init__(
        self,
        app,
        max_requests: int = 100,        # Max request per window per IP
        window_seconds: int = 60,
        burst_max: int = 20,            # Max burst dalam 5 detik
        burst_window: int = 5,
        whitelist_private_ips: bool = True,
        exempt_paths: Set[str] = None,
    ):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.burst_max = burst_max
        self.burst_window = burst_window
        self.whitelist_private_ips = whitelist_private_ips
        self.exempt_paths = exempt_paths or {"/health", "/metrics"}

        # ip → deque of timestamps
        self._windows: dict = defaultdict(lambda: deque())
        self._burst_windows: dict = defaultdict(lambda: deque())
        self._lock = threading.Lock()

        # Cleanup thread (tiap 5 menit)
        self._cleanup_thread = threading.Thread(
            target=self._periodic_cleanup, daemon=True
        )
        self._cleanup_thread.start()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip exempt paths
        if request.url.path in self.exempt_paths:
            return await call_next(request)

        client_ip = self._get_ip(request)
        if client_ip == "unknown":
            # Cannot determine IP, proceed without rate limiting
            return await call_next(request)


        # Skip private IPs (inter-service traffic)
        if self.whitelist_private_ips and _is_private_ip(client_ip):
            return await call_next(request)

        now = time.time()

        with self._lock:
            # Sliding window check
            window = self._windows[client_ip]
            cutoff = now - self.window_seconds
            while window and window[0] < cutoff:
                window.popleft()

            if len(window) >= self.max_requests:
                logger.warning(
                    f"Rate limit exceeded for IP {client_ip}: "
                    f"{len(window)} requests in {self.window_seconds}s"
                )
                retry_after = int(self.window_seconds - (now - window[0])) + 1
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "Too many requests",
                        "retry_after_seconds": retry_after,
                    },
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(self.max_requests),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(int(now + retry_after)),
                    },
                )

            # Burst check (lebih ketat, window pendek)
            burst = self._burst_windows[client_ip]
            burst_cutoff = now - self.burst_window
            while burst and burst[0] < burst_cutoff:
                burst.popleft()

            if len(burst) >= self.burst_max:
                logger.warning(
                    f"Burst rate limit exceeded for IP {client_ip}: "
                    f"{len(burst)} requests in {self.burst_window}s"
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "Request rate too high (burst limit)",
                        "retry_after_seconds": self.burst_window,
                    },
                    headers={"Retry-After": str(self.burst_window)},
                )

            window.append(now)
            burst.append(now)
            remaining = self.max_requests - len(window)

        response = await call_next(request)

        # Inject rate limit headers ke response
        response.headers["X-RateLimit-Limit"] = str(self.max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(now + self.window_seconds))

        return response

    def _get_ip(self, request: Request) -> str:
        """
        Extract the client IP address securely for rate limiting.
        """
        # Direct connection IP
        client_host = request.client.host if request.client else "unknown"
        if client_host == "unknown":
            return "unknown"

        # Check if the connection is from a trusted proxy
        try:
            is_trusted = any(ipaddress.ip_address(client_host) in net for net in TRUSTED_PROXIES)
        except ValueError:
            is_trusted = False

        forwarded_for = request.headers.get("X-Forwarded-For")
        if is_trusted and forwarded_for:
            return forwarded_for.split(",")[0].strip()

        return client_host

    def _periodic_cleanup(self) -> None:
        """Remove stale IP entries tiap 5 menit."""
        while True:
            time.sleep(300)
            now = time.time()
            with self._lock:
                stale_ips = [
                    ip for ip, window in self._windows.items()
                    if not window or now - window[-1] > self.window_seconds * 2
                ]
                for ip in stale_ips:
                    del self._windows[ip]
                    self._burst_windows.pop(ip, None)
            if stale_ips:
                logger.debug(f"Rate limiter: cleaned {len(stale_ips)} stale IP entries")
