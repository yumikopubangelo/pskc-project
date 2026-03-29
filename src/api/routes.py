# ============================================================
# PSKC — API Routes Main Orchestrator
# ============================================================
# This file orchestrates all refactored route modules
# See src/api/route_*.py for individual endpoint implementations

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.security.fips_self_tests import run_power_on_self_tests, FipsSelfTestFailure
from src.api.ml_service import (
    initialize_ml_runtime,
    shutdown_ml_runtime,
    record_runtime_access,
    schedule_request_path_prefetch,
    get_model_registry_payload,
    get_model_lifecycle_payload,
    get_model_evaluation_payload,
    promote_runtime_model_version,
    rollback_runtime_model_version,
)
from src.runtime.bootstrap import build_runtime_services, shutdown_runtime_services
from src.prefetch.queue import get_prefetch_queue
from src.security.security_headers import SecurityHeadersMiddleware, SlidingWindowRateLimiter, configure_trusted_proxies
from config.settings import settings
from src.auth.key_fetcher import get_key_fetcher
from src.api.live_validation_service import run_live_validation
from src.api.live_simulation_service import (
    start_live_simulation_session,
    get_live_simulation_session,
    stop_live_simulation_session,
)

# Import all route modules
from src.api.route_health import create_health_router, get_startup_state
from src.api.route_keys import create_key_router, metrics_storage as _metrics_storage
from src.api.route_metrics import create_metrics_router
from src.api.route_prefetch import create_prefetch_router
from src.api.route_ml import create_ml_router
from src.api.route_training import create_training_router
from src.api.route_simulation import create_simulation_router
from src.api.route_security_lifecycle import create_security_router, create_lifecycle_router
from src.api.route_admin_pipeline import create_admin_router, create_pipeline_router
from src.api.routes_models import router as models_router, legacy_router as legacy_models_router
from src.api.routes_observability import router as observability_router
from src.api.routes_dashboard import router as dashboard_router
from src.api.routes_admin_db import router as admin_db_router

logger = logging.getLogger(__name__)


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle manager for startup and shutdown."""
    startup_state = get_startup_state()
    logger.info("Application starting up...")
    startup_state["startup_progress"] = "building_services"

    runtime_services = build_runtime_services()
    fips_module = runtime_services["fips_module"]
    audit_logger = runtime_services["audit_logger"]
    secure_cache_manager = runtime_services["secure_cache_manager"]
    redis_cache = runtime_services.get("redis_cache")
    
    startup_state["startup_progress"] = "running_fips_self_tests"
    if bool(_get_setting("fips_self_test_enabled", True)):
        try:
            run_power_on_self_tests(fips_module)
        except FipsSelfTestFailure as e:
            logger.critical(f"FIPS self-test failed: {e}. Application will not start.")
            startup_state["startup_error"] = str(e)
            shutdown_runtime_services(runtime_services)
            raise RuntimeError("FIPS Power-On Self-Test failed.") from e
    else:
        logger.warning("FIPS power-on self-tests are disabled by configuration.")

    startup_state["startup_progress"] = "initializing_ml_runtime"
    ml_runtime = initialize_ml_runtime()
    
    startup_state["startup_progress"] = "priming_dependencies"
    if redis_cache is not None:
        _prime_optional_dependency("redis cache", redis_cache)
    _prime_optional_dependency("prefetch queue", get_prefetch_queue())

    app.state.fips_module = fips_module
    app.state.audit_logger = audit_logger
    app.state.secure_cache_manager = secure_cache_manager
    app.state.ml_runtime = ml_runtime
    app.state.runtime_services = runtime_services
    
    audit_logger.log("SYSTEM", "APP_STARTUP", "SUCCESS")
    
    startup_state["started"] = True
    startup_state["startup_progress"] = "ready"
    logger.info("Startup finished successfully.")
    
    yield

    logger.info("Application shutting down...")
    startup_state["started"] = False
    startup_state["startup_progress"] = "shutting_down"
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
        app.add_middleware(
            SlidingWindowRateLimiter,
            max_requests=http_rate_limit_max_requests,
            window_seconds=http_rate_limit_window_seconds,
            burst_max=http_rate_limit_burst_max,
            burst_window=http_rate_limit_burst_window_seconds,
            whitelist_private_ips=http_rate_limit_whitelist_private_ips,
            exempt_paths={
                "/health", "/metrics",
                "/ml/training/progress/stream",
                "/ml/training/generate-progress/stream",
            },
        )

    logger.info(
        "HTTP security middleware configured: headers=%s rate_limit=%s trusted_proxies=%s sensitive_path_block=%s",
        http_security_enabled,
        http_rate_limit_enabled,
        len(configure_trusted_proxies(_get_trusted_proxy_networks())),
        http_security_block_sensitive_from_external,
    )


# Create FastAPI app with lifecycle manager
app = FastAPI(lifespan=lifespan)
_register_http_security_middleware(app)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:4173"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register all refactored route modules
app.include_router(create_health_router())
app.include_router(create_key_router())
app.include_router(create_metrics_router())
app.include_router(create_prefetch_router())
app.include_router(create_ml_router())
app.include_router(create_training_router())
app.include_router(create_simulation_router())
app.include_router(create_security_router())
app.include_router(create_lifecycle_router())
app.include_router(create_admin_router())
app.include_router(create_pipeline_router())
app.include_router(models_router)
app.include_router(legacy_models_router)
app.include_router(observability_router)
app.include_router(dashboard_router)
app.include_router(admin_db_router)

logger.info("All route modules registered successfully")
