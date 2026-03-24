# ============================================================
# Routes Admin Control Plane & Pipeline Endpoints Module
# ============================================================
import logging
import uuid
from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Query, HTTPException, status, Request, Depends

logger = logging.getLogger(__name__)

# In-memory storage for pipeline runs
_pipeline_runs = {}


def create_admin_router() -> APIRouter:
    """Create and return the admin control plane router"""
    from src.api.admin_control_plane import (
        get_admin_auth_manager, get_cache_admin_manager, get_model_admin_manager,
        get_security_admin_manager, AdminRole,
    )
    
    router = APIRouter(prefix="/admin", tags=["admin"])
    
    def _get_admin_auth_header(request: Request) -> Optional[str]:
        """Extract API key from X-Admin-Key header"""
        return request.headers.get("X-Admin-Key")
    
    def _require_admin_role(required_role: AdminRole = AdminRole.ADMIN):
        """Dependency that requires admin role"""
        def role_checker(request: Request):
            api_key = _get_admin_auth_header(request)
            if not api_key:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Admin API key required"
                )
            
            auth_manager = get_admin_auth_manager()
            user = auth_manager.authenticate(api_key)
            
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid admin API key"
                )
            
            if not auth_manager.authorize(user, required_role):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Insufficient permissions. Required role: {required_role.value}"
                )
            
            return user
        return role_checker

    @router.get("/auth/status")
    async def get_admin_auth_status():
        """Get admin auth system status"""
        auth_manager = get_admin_auth_manager()
        return auth_manager.get_stats()

    @router.get("/auth/audit")
    async def get_admin_audit_log(
        user_id: Optional[str] = Query(default=None),
        action: Optional[str] = Query(default=None),
        limit: int = Query(default=100, ge=1, le=1000)
    ):
        """Get admin action audit log"""
        auth_manager = get_admin_auth_manager()
        return {
            "audit_log": auth_manager.get_audit_log(
                user_id=user_id,
                action=action,
                limit=limit
            )
        }

    @router.get("/cache/summary")
    async def get_admin_cache_summary(
        request: Request,
        user = Depends(_require_admin_role(AdminRole.OPERATOR))
    ):
        """Get comprehensive cache summary per service"""
        cache_manager = get_cache_admin_manager(request.app.state.secure_cache_manager)
        return cache_manager.get_cache_summary()

    @router.post("/cache/invalidate")
    async def invalidate_cache_by_prefix(
        request: Request,
        prefix: str = Query(..., min_length=1),
        service_id: Optional[str] = Query(default=None),
        user = Depends(_require_admin_role(AdminRole.ADMIN))
    ):
        """Invalidate all cache keys matching prefix"""
        cache_manager = get_cache_admin_manager(request.app.state.secure_cache_manager)
        result = cache_manager.invalidate_by_prefix(prefix, service_id)
        
        auth_manager = get_admin_auth_manager()
        auth_manager.log_action(
            user_id=user.user_id,
            action="cache_invalidate_prefix",
            target=prefix,
            outcome="success" if result.get("deleted", 0) > 0 else "no_keys_found",
            details=result
        )
        
        return result

    @router.get("/cache/ttl/{key_id}")
    async def inspect_cache_key_ttl(
        request: Request,
        key_id: str,
        service_id: str = Query(default="default"),
        user = Depends(_require_admin_role(AdminRole.OPERATOR))
    ):
        """Inspect TTL and metadata of a specific cache key"""
        cache_manager = get_cache_admin_manager(request.app.state.secure_cache_manager)
        return cache_manager.inspect_key_ttl(key_id, service_id)

    @router.get("/cache/warmup")
    async def get_cache_warmup_status(
        request: Request,
        user = Depends(_require_admin_role(AdminRole.OPERATOR))
    ):
        """Get cache warmup status"""
        cache_manager = get_cache_admin_manager(request.app.state.secure_cache_manager)
        return cache_manager.get_warmup_status()

    @router.post("/cache/warmup")
    async def trigger_cache_warmup(
        request: Request,
        service_id: Optional[str] = Query(default=None),
        user = Depends(_require_admin_role(AdminRole.OPERATOR))
    ):
        """Trigger cache warmup for a service"""
        cache_manager = get_cache_admin_manager(request.app.state.secure_cache_manager)
        result = cache_manager.trigger_warmup(service_id)
        
        auth_manager = get_admin_auth_manager()
        auth_manager.log_action(
            user_id=user.user_id,
            action="cache_warmup",
            target=service_id or "all",
            outcome="success",
            details=result
        )
        
        return result

    @router.get("/model/versions")
    async def get_model_versions_by_stage(
        user = Depends(_require_admin_role(AdminRole.OPERATOR))
    ):
        """Get model versions grouped by stage"""
        model_manager = get_model_admin_manager()
        return model_manager.get_versions_by_stage()

    @router.get("/model/history/{model_name}")
    async def get_model_version_history(
        model_name: str,
        user = Depends(_require_admin_role(AdminRole.OPERATOR))
    ):
        """Get active version history for a model"""
        model_manager = get_model_admin_manager()
        return model_manager.get_active_version_history(model_name)

    @router.get("/model/compare")
    async def compare_model_versions(
        model_name: str = Query(...),
        version1: str = Query(...),
        version2: str = Query(...),
        user = Depends(_require_admin_role(AdminRole.OPERATOR))
    ):
        """Compare two model registry entries"""
        model_manager = get_model_admin_manager()
        return model_manager.compare_registry_entries(version1, version2, model_name)

    @router.get("/model/export/{model_name}")
    async def export_model_lifecycle(
        model_name: str,
        user = Depends(_require_admin_role(AdminRole.OPERATOR))
    ):
        """Export full lifecycle summary for a model"""
        model_manager = get_model_admin_manager()
        return model_manager.export_lifecycle_summary(model_name)

    @router.get("/security/summary")
    async def get_security_summary(
        request: Request,
        user = Depends(_require_admin_role(AdminRole.OPERATOR))
    ):
        """Get intrusion detection summary"""
        security_manager = get_security_admin_manager(
            ids=request.app.state.secure_cache_manager.ids if hasattr(request.app.state, "secure_cache_manager") else None,
            audit_logger=request.app.state.audit_logger if hasattr(request.app.state, "audit_logger") else None
        )
        return security_manager.get_intrusion_summary()

    @router.get("/security/blocked-ips")
    async def get_blocked_ips(
        request: Request,
        user = Depends(_require_admin_role(AdminRole.OPERATOR))
    ):
        """Get list of currently blocked IPs"""
        security_manager = get_security_admin_manager(
            ids=request.app.state.secure_cache_manager.ids if hasattr(request.app.state, "secure_cache_manager") else None
        )
        return security_manager.get_blocked_ips()

    @router.get("/security/reputation")
    async def get_ip_reputation(
        request: Request,
        user = Depends(_require_admin_role(AdminRole.OPERATOR))
    ):
        """Get IP reputation overview"""
        security_manager = get_security_admin_manager(
            ids=request.app.state.secure_cache_manager.ids if hasattr(request.app.state, "secure_cache_manager") else None
        )
        return security_manager.get_reputation_view()

    @router.post("/security/unblock")
    async def unblock_ip_address(
        request: Request,
        ip_address: str = Query(...),
        user = Depends(_require_admin_role(AdminRole.ADMIN))
    ):
        """Unblock a specific IP address"""
        security_manager = get_security_admin_manager(
            ids=request.app.state.secure_cache_manager.ids if hasattr(request.app.state, "secure_cache_manager") else None
        )
        result = security_manager.unblock_ip(ip_address)
        
        auth_manager = get_admin_auth_manager()
        auth_manager.log_action(
            user_id=user.user_id,
            action="security_unblock_ip",
            target=ip_address,
            outcome="success" if result.get("unblocked") else "failed",
            details=result
        )
        
        return result

    @router.get("/security/audit-recovery")
    async def get_audit_recovery_history(
        request: Request,
        user = Depends(_require_admin_role(AdminRole.OPERATOR))
    ):
        """Get audit log recovery history"""
        security_manager = get_security_admin_manager(
            ids=request.app.state.secure_cache_manager.ids if hasattr(request.app.state, "secure_cache_manager") else None
        )
        return security_manager.get_audit_recovery_history()

    return router


def create_pipeline_router() -> APIRouter:
    """Create and return the ML pipeline builder router"""
    from src.api.schemas import PipelineRequest, PipelineResponse, PipelineStatusResponse
    
    router = APIRouter(prefix="/ml/pipeline", tags=["pipeline"])

    @router.post("/run", response_model=PipelineResponse)
    async def run_pipeline(req: PipelineRequest):
        """Run an ML pipeline defined by nodes and connections."""
        pipeline_id = str(uuid.uuid4())
        
        if not req.nodes or len(req.nodes) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Pipeline must have at least one node"
            )
        
        node_ids = {node["id"] for node in req.nodes}
        for conn in req.connections:
            if conn["from"] not in node_ids or conn["to"] not in node_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid connection: node not found"
                )
        
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

    @router.get("/status/{pipeline_id}", response_model=PipelineStatusResponse)
    async def get_pipeline_status(pipeline_id: str):
        """Get the status of a pipeline run."""
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

    @router.get("/metrics/{pipeline_id}")
    async def get_pipeline_metrics(pipeline_id: str):
        """Get real-time metrics for a running pipeline."""
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

    @router.get("")
    async def list_pipelines():
        """List all pipeline runs."""
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

    return router
