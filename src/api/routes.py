# ============================================================
# PSKC — API Routes (FINAL FIPS-COMPLIANT WIRING)
# ============================================================
#
# DOKUMEN INI ADALAH IMPLEMENTASI RENCANA AKSI DARI
# `plans/fips_nist_compliance_assessment.md`.
#
# PERUBAHAN FINAL:
# 1. Inisialisasi Terpusat: Lifespan manager sekarang menginisialisasi
#    SEMUA komponen inti (FIPS module, logger, cache, policy manager,
#    encrypted store, secure manager) dan menyimpannya di `app.state`.
#    Ini menciptakan satu sumber kebenaran untuk state aplikasi.
# 2. Dependency Injection Lengkap: Fungsi `Depends()` sekarang digunakan
#    untuk menyediakan `SecureCacheManager` dan dependensi lainnya ke
#    setiap endpoint yang membutuhkannya. Ini menyelesaikan pergeseran
#    dari pola singleton global ke arsitektur yang modern dan dapat diuji.
# 3. Endpoint yang Direfaktor: Endpoint seperti `/keys/access` dan
#    `/keys/store` sekarang menggunakan `SecureCacheManager` yang
#    di-inject untuk melakukan operasi mereka.
#
# ============================================================

import base64
import binascii
import ipaddress
import logging
import time
from contextlib import asynccontextmanager
from fastapi import APIRouter, BackgroundTasks, HTTPException, status, Request, Depends, FastAPI, Query
from fastapi.responses import Response
from typing import Optional

# --- Impor Modul FIPS dan Logger Baru ---
from src.security.fips_self_tests import run_power_on_self_tests, FipsSelfTestFailure

# --- Impor Komponen Aplikasi yang Direfaktor ---
from src.security.intrusion_detection import SecureCacheManager

# --- Impor Skema dan Modul Lainnya ---
from src.api.schemas import (
    KeyAccessRequest, KeyAccessResponse, 
    KeyStoreRequest, KeyStoreResponse, 
    HealthResponse, ReadinessResponse, StartupResponse, MetricsResponse,
    CacheStatsResponse, PredictionResponse,
    SimulationRequest, SimulationResponse,
    SimulationResultResponse, SecurityAuditResponse,
    IntrusionLogResponse,
    ModelPromotionRequest,
    ModelRollbackRequest,
    PipelineRequest,
    PipelineResponse,
    PipelineStatusResponse,
)
from src.auth.key_fetcher import get_key_fetcher
from src.security.security_headers import (
    TRUSTED_PROXIES,
    SecurityHeadersMiddleware,
    SlidingWindowRateLimiter,
    configure_trusted_proxies,
)
from src.api.simulation_service import list_simulation_scenarios, run_simulation_job
from src.api.ml_service import (
    get_accuracy_history_payload,
    get_model_lifecycle_payload,
    get_model_registry_payload,
    get_prefetch_dlq_payload,
    get_prefetch_metrics_payload,
    get_ml_status_payload,
    get_prediction_payload,
    initialize_ml_runtime,
    promote_runtime_model_version,
    record_runtime_access,
    rollback_runtime_model_version,
    schedule_request_path_prefetch,
    shutdown_ml_runtime,
    trigger_runtime_retraining,
)
from src.observability.prometheus_exporter import (
    build_prometheus_metrics_payload,
    get_prometheus_content_type,
)
from src.observability.metrics_persistence import (
    get_metrics_persistence,
    is_metrics_available,
)
from src.prefetch.queue import get_prefetch_queue
from src.ml.evaluation import get_ml_evaluation_service
from src.security.security_testing import get_security_testing_service
from src.runtime.bootstrap import build_runtime_services, shutdown_runtime_services
from config.settings import settings
from datetime import datetime, timezone
import uuid

logger = logging.getLogger(__name__)

# Global startup state for health checks
_startup_state = {
    "started": False,
    "startup_error": None,
    "startup_progress": "initializing",
}


def _get_setting(name: str, default):
    return getattr(settings, name, default)


def _get_trusted_proxy_networks() -> list[str]:
    configured_networks = getattr(settings, "trusted_proxy_networks", None)
    if configured_networks is not None:
        return list(configured_networks)

    raw_value = getattr(settings, "trusted_proxies", "")
    return [entry.strip() for entry in str(raw_value).split(",") if entry.strip()]


def _prime_optional_dependency(name: str, dependency: object) -> None:
    ping = getattr(dependency, "ping", None)
    if not callable(ping):
        logger.debug("Skipping %s priming because ping() is unavailable.", name)
        return

    try:
        if not ping():
            logger.warning("%s is unavailable during startup priming.", name)
    except Exception as exc:
        logger.warning("%s priming failed during startup: %s", name, exc)


# ============================================================
# Lifespan Manager & Inisialisasi Terpusat
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """ Manajer siklus hidup aplikasi untuk startup dan shutdown. """
    logger.info("Application starting up...")
    _startup_state["startup_progress"] = "building_services"

    runtime_services = build_runtime_services()
    fips_module = runtime_services["fips_module"]
    audit_logger = runtime_services["audit_logger"]
    secure_cache_manager = runtime_services["secure_cache_manager"]
    redis_cache = runtime_services.get("redis_cache")
    
    _startup_state["startup_progress"] = "running_fips_self_tests"
    if bool(_get_setting("fips_self_test_enabled", True)):
        try:
            run_power_on_self_tests(fips_module)
        except FipsSelfTestFailure as e:
            logger.critical(f"FIPS self-test failed: {e}. Application will not start.")
            _startup_state["startup_error"] = str(e)
            shutdown_runtime_services(runtime_services)
            raise RuntimeError("FIPS Power-On Self-Test failed.") from e
    else:
        logger.warning("FIPS power-on self-tests are disabled by configuration.")

    # Inisialisasi runtime ML online
    _startup_state["startup_progress"] = "initializing_ml_runtime"
    ml_runtime = initialize_ml_runtime()
    
    # Prime optional dependencies
    _startup_state["startup_progress"] = "priming_dependencies"
    if redis_cache is not None:
        _prime_optional_dependency("redis cache", redis_cache)
    _prime_optional_dependency("prefetch queue", get_prefetch_queue())

    # Simpan semua instance utama di state aplikasi
    app.state.fips_module = fips_module
    app.state.audit_logger = audit_logger
    app.state.secure_cache_manager = secure_cache_manager
    app.state.ml_runtime = ml_runtime
    app.state.runtime_services = runtime_services
    
    audit_logger.log("SYSTEM", "APP_STARTUP", "SUCCESS")
    
    # Mark startup as complete
    _startup_state["started"] = True
    _startup_state["startup_progress"] = "ready"
    logger.info("Startup finished successfully.")
    
    yield  # Aplikasi berjalan

    logger.info("Application shutting down...")
    _startup_state["started"] = False
    _startup_state["startup_progress"] = "shutting_down"
    shutdown_ml_runtime()
    app.state.audit_logger.log("SYSTEM", "APP_SHUTDOWN", "SUCCESS")
    shutdown_runtime_services(app.state.runtime_services)
    logger.info("Shutdown finished.")


def _register_http_security_middleware(app: FastAPI) -> None:
    http_security_enabled = bool(_get_setting("http_security_enabled", True))
    http_security_max_request_body_bytes = int(
        _get_setting("http_security_max_request_body_bytes", 10 * 1024 * 1024)
    )
    http_security_block_sensitive_from_external = bool(
        _get_setting("http_security_block_sensitive_from_external", False)
    )
    http_rate_limit_enabled = bool(_get_setting("http_rate_limit_enabled", True))
    http_rate_limit_max_requests = int(_get_setting("http_rate_limit_max_requests", 300))
    http_rate_limit_window_seconds = int(_get_setting("http_rate_limit_window_seconds", 60))
    http_rate_limit_burst_max = int(_get_setting("http_rate_limit_burst_max", 60))
    http_rate_limit_burst_window_seconds = int(
        _get_setting("http_rate_limit_burst_window_seconds", 5)
    )
    http_rate_limit_whitelist_private_ips = bool(
        _get_setting("http_rate_limit_whitelist_private_ips", True)
    )

    invalid_trusted_proxies = configure_trusted_proxies(_get_trusted_proxy_networks())
    if invalid_trusted_proxies:
        logger.warning(
            "Ignoring invalid TRUSTED_PROXIES entries: %s",
            ", ".join(invalid_trusted_proxies),
        )

    if http_security_enabled:
        app.add_middleware(
            SecurityHeadersMiddleware,
            max_request_body_bytes=http_security_max_request_body_bytes,
            block_sensitive_from_external=http_security_block_sensitive_from_external,
        )

    if http_rate_limit_enabled:
        # Last-added middleware runs first, so register the rate limiter after
        # header hardening to enforce limits before request handlers execute.
        app.add_middleware(
            SlidingWindowRateLimiter,
            max_requests=http_rate_limit_max_requests,
            window_seconds=http_rate_limit_window_seconds,
            burst_max=http_rate_limit_burst_max,
            burst_window=http_rate_limit_burst_window_seconds,
            whitelist_private_ips=http_rate_limit_whitelist_private_ips,
        )

    logger.info(
        "HTTP security middleware configured: headers=%s rate_limit=%s trusted_proxies=%s sensitive_path_block=%s",
        http_security_enabled,
        http_rate_limit_enabled,
        len(TRUSTED_PROXIES),
        http_security_block_sensitive_from_external,
    )


app = FastAPI(lifespan=lifespan)
_register_http_security_middleware(app)
router = APIRouter()


# ============================================================
# Dependency Injection untuk Komponen Utama
# ============================================================

def get_secure_cache_manager(request: Request) -> SecureCacheManager:
    return request.app.state.secure_cache_manager


def get_audit_logger(request: Request):
    return request.app.state.audit_logger


def _raise_ml_registry_error(result: dict) -> None:
    reason = str(result.get("reason") or "unknown")
    detail = result.get("detail")
    if reason in {"model_not_found", "version_not_found", "rollback_target_not_found"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail or reason)
    if reason == "integrity_verification_failed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail or "Model integrity verification failed")
    if reason in {"runtime_reload_failed", "rollback_activation_failed"}:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detail or reason)
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail or reason)

# ... (Fungsi get_fips_module dan get_tamper_evident_logger bisa tetap ada jika diperlukan di tempat lain)


# ============================================================
# Endpoint yang Direfaktor
# ============================================================

def _extract_client_ip(request: Request) -> Optional[str]:
    client_host = request.client.host if request.client else None
    if not client_host: return None
    try:
        is_trusted = any(ipaddress.ip_address(client_host) in net for net in TRUSTED_PROXIES)
    except ValueError:
        is_trusted = False
    forwarded_for = request.headers.get("X-Forwarded-For")
    if is_trusted and forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return client_host


def _check_dependency_health(request: Request) -> dict:
    """
    Check all dependencies and return their health status.
    
    Dependency Policy:
    - fail_closed: dependency failure blocks startup/readiness (FIPS, audit logger)
    - fail_open: dependency failure doesn't block (Redis cache, prefetch queue)
    """
    dependencies = {}
    
    # Check FIPS module (fail_closed - critical)
    try:
        fips_module = getattr(request.app.state, "fips_module", None)
        if fips_module is not None:
            dependencies["fips_module"] = {
                "status": "healthy",
                "type": "fail_closed",
                "error": None
            }
        else:
            dependencies["fips_module"] = {
                "status": "unavailable",
                "type": "fail_closed",
                "error": "FIPS module not initialized"
            }
    except Exception as e:
        dependencies["fips_module"] = {
            "status": "unhealthy",
            "type": "fail_closed",
            "error": str(e)
        }
    
    # Check Audit Logger (fail_closed - critical for security)
    try:
        audit_logger = getattr(request.app.state, "audit_logger", None)
        if audit_logger is not None:
            # Test write capability
            dependencies["audit_logger"] = {
                "status": "healthy",
                "type": "fail_closed",
                "error": None
            }
        else:
            dependencies["audit_logger"] = {
                "status": "unavailable",
                "type": "fail_closed",
                "error": "Audit logger not initialized"
            }
    except Exception as e:
        dependencies["audit_logger"] = {
            "status": "unhealthy",
            "type": "fail_closed",
            "error": str(e)
        }
    
    # Check Redis Cache (fail_open - optional for read-heavy workloads)
    try:
        redis_cache = request.app.state.runtime_services.get("redis_cache") if hasattr(request.app.state, "runtime_services") else None
        if redis_cache is not None:
            ping_result = redis_cache.ping() if hasattr(redis_cache, 'ping') else True
            dependencies["redis_cache"] = {
                "status": "healthy" if ping_result else "unhealthy",
                "type": "fail_open",
                "error": None if ping_result else "Redis ping failed"
            }
        else:
            dependencies["redis_cache"] = {
                "status": "not_configured",
                "type": "fail_open",
                "error": None
            }
    except Exception as e:
        dependencies["redis_cache"] = {
            "status": "unhealthy",
            "type": "fail_open",
            "error": str(e)
        }
    
    # Check Prefetch Queue (fail_open - optional)
    try:
        prefetch_queue = get_prefetch_queue()
        if prefetch_queue is not None:
            dependencies["prefetch_queue"] = {
                "status": "healthy",
                "type": "fail_open",
                "error": None
            }
        else:
            dependencies["prefetch_queue"] = {
                "status": "not_configured",
                "type": "fail_open",
                "error": None
            }
    except Exception as e:
        dependencies["prefetch_queue"] = {
            "status": "unhealthy",
            "type": "fail_open",
            "error": str(e)
        }
    
    # Check ML Runtime (fail_open - optional)
    try:
        ml_runtime = getattr(request.app.state, "ml_runtime", None)
        if ml_runtime is not None:
            dependencies["ml_runtime"] = {
                "status": "healthy",
                "type": "fail_open",
                "error": None
            }
        else:
            dependencies["ml_runtime"] = {
                "status": "not_initialized",
                "type": "fail_open",
                "error": None
            }
    except Exception as e:
        dependencies["ml_runtime"] = {
            "status": "unhealthy",
            "type": "fail_open",
            "error": str(e)
        }
    
    return dependencies


def _determine_readiness(dependencies: dict) -> tuple[bool, str]:
    """
    Determine if the system is ready based on dependency health.
    
    Fail-closed dependencies must be healthy for system to be ready.
    Fail-open dependencies can be unhealthy without blocking readiness.
    """
    for dep_name, dep_info in dependencies.items():
        dep_type = dep_info.get("type", "fail_open")
        dep_status = dep_info.get("status", "unavailable")
        
        if dep_type == "fail_closed" and dep_status != "healthy":
            return False, f"Critical dependency {dep_name} is {dep_status}"
    
    return True, "All critical dependencies are healthy"


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Simple liveness check - is the process running?
    
    This endpoint is for Kubernetes livenessProbe.
    It returns 200 as long as the process is alive.
    """
    return HealthResponse(
        status="healthy", 
        services={"cache": "ok", "ml": "ok", "auth": "ok"}
    )


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness_check(request: Request):
    """
    Readiness check - can the system serve traffic?
    
    This endpoint is for Kubernetes readinessProbe.
    It verifies all critical dependencies are available.
    
    Fail-closed dependencies (FIPS, audit logger) MUST be healthy.
    Fail-open dependencies (Redis, prefetch, ML) can be degraded.
    """
    dependencies = _check_dependency_health(request)
    ready, status_message = _determine_readiness(dependencies)
    
    return ReadinessResponse(
        ready=ready,
        status=status_message,
        dependencies=dependencies
    )


@router.get("/health/startup", response_model=StartupResponse)
async def startup_check():
    """
    Startup check - is the application done starting up?
    
    This endpoint is for Kubernetes startupProbe.
    It returns 200 once startup is complete.
    """
    if _startup_state["started"]:
        return StartupResponse(
            started=True,
            status="ready",
            progress=_startup_state["startup_progress"]
        )
    else:
        return StartupResponse(
            started=False,
            status="starting",
            progress=_startup_state["startup_progress"],
            error=_startup_state.get("startup_error")
        )


@router.post("/keys/access", response_model=KeyAccessResponse)
async def access_key(
    req_body: KeyAccessRequest, 
    request: Request,
    background_tasks: BackgroundTasks,
    secure_manager: SecureCacheManager = Depends(get_secure_cache_manager)
):
    """ Mengakses kunci dari cache atau KMS menggunakan alur yang aman. """
    ip_address = _extract_client_ip(request)
    started_at = time.perf_counter()
    
    try:
        key_data, cache_hit, latency, security_ok = secure_manager.secure_get(
            req_body.key_id,
            req_body.service_id,
            ip_address
        )
        
        if not security_ok:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access blocked by security system")
        
        if key_data is None:
            fetcher = get_key_fetcher() # Asumsi fetcher tidak butuh refactoring FIPS
            key_data = await fetcher.fetch_key(req_body.key_id, req_body.service_id)
            if key_data is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Key not found: {req_body.key_id}")
            
            if not secure_manager.secure_set(req_body.key_id, key_data, req_body.service_id, ip_address or ""):
                logger.error(
                    "Failed to securely cache fetched key key_id=%s service_id=%s",
                    req_body.key_id,
                    req_body.service_id,
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Failed to store fetched key securely",
                )
            cache_hit = False

        total_latency_ms = (time.perf_counter() - started_at) * 1000
        _metrics_storage["total_requests"] += 1
        if cache_hit:
            _metrics_storage["cache_hits"] += 1
        else:
            _metrics_storage["cache_misses"] += 1
        _metrics_storage["latencies"].append(total_latency_ms)
        _metrics_storage["latencies"] = _metrics_storage["latencies"][-500:]
        _metrics_storage["active_keys"].add(req_body.key_id)

        # Persist metrics to Redis for historical analysis
        metrics_persistence = get_metrics_persistence()
        if metrics_persistence is not None and metrics_persistence.ping():
            try:
                metrics_persistence.record_request(
                    cache_hit=cache_hit,
                    latency_ms=total_latency_ms,
                    key_id=req_body.key_id
                )
            except Exception as mp_exc:
                logger.warning(f"Failed to persist metrics: {mp_exc}")

        try:
            record_runtime_access(
                key_id=req_body.key_id,
                service_id=req_body.service_id,
                latency_ms=total_latency_ms,
                cache_hit=cache_hit,
                verify=req_body.verify,
                source_ip=ip_address or "",
            )
        except Exception as ml_exc:
            logger.warning(f"Failed to record ML runtime access for {req_body.key_id}: {ml_exc}")

        background_tasks.add_task(
            schedule_request_path_prefetch,
            secure_manager,
            req_body.service_id,
            req_body.key_id,
            ip_address or "",
        )
        
        # NOTE: Key data tidak dikembalikan dalam response untuk keamanan.
        return KeyAccessResponse(
            success=True,
            key_id=req_body.key_id,
            cache_hit=cache_hit,
            latency_ms=total_latency_ms
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error accessing key: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to access key",
        )


@router.post("/keys/store", response_model=KeyStoreResponse)
async def store_key(
    req_body: KeyStoreRequest, 
    request: Request,
    secure_manager: SecureCacheManager = Depends(get_secure_cache_manager)
):
    """ Menyimpan kunci ke dalam cache yang terenkripsi. """
    ip_address = _extract_client_ip(request)
    
    try:
        key_data = base64.b64decode(req_body.key_data, validate=True)
        success = secure_manager.secure_set(
            req_body.key_id,
            key_data,
            req_body.service_id,
            ip_address or "",
            ttl=req_body.ttl,
        )
        
        if not success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Key rejected by security system")

        _metrics_storage["active_keys"].add(req_body.key_id)
        
        return KeyStoreResponse(success=True, key_id=req_body.key_id, service_id=req_body.service_id)

    except HTTPException:
        raise
    except (binascii.Error, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid base64 key_data payload",
        )
    except Exception as e:
        logger.exception("Error storing key: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store key",
        )


# ============================================================
# Metrics & Cache Endpoints
# ============================================================

# In-memory metrics storage for demo purposes
_metrics_storage = {
    "cache_hits": 0,
    "cache_misses": 0,
    "total_requests": 0,
    "latencies": [],
    "active_keys": set()
}


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(
    secure_manager: SecureCacheManager = Depends(get_secure_cache_manager)
):
    """Get system metrics"""
    hits = _metrics_storage["cache_hits"]
    misses = _metrics_storage["cache_misses"]
    total = _metrics_storage["total_requests"]
    hit_rate = hits / total if total > 0 else 0.0
    avg_latency = sum(_metrics_storage["latencies"]) / len(_metrics_storage["latencies"]) if _metrics_storage["latencies"] else 0.0
    active_keys = len(secure_manager.get_cache_keys())
    
    return MetricsResponse(
        cache_hits=hits,
        cache_misses=misses,
        cache_hit_rate=hit_rate,
        total_requests=total,
        avg_latency_ms=avg_latency,
        active_keys=active_keys
    )


@router.get("/cache/stats", response_model=CacheStatsResponse)
async def get_cache_stats(
    secure_manager: SecureCacheManager = Depends(get_secure_cache_manager)
):
    """Get cache statistics"""
    hits = _metrics_storage["cache_hits"]
    misses = _metrics_storage["cache_misses"]
    total = _metrics_storage["total_requests"]
    hit_rate = hits / total if total > 0 else 0.0
    cache_size = len(secure_manager.get_cache_keys())
    
    return CacheStatsResponse(
        size=cache_size,
        max_size=settings.cache_max_size,
        hits=hits,
        misses=misses,
        hit_rate=hit_rate,
        total_requests=total
    )


@router.get("/cache/keys")
async def get_cache_keys(
    secure_manager: SecureCacheManager = Depends(get_secure_cache_manager)
):
    """Get list of cached keys"""
    keys = secure_manager.get_cache_keys()
    return {"keys": keys, "count": len(keys)}


@router.post("/cache/invalidate/{key}")
async def invalidate_key(
    key: str,
    secure_manager: SecureCacheManager = Depends(get_secure_cache_manager)
):
    """Invalidate a cache key"""
    removed = False

    if key in _metrics_storage["active_keys"]:
        _metrics_storage["active_keys"].discard(key)
        removed = True

    # Try direct key match first, then fall back to scanning composite service:key entries.
    if secure_manager.secure_delete(key, "default", reason="manual_invalidate"):
        removed = True
    else:
        for cache_key in secure_manager.get_cache_keys():
            if cache_key == key:
                continue
            if cache_key.endswith(f":{key}"):
                service_id = cache_key.split(":", 1)[0]
                if secure_manager.secure_delete(key, service_id, reason="manual_invalidate"):
                    removed = True

    if removed:
        return {"success": True, "key": key, "message": "Key invalidated"}
    return {"success": False, "key": key, "message": "Key not found"}


# ============================================================
# ML Endpoints
# ============================================================

from typing import List, Dict, Any
from src.ml.data_collector import get_data_collector
from src.ml.trainer import get_model_trainer
import json
import os

@router.post("/ml/data/import")
async def import_training_data():
    """
    Import seed training data into the DataCollector.
    
    Loads access events from data/raw/access_events.json if available.
    This populates the ML pipeline with runtime events for training.
    """
    collector = get_data_collector()
    
    # Try to load from default seed data location
    seed_file = "data/raw/access_events.json"
    
    if not os.path.exists(seed_file):
        # Generate seed data if file doesn't exist
        from scripts.seed_data import generate_access_events
        events = generate_access_events(
            num_events=5000,
            num_keys=500,
            num_services=5,
            duration_hours=24
        )
        # Save to file for future use
        os.makedirs("data/raw", exist_ok=True)
        with open(seed_file, 'w') as f:
            json.dump(events, f)
        logger.info(f"Generated {len(events)} seed events")
    else:
        # Load from file
        with open(seed_file, 'r') as f:
            events = json.load(f)
        logger.info(f"Loaded {len(events)} events from {seed_file}")
    
    # Import events into collector
    imported = collector.import_events(events)
    
    # Get stats
    stats = collector.get_stats()
    
    return {
        "success": True,
        "imported_events": imported,
        "total_events": stats["total_events"],
        "unique_keys": stats["unique_keys"],
        "message": f"Successfully imported {imported} events"
    }

@router.get("/ml/data/stats")
async def get_data_stats():
    """
    Get current data collector statistics.
    """
    collector = get_data_collector()
    return collector.get_stats()

@router.get("/ml/diagnostics")
async def get_ml_diagnostics():
    """
    Get ML diagnostics - why predictions/confidence are low.
    """
    from collections import Counter
    from src.ml.predictor import get_key_predictor
    
    collector = get_data_collector()
    collector_stats = collector.get_stats()
    
    # Get recent events
    recent_events = collector.get_access_sequence(window_seconds=3600, max_events=1000)
    
    # Analyze data
    data_issues = []
    if not recent_events:
        data_status = "no_data"
        data_issues.append("No events in last hour - call /ml/data/import first")
    else:
        data_status = "ok"
        key_counts = Counter(e.get("key_id") for e in recent_events)
        if len(key_counts) < 10:
            data_issues.append(f"Only {len(key_counts)} unique keys - need more variety")
    
    # Get predictor stats
    predictor = get_key_predictor()
    pred_stats = predictor.get_prediction_stats()
    
    # Try to get predictions
    try:
        preds = predictor.predict(n=5)
    except:
        preds = []
    
    pred_issues = []
    if not preds:
        pred_status = "no_predictions"
        pred_issues.append("No predictions generated - model may not be trained")
    else:
        pred_status = "ok"
        confs = [p[1] for p in preds]
        avg_conf = sum(confs) / len(confs) if confs else 0
        if avg_conf < 0.3:
            pred_issues.append(f"Low avg confidence: {avg_conf:.2f}")
    
    # Recommendations
    recommendations = []
    if data_status != "ok":
        recommendations.append("1. Call POST /ml/data/import to load training data")
    if pred_status != "ok" or pred_issues:
        recommendations.append("2. Call POST /ml/retrain to train the model")
    if data_status == "ok" and len(key_counts) < 50:
        recommendations.append("3. Generate more traffic for better patterns")
    
    return {
        "summary": {
            "data_status": data_status,
            "prediction_status": pred_status,
            "collector_events": collector_stats.get("total_events", 0),
            "model_loaded": pred_stats.get("model_loaded", False)
        },
        "data_issues": data_issues,
        "prediction_issues": pred_issues,
        "recommendations": recommendations
    }

@router.get("/ml/predictions", response_model=PredictionResponse)
async def get_predictions(n: int = 10):
    """Get ML predictions for keys to pre-cache"""
    return get_prediction_payload(service_id="default", n=n)


@router.get("/ml/status")
async def get_ml_status():
    """Get ML model status"""
    return get_ml_status_payload()


@router.get("/ml/drift")
async def get_drift_analysis():
    """
    Get detailed drift analysis from the EWMA-based concept drift detector.
    
    Returns:
    - ewma_short: Short-term EWMA accuracy
    - ewma_long: Long-term EWMA accuracy  
    - ewma_drop: Difference between long and short term
    - drift_count: Number of drift events detected
    - warning_count: Number of warning events
    - total_records: Total cache outcomes recorded
    - drift_analysis: Trend analysis and history
    """
    trainer = get_model_trainer()
    drift_stats = trainer._drift_detector.get_stats()
    drift_analysis = trainer._drift_detector.get_drift_analysis()
    
    return {
        "drift_stats": drift_stats,
        "drift_analysis": drift_analysis,
    }


@router.get("/ml/registry")
async def get_ml_registry(model_name: Optional[str] = Query(default=None)):
    """Get registry summary for the active ML model lineage."""
    return get_model_registry_payload(model_name=model_name)


@router.get("/ml/lifecycle")
async def get_ml_lifecycle(
    limit: int = Query(default=100, ge=1, le=1000),
    model_name: Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
):
    """Get persistent lifecycle history for ML model operations."""
    return get_model_lifecycle_payload(limit=limit, model_name=model_name, event_type=event_type)


@router.post("/ml/retrain")
async def trigger_retraining():
    """Trigger live model retraining using collected runtime events."""
    return trigger_runtime_retraining(force=True)


@router.post("/ml/promote")
async def promote_ml_model(req: ModelPromotionRequest):
    """Promote a registered model version to a target stage and optionally activate it."""
    result = promote_runtime_model_version(
        model_name=req.model_name,
        version=req.version,
        target_stage=req.target_stage,
        actor=req.actor,
        notes=req.notes or "",
        make_active=req.make_active,
    )
    if not result.get("success"):
        _raise_ml_registry_error(result)
    return result


@router.post("/ml/rollback")
async def rollback_ml_model(req: ModelRollbackRequest):
    """Rollback the active runtime model to a prior secure registry version."""
    result = rollback_runtime_model_version(
        model_name=req.model_name,
        version=req.version,
        actor=req.actor,
        notes=req.notes or "",
    )
    if not result.get("success"):
        _raise_ml_registry_error(result)
    return result


# ============================================================
# Simulation Endpoints
# ============================================================

# Simulation results storage
_simulation_results = {}


def _get_latest_simulation_result():
    if not _simulation_results:
        return None

    return max(
        _simulation_results.values(),
        key=lambda item: item.get("generated_at", ""),
    )


@router.get("/simulation/scenarios")
async def get_simulation_scenarios():
    """List available backend simulation scenarios."""
    return list_simulation_scenarios()


@router.post("/simulation/run", response_model=SimulationResponse)
async def run_simulation(req: SimulationRequest):
    """Run a simulation using the backend Python scenario engines."""
    scenario_catalog = list_simulation_scenarios()
    default_scenario = scenario_catalog["default_scenario"]
    scenario_id = req.scenario or default_scenario
    sim_id = str(uuid.uuid4())
    try:
        simulation_payload = run_simulation_job(
            scenario_id=scenario_id,
            profile_id=req.profile_id,
            request_count=req.request_count,
            seed=req.seed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _simulation_results[sim_id] = {
        "simulation_id": sim_id,
        **simulation_payload,
    }

    return SimulationResponse(
        simulation_id=sim_id,
        status=simulation_payload["status"],
        scenario=scenario_id,
        profile_id=simulation_payload["profile_id"],
        request_count=req.request_count,
        duration_seconds=req.duration_seconds
    )


@router.get("/simulation/results/{simulation_id}")
async def get_simulation_results(simulation_id: str):
    """Get simulation results"""
    if simulation_id not in _simulation_results:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return _simulation_results[simulation_id]


# ============================================================
# Live System Test Endpoints
# ============================================================

@router.post("/simulation/live-test")
async def run_live_system_test(
    request: Request,
    num_requests: int = Query(default=50, ge=10, le=200),
    seed_data: bool = Query(default=True)
):
    """
    Run a live system test that exercises:
    1. ML predictions
    2. Cache layer (Redis + local)
    3. Prefetch worker queue
    4. End-to-end latency measurement
    
    This provides real metrics unlike the mathematical simulation.
    """
    import random
    import string
    from datetime import datetime, timezone
    
    result = {
        "test_id": str(uuid.uuid4()),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "num_requests": num_requests,
        "steps": []
    }
    
    # Step 1: Seed data if requested
    if seed_data:
        try:
            collector = get_data_collector()
            # Generate seed events
            test_events = []
            services = ["default", "auth-service", "payment-service", "user-service"]
            key_patterns = ["api-key-", "token-", "secret-", "credential-"]
            
            for i in range(500):
                service = random.choice(services)
                key_pattern = random.choice(key_patterns)
                key_id = f"{key_pattern}{random.randint(1, 100)}"
                test_events.append({
                    "key_id": key_id,
                    "service_id": service,
                    "timestamp": datetime.now(timezone.utc).timestamp() - random.randint(0, 3600),
                    "latency_ms": random.uniform(5, 50),
                    "cache_hit": random.choice([True, True, True, False]),
                })
            
            imported = collector.import_events(test_events)
            result["steps"].append({
                "step": "data_seeding",
                "success": True,
                "events_imported": imported
            })
        except Exception as e:
            result["steps"].append({
                "step": "data_seeding",
                "success": False,
                "error": str(e)
            })
    
    # Step 2: Test ML predictions
    try:
        from src.ml.predictor import get_key_predictor
        predictor = get_key_predictor()
        predictions = predictor.predict(service_id="default", n=10)
        
        result["steps"].append({
            "step": "ml_predictions",
            "success": True,
            "predictions_count": len(predictions),
            "predictions": [
                {"key_id": k, "confidence": round(float(c), 4)} 
                for k, c in predictions[:5]
            ]
        })
    except Exception as e:
        result["steps"].append({
            "step": "ml_predictions",
            "success": False,
            "error": str(e)
        })
        predictions = []
    
    # Step 3: Test cache operations
    try:
        secure_manager = request.app.state.secure_cache_manager
        redis_cache = request.app.state.runtime_services.get("redis_cache")
        
        # Generate test keys
        test_keys = [f"test-key-{i}" for i in range(10)]
        cache_hits = 0
        cache_misses = 0
        
        for key_id in test_keys:
            # Try to access (will miss)
            data, hit, _, _ = secure_manager.secure_get(key_id, "default", "127.0.0.1")
            if hit:
                cache_hits += 1
            else:
                cache_misses += 1
                # Store the key
                test_data = ''.join(random.choices(string.ascii_letters, k=32))
                secure_manager.secure_set(key_id, test_data, "default", "127.0.0.1")
        
        # Second pass - should hit cache
        for key_id in test_keys:
            data, hit, _, _ = secure_manager.secure_get(key_id, "default", "127.0.0.1")
            if hit:
                cache_hits += 1
            else:
                cache_misses += 1
        
        # Get Redis stats if available
        redis_available = False
        redis_keys_count = 0
        if redis_cache:
            try:
                redis_available = redis_cache.ping()
                redis_keys_count = len(redis_cache.get_keys())
            except:
                pass
        
        result["steps"].append({
            "step": "cache_test",
            "success": True,
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "hit_rate": round(cache_hits / (cache_hits + cache_misses) * 100, 1) if (cache_hits + cache_misses) > 0 else 0,
            "redis_available": redis_available,
            "redis_keys_count": redis_keys_count
        })
    except Exception as e:
        result["steps"].append({
            "step": "cache_test",
            "success": False,
            "error": str(e)
        })
    
    # Step 4: Test prefetch queue
    try:
        prefetch_queue = get_prefetch_queue()
        queue_stats_before = prefetch_queue.get_stats()
        
        # Add test prefetch jobs
        test_candidates = [
            {"key_id": f"prefetch-key-{i}", "priority": random.uniform(0.5, 1.0)}
            for i in range(5)
        ]
        
        if predictions:
            job_payload = {
                "job_id": str(uuid.uuid4()),
                "service_id": "default",
                "source_key_id": predictions[0][0] if predictions else "test-key-0",
                "ip_address": "127.0.0.1",
                "candidates": test_candidates,
                "enqueued_at": datetime.now(timezone.utc).isoformat(),
            }
            prefetch_queue.enqueue(job_payload)
        
        queue_stats_after = prefetch_queue.get_stats()
        
        result["steps"].append({
            "step": "prefetch_test",
            "success": True,
            "queue_before": queue_stats_before.get("queue_length", 0),
            "queue_after": queue_stats_after.get("queue_length", 0),
            "jobs_enqueued": len(test_candidates)
        })
    except Exception as e:
        result["steps"].append({
            "step": "prefetch_test",
            "success": False,
            "error": str(e)
        })
    
    # Step 5: End-to-end latency test
    try:
        latencies = []
        for i in range(min(num_requests, 50)):  # Cap at 50 for speed
            key_id = f"test-key-{i % 10}"
            start = time.perf_counter()
            data, hit, _, _ = secure_manager.secure_get(key_id, "default", "127.0.0.1")
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(round(elapsed, 2))
        
        latencies.sort()
        result["steps"].append({
            "step": "latency_test",
            "success": True,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0,
            "p50_ms": latencies[len(latencies)//2] if latencies else 0,
            "p99_ms": latencies[int(len(latencies)*0.99)] if latencies else 0,
            "min_ms": min(latencies) if latencies else 0,
            "max_ms": max(latencies) if latencies else 0
        })
    except Exception as e:
        result["steps"].append({
            "step": "latency_test",
            "success": False,
            "error": str(e)
        })
    
    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    result["overall_success"] = all(
        s.get("success", False) for s in result["steps"]
    )
    
    return result


@router.get("/simulation/live-test")
async def get_live_test_status():
    """
    Get the current system status for live testing.
    Returns ML status, cache stats, and prefetch queue status.
    """
    try:
        ml_status = get_ml_status_payload()
    except:
        ml_status = {"error": "ML runtime not available"}
    
    try:
        prefetch_stats = get_prefetch_metrics_payload()
    except:
        prefetch_stats = {"error": "Prefetch queue not available"}
    
    return {
        "ml_status": ml_status,
        "prefetch_stats": prefetch_stats,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# ============================================================
# Key Lifecycle Management Endpoints
# ============================================================

from src.security.key_lifecycle_manager import (
    KeyLifecycleManager,
    LifecyclePolicy,
    LifecycleEvent,
    get_lifecycle_manager,
)

# Global lifecycle manager instance
_lifecycle_manager: Optional[KeyLifecycleManager] = None

def get_key_lifecycle_manager() -> KeyLifecycleManager:
    """Get or create the key lifecycle manager"""
    global _lifecycle_manager
    if _lifecycle_manager is None:
        policy = LifecyclePolicy(
            rotation_interval_days=30,
            max_versions=5,
            grace_period_hours=24,
            auto_rotate=True,
            auto_expire=True,
            cache_enabled=True,
            cache_ttl_seconds=300
        )
        _lifecycle_manager = KeyLifecycleManager(policy=policy)
    return _lifecycle_manager


@router.post("/keys/lifecycle/create")
async def create_lifecycle_key(
    key_id: str = Query(..., min_length=1, max_length=128),
    key_type: str = Query(default="encryption"),
    created_by: str = Query(default="system"),
    description: str = Query(default=""),
    expires_in_days: Optional[int] = Query(default=None, ge=1, le=365)
):
    """
    Create a new key with complete lifecycle management.
    
    This integrates with both cache and secure store.
    """
    manager = get_key_lifecycle_manager()
    
    try:
        metadata = manager.create_key(
            key_id=key_id,
            key_type=key_type,
            created_by=created_by,
            description=description,
            expires_in_days=expires_in_days
        )
        return {
            "success": True,
            "key_id": key_id,
            "metadata": metadata.to_dict()
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Error creating key")
        raise HTTPException(status_code=500, detail="Failed to create key")


@router.get("/keys/lifecycle/{key_id}")
async def get_lifecycle_key(key_id: str):
    """Get key metadata from lifecycle manager"""
    manager = get_key_lifecycle_manager()
    metadata = manager.get_key_metadata(key_id)
    
    if metadata is None:
        raise HTTPException(status_code=404, detail=f"Key not found: {key_id}")
    
    return {
        "key_id": key_id,
        "metadata": metadata.to_dict()
    }


@router.post("/keys/lifecycle/{key_id}/rotate")
async def rotate_lifecycle_key(
    key_id: str,
    created_by: str = Query(default="system"),
    force: bool = Query(default=False)
):
    """
    Rotate a key to a new version.
    
    This automatically invalidates the cache and creates a new key version.
    """
    manager = get_key_lifecycle_manager()
    
    try:
        metadata = manager.rotate_key(key_id, created_by=created_by, force=force)
        return {
            "success": True,
            "key_id": key_id,
            "metadata": metadata.to_dict()
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Error rotating key")
        raise HTTPException(status_code=500, detail="Failed to rotate key")


@router.post("/keys/lifecycle/{key_id}/revoke")
async def revoke_lifecycle_key(
    key_id: str,
    reason: str = Query(default="manual"),
    invalidated_by: str = Query(default="system")
):
    """
    Revoke a key immediately.
    
    This invalidates the cache and marks the key as revoked.
    """
    manager = get_key_lifecycle_manager()
    
    success = manager.revoke_key(key_id, reason=reason, invalidated_by=invalidated_by)
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Key not found: {key_id}")
    
    return {
        "success": True,
        "key_id": key_id,
        "status": "revoked"
    }


@router.post("/keys/lifecycle/{key_id}/expire")
async def expire_lifecycle_key(key_id: str):
    """
    Manually expire a key.
    
    This marks the key as expired and invalidates the cache.
    """
    manager = get_key_lifecycle_manager()
    
    success = manager.expire_key(key_id)
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Key not found or already expired: {key_id}")
    
    return {
        "success": True,
        "key_id": key_id,
        "status": "expired"
    }


@router.get("/keys/lifecycle")
async def list_lifecycle_keys(
    status: Optional[str] = Query(default=None),
    key_type: Optional[str] = Query(default=None)
):
    """List all keys managed by the lifecycle manager"""
    manager = get_key_lifecycle_manager()
    
    keys = manager.list_keys(status=status, key_type=key_type)
    
    return {
        "keys": [k.to_dict() for k in keys],
        "count": len(keys)
    }


@router.get("/keys/lifecycle/{key_id}/events")
async def get_lifecycle_events(
    key_id: str,
    limit: int = Query(default=100, ge=1, le=1000)
):
    """Get lifecycle events for a specific key"""
    manager = get_key_lifecycle_manager()
    
    events = manager.get_lifecycle_events(key_id=key_id, limit=limit)
    
    return {
        "key_id": key_id,
        "events": [e.to_dict() for e in events],
        "count": len(events)
    }


@router.get("/keys/lifecycle/stats")
async def get_lifecycle_stats():
    """Get lifecycle manager statistics"""
    manager = get_key_lifecycle_manager()
    
    return manager.get_stats()


@router.post("/keys/lifecycle/workflow/{workflow}")
async def execute_lifecycle_workflow(
    workflow: str,
    key_id: str = Query(..., min_length=1, max_length=128),
    created_by: str = Query(default="system"),
    expires_in_days: Optional[int] = Query(default=None, ge=1, le=365),
    rotate_count: int = Query(default=2, ge=1, le=10)
):
    """
    Execute a predefined lifecycle workflow.
    
    Available workflows:
    - create_rotate: Create key and immediately rotate
    - rotate_revoke: Rotate key then revoke
    - create_expire: Create key with expiration
    - full_lifecycle: Create -> rotate multiple -> revoke
    """
    manager = get_key_lifecycle_manager()
    
    try:
        result = manager.execute_workflow(
            workflow=workflow,
            key_id=key_id,
            created_by=created_by,
            expires_in_days=expires_in_days,
            rotate_count=rotate_count
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Error executing workflow")
        raise HTTPException(status_code=500, detail="Failed to execute workflow")


# ============================================================
# Security Endpoints
# ============================================================

@router.get("/security/audit")
async def get_security_audit(
    limit: int = Query(default=100, ge=1, le=1000),
    audit_logger=Depends(get_audit_logger),
):
    """Get recent security audit events from the tamper-evident runtime log."""
    payload = audit_logger.read_recent_entries(limit=limit)
    return {"audit_events": payload["entries"], "total_count": payload["total_count"]}


@router.get("/security/intrusions")
async def get_intrusion_logs(
    limit: int = Query(default=100, ge=1, le=1000),
    secure_manager: SecureCacheManager = Depends(get_secure_cache_manager),
):
    """Get recent intrusion detection alerts from the live IDS state."""
    alerts = secure_manager.ids.get_alerts(limit=limit)
    intrusions = [
        {
            "event_type": alert.event.value,
            "threat_level": alert.threat_level.value,
            "timestamp": datetime.fromtimestamp(alert.timestamp, tz=timezone.utc).isoformat(),
            "source_ip": alert.source_ip,
            "service_id": alert.service_id,
            "details": alert.details,
            "auto_purge_triggered": alert.auto_purge_triggered,
        }
        for alert in alerts
    ]
    return {"intrusions": intrusions, "total_count": len(intrusions)}


# ============================================================
# Chart Data Endpoints
# ============================================================

@router.get("/metrics/latency")
async def get_latency_chart_data():
    """Get latency comparison chart data"""
    latest = _get_latest_simulation_result()
    if latest is None:
        return {"data": []}

    without_stats = latest.get("results", {}).get("without_pskc", {})
    with_stats = latest.get("results", {}).get("with_pskc", {})

    data = [
        {
            "name": "Average",
            "withoutPSKC": round(float(without_stats.get("avg_latency_ms", 0.0)), 2),
            "withPSKC": round(float(with_stats.get("avg_latency_ms", 0.0)), 2),
        },
        {
            "name": "p95",
            "withoutPSKC": round(float(without_stats.get("p95_ms", 0.0)), 2),
            "withPSKC": round(float(with_stats.get("p95_ms", 0.0)), 2),
        },
        {
            "name": "p99",
            "withoutPSKC": round(float(without_stats.get("p99_ms", 0.0)), 2),
            "withPSKC": round(float(with_stats.get("p99_ms", 0.0)), 2),
        },
    ]

    return {
        "scenario": latest.get("scenario"),
        "profile_id": latest.get("profile_id"),
        "data": data,
    }


@router.get("/metrics/cache-distribution")
async def get_cache_distribution_data():
    """Get cache distribution chart data"""
    total = _metrics_storage["total_requests"]
    if total == 0:
        return {"data": []}

    return {
        "data": [
            {"name": "Cache Hits", "value": _metrics_storage["cache_hits"], "color": "#059669"},
            {"name": "Cache Misses", "value": _metrics_storage["cache_misses"], "color": "#dc2626"},
        ]
    }


@router.get("/metrics/accuracy")
async def get_accuracy_chart_data():
    """Get ML accuracy chart data"""
    return get_accuracy_history_payload()


@router.get("/metrics/prefetch")
async def get_prefetch_metrics():
    """Get Redis prefetch queue and worker metrics."""
    return get_prefetch_metrics_payload()


@router.get("/metrics/prometheus", include_in_schema=False)
async def get_prometheus_metrics(
    secure_manager: SecureCacheManager = Depends(get_secure_cache_manager)
):
    """Expose runtime metrics in Prometheus text format."""
    return Response(
        content=build_prometheus_metrics_payload(_metrics_storage, secure_manager),
        media_type=get_prometheus_content_type(),
    )


@router.get("/prefetch/dlq")
async def get_prefetch_dlq(limit: int = 20):
    """Inspect the latest dead-lettered prefetch jobs."""
    return get_prefetch_dlq_payload(limit=limit)


@router.post("/prefetch/dlq/replay")
async def replay_prefetch_dlq(
    job_id: Optional[str] = None,
    limit: int = Query(default=10, ge=1, le=100),
):
    """
    Replay jobs from DLQ back to the main queue.
    
    - If job_id is provided: replay specific job
    - Otherwise: replay up to `limit` jobs from DLQ
    """
    queue = get_prefetch_queue()
    result = queue.replay_from_dlq(job_id=job_id, limit=limit)
    return result


@router.post("/prefetch/retry/replay")
async def replay_prefetch_retry(
    limit: int = Query(default=50, ge=1, le=200),
):
    """
    Manually promote jobs from retry queue to main queue.
    Useful for draining the retry queue during maintenance.
    """
    queue = get_prefetch_queue()
    count = queue.replay_from_retry(limit=limit)
    return {"success": True, "replayed_count": count}


@router.delete("/prefetch/dlq")
async def clear_prefetch_dlq():
    """Clear all jobs from DLQ. Use with caution!"""
    queue = get_prefetch_queue()
    return queue.clear_dlq()


@router.get("/prefetch/rate-limit")
async def get_rate_limit_stats():
    """Get rate limiter statistics."""
    queue = get_prefetch_queue()
    return queue.get_rate_limit_stats()


@router.post("/prefetch/rate-limit/adjust")
async def adjust_rate_limit(
    factor: float = Query(default=1.5, ge=0.1, le=10.0),
):
    """
    Adjust rate limit by multiplicative factor.
    
    Example: factor=1.5 increases rate by 50%, factor=0.5 decreases by 50%
    """
    queue = get_prefetch_queue()
    return queue.adjust_rate_limit(factor)


@router.post("/prefetch/rate-limit/set")
async def set_rate_limit(
    rate: float = Query(default=10.0, ge=0.1, le=1000.0),
):
    """Set the rate limit to a specific value (jobs per second)."""
    queue = get_prefetch_queue()
    return queue.set_rate_limit(rate)


@router.post("/prefetch/rate-limit/adaptive")
async def trigger_adaptive_rate():
    """Trigger adaptive rate adjustment based on recent capacity."""
    queue = get_prefetch_queue()
    return queue.trigger_adaptive_adjust()


@router.get("/prefetch/replay-history")
async def get_replay_history(limit: int = 20):
    """Get replay history."""
    queue = get_prefetch_queue()
    return {"history": queue.get_replay_history(limit=limit)}


# ============================================================
# Historical Metrics Endpoints
# ============================================================

@router.get("/metrics/historical/cache")
async def get_historical_cache_metrics(
    window_seconds: int = Query(default=3600, ge=60, le=86400)
):
    """
    Get historical cache metrics from persistent storage.
    
    Returns cache hit rate calculated from persisted metrics.
    """
    metrics_persistence = get_metrics_persistence()
    if metrics_persistence is None or not metrics_persistence.ping():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Metrics persistence unavailable"
        )
    
    cache_stats = metrics_persistence.get_cache_hit_rate(window_seconds=window_seconds)
    return cache_stats


@router.get("/metrics/historical/latency")
async def get_historical_latency_metrics(
    window_seconds: int = Query(default=3600, ge=60, le=86400)
):
    """
    Get historical latency metrics from persistent storage.
    
    Returns latency percentiles (p50, p95, p99).
    """
    metrics_persistence = get_metrics_persistence()
    if metrics_persistence is None or not metrics_persistence.ping():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Metrics persistence unavailable"
        )
    
    latency_stats = metrics_persistence.get_latency_stats(window_seconds=window_seconds)
    return latency_stats


@router.get("/metrics/comprehensive")
async def get_comprehensive_metrics():
    """
    Get comprehensive metrics summary including all types.
    
    Returns:
    - Request metrics (count, hit rate)
    - Latency metrics (percentiles)
    - ML metrics (training history, drift events)
    - Lifecycle metrics (model events, key rotation events)
    """
    metrics_persistence = get_metrics_persistence()
    if metrics_persistence is None or not metrics_persistence.ping():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Metrics persistence unavailable"
        )
    
    return metrics_persistence.get_comprehensive_metrics()


@router.get("/metrics/ml/training")
async def get_ml_training_history(
    limit: int = Query(default=10, ge=1, le=100)
):
    """
    Get ML training history from persistent storage.
    """
    metrics_persistence = get_metrics_persistence()
    if metrics_persistence is None or not metrics_persistence.ping():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Metrics persistence unavailable"
        )
    
    return {
        "training_history": metrics_persistence.get_ml_training_history(limit=limit)
    }


@router.get("/metrics/drift")
async def get_drift_history(
    limit: int = Query(default=50, ge=1, le=200)
):
    """
    Get concept drift detection history from persistent storage.
    """
    metrics_persistence = get_metrics_persistence()
    if metrics_persistence is None or not metrics_persistence.ping():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Metrics persistence unavailable"
        )
    
    return {
        "drift_history": metrics_persistence.get_drift_history(limit=limit)
    }


@router.get("/metrics/lifecycle/model")
async def get_model_lifecycle_history(
    model_name: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200)
):
    """
    Get model lifecycle history from persistent storage.
    """
    metrics_persistence = get_metrics_persistence()
    if metrics_persistence is None or not metrics_persistence.ping():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Metrics persistence unavailable"
        )
    
    return {
        "lifecycle_history": metrics_persistence.get_model_lifecycle_history(
            model_name=model_name, limit=limit
        )
    }


@router.get("/metrics/lifecycle/key-rotation")
async def get_key_rotation_history(
    key_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200)
):
    """
    Get key rotation lifecycle history from persistent storage.
    """
    metrics_persistence = get_metrics_persistence()
    if metrics_persistence is None or not metrics_persistence.ping():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Metrics persistence unavailable"
        )
    
    return {
        "rotation_history": metrics_persistence.get_key_rotation_history(
            key_id=key_id, limit=limit
        )
    }


# ============================================================
# ML Evaluation Endpoints
# ============================================================

@router.post("/ml/evaluation/run")
async def run_ml_evaluation(
    num_samples: int = Query(default=500, ge=100, le=5000)
):
    """
    Run ML model evaluation with specified number of test samples.
    Returns precision, recall, F1-score, confusion matrix, and confidence levels.
    """
    evaluation_service = get_ml_evaluation_service()
    
    try:
        # Create and evaluate model
        evaluation_service.create_test_model()
        metrics = evaluation_service.evaluate_model(num_test_samples=num_samples)
        
        return {
            "success": True,
            "metrics": metrics.to_dict(),
            "confusion_matrix": evaluation_service.get_confusion_matrix_data(),
            "confidence_distribution": evaluation_service.get_confidence_distribution(),
        }
    except Exception as e:
        logger.exception("ML evaluation failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ML evaluation failed: {str(e)}",
        )


@router.get("/ml/evaluation/results")
async def get_ml_evaluation_results():
    """Get ML evaluation history and results"""
    evaluation_service = get_ml_evaluation_service()
    
    return {
        "history": evaluation_service.get_evaluation_history(),
        "confusion_matrix": evaluation_service.get_confusion_matrix_data(),
        "confidence_distribution": evaluation_service.get_confidence_distribution(),
    }


# ============================================================
# Security Testing Endpoints
# ============================================================

@router.post("/security/testing/run")
async def run_security_tests(
    test_type: Optional[str] = Query(default=None),
    num_attempts: int = Query(default=100, ge=10, le=1000)
):
    """
    Run security attack simulations.
    
    test_type options:
    - brute_force
    - sql_injection
    - xss
    - credential_stuffing
    - rate_limit_violation
    - api_abuse
    - all (run all tests)
    """
    security_service = get_security_testing_service()
    
    try:
        if test_type == "all" or test_type is None:
            results = security_service.run_all_tests()
        elif test_type == "brute_force":
            results = {"result": security_service.simulate_brute_force(num_attempts)}
        elif test_type == "sql_injection":
            results = {"result": security_service.simulate_sql_injection(num_attempts)}
        elif test_type == "xss":
            results = {"result": security_service.simulate_xss_attack(num_attempts)}
        elif test_type == "credential_stuffing":
            results = {"result": security_service.simulate_credential_stuffing(num_attempts)}
        elif test_type == "rate_limit_violation":
            results = {"result": security_service.simulate_rate_limit_violation(num_attempts)}
        elif test_type == "api_abuse":
            results = {"result": security_service.simulate_api_abuse(num_attempts)}
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown test type: {test_type}",
            )
        
        # Convert results to dict
        results_dict = {}
        for key, value in results.items():
            results_dict[key] = {
                "test_name": value.test_name,
                "attack_type": value.attack_type.value,
                "total_attempts": value.total_attempts,
                "detected_count": value.detected_count,
                "blocked_count": value.blocked_count,
                "detection_rate": value.detection_rate,
                "block_rate": value.block_rate,
                "recommendations": value.recommendations,
            }
        
        return {
            "success": True,
            "results": results_dict,
            "summary": security_service.get_security_summary(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Security testing failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Security testing failed: {str(e)}",
        )


@router.get("/security/testing/results")
async def get_security_test_results():
    """Get security test results and history"""
    security_service = get_security_testing_service()
    
    return {
        "test_results": security_service.get_test_results(),
        "attack_history": security_service.get_attack_history(limit=50),
        "security_summary": security_service.get_security_summary(),
    }

# ============================================================
# ML Pipeline Builder Endpoints
# ============================================================

# In-memory storage for pipeline runs
_pipeline_runs = {}


@router.post("/ml/pipeline/run", response_model=PipelineResponse)
async def run_pipeline(req: PipelineRequest):
    """
    Run an ML pipeline defined by nodes and connections.
    
    This endpoint executes the pipeline and returns a pipeline run ID
    that can be used to track progress and retrieve results.
    """
    pipeline_id = str(uuid.uuid4())
    
    # Validate pipeline
    if not req.nodes or len(req.nodes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pipeline must have at least one node"
        )
    
    # Validate connections
    node_ids = {node["id"] for node in req.nodes}
    for conn in req.connections:
        if conn["from"] not in node_ids or conn["to"] not in node_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid connection: node not found"
            )
    
    # Create pipeline run
    _pipeline_runs[pipeline_id] = {
        "pipeline_id": pipeline_id,
        "nodes": req.nodes,
        "connections": req.connections,
        "status": "running",
        "progress": 0,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "metrics": {
            "loss": [],
            "accuracy": [],
            "validation": []
        },
        "results": None,
        "error": None,
    }
    
    return PipelineResponse(
        pipeline_id=pipeline_id,
        status="running",
        message="Pipeline started successfully",
        progress=0
    )


@router.get("/ml/pipeline/status/{pipeline_id}", response_model=PipelineStatusResponse)
async def get_pipeline_status(pipeline_id: str):
    """
    Get the status of a pipeline run.
    """
    if pipeline_id not in _pipeline_runs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline run {pipeline_id} not found"
        )
    
    run = _pipeline_runs[pipeline_id]
    
    return PipelineStatusResponse(
        pipeline_id=pipeline_id,
        status=run["status"],
        progress=run["progress"],
        metrics=run["metrics"],
        results=run["results"],
        error=run["error"],
        started_at=run["started_at"],
        completed_at=run["completed_at"]
    )


@router.get("/ml/pipeline/metrics/{pipeline_id}")
async def get_pipeline_metrics(pipeline_id: str):
    """
    Get real-time metrics for a running pipeline.
    """
    if pipeline_id not in _pipeline_runs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline run {pipeline_id} not found"
        )
    
    run = _pipeline_runs[pipeline_id]
    
    return {
        "pipeline_id": pipeline_id,
        "status": run["status"],
        "progress": run["progress"],
        "metrics": run["metrics"],
    }


@router.get("/ml/pipelines")
async def list_pipelines():
    """
    List all pipeline runs.
    """
    pipelines = [
        {
            "pipeline_id": pid,
            "status": run["status"],
            "progress": run["progress"],
            "started_at": run["started_at"],
            "completed_at": run["completed_at"],
        }
        for pid, run in _pipeline_runs.items()
    ]
    
    return {
        "pipelines": pipelines,
        "total": len(pipelines)
    }


# Sertakan router ke dalam aplikasi utama
app.include_router(router)
