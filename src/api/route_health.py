# ============================================================
# Routes Health Endpoints Module
# ============================================================
import logging
from fastapi import APIRouter, Request
from src.api.schemas import HealthResponse, ReadinessResponse, StartupResponse
from src.prefetch.queue import get_prefetch_queue

logger = logging.getLogger(__name__)

# Global startup state for health checks
_startup_state = {
    "started": False,
    "startup_error": None,
    "startup_progress": "initializing",
}


def get_startup_state():
    """Get the startup state dictionary"""
    return _startup_state


def check_dependency_health(request: Request) -> dict:
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


def determine_readiness(dependencies: dict) -> tuple[bool, str]:
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


def create_health_router() -> APIRouter:
    """Create and return the health check router"""
    router = APIRouter(tags=["health"])
    
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
        dependencies = check_dependency_health(request)
        ready, status_message = determine_readiness(dependencies)
        
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
        startup_state = get_startup_state()
        if startup_state["started"]:
            return StartupResponse(
                started=True,
                status="ready",
                progress=startup_state["startup_progress"]
            )
        else:
            return StartupResponse(
                started=False,
                status="starting",
                progress=startup_state["startup_progress"],
                error=startup_state.get("startup_error")
            )
    
    return router
