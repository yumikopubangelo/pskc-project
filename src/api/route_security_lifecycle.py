# ============================================================
# Routes Security & Lifecycle Endpoints Module
# ============================================================
import logging
from typing import Optional
from fastapi import APIRouter, Query, HTTPException, status, Request, Depends
from datetime import datetime, timezone

from src.security.intrusion_detection import SecureCacheManager
from src.api.route_keys import get_secure_cache_manager

logger = logging.getLogger(__name__)


def get_audit_logger(request: Request):
    return request.app.state.audit_logger


def create_security_router() -> APIRouter:
    """Create and return the security endpoints router"""
    router = APIRouter(prefix="/security", tags=["security"])

    @router.get("/audit")
    async def get_security_audit(
        limit: int = Query(default=100, ge=1, le=1000),
        audit_logger=Depends(get_audit_logger),
    ):
        """Get recent security audit events from the tamper-evident runtime log."""
        payload = audit_logger.read_recent_entries(limit=limit)
        return {"audit_events": payload["entries"], "total_count": payload["total_count"]}

    @router.get("/intrusions")
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

    @router.post("/testing/run")
    async def run_security_tests(
        test_type: Optional[str] = Query(default=None),
        num_attempts: int = Query(default=100, ge=10, le=1000)
    ):
        """Run security attack simulations."""
        from src.security.security_testing import get_security_testing_service
        
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

    @router.get("/testing/results")
    async def get_security_test_results():
        """Get security test results and history"""
        from src.security.security_testing import get_security_testing_service
        
        security_service = get_security_testing_service()
        
        return {
            "test_results": security_service.get_test_results(),
            "attack_history": security_service.get_attack_history(limit=50),
            "security_summary": security_service.get_security_summary(),
        }

    return router


def create_lifecycle_router() -> APIRouter:
    """Create and return the key lifecycle endpoints router"""
    from src.security.key_lifecycle_manager import (
        KeyLifecycleManager, LifecyclePolicy, get_lifecycle_manager,
    )
    
    router = APIRouter(prefix="/keys/lifecycle", tags=["lifecycle"])
    
    def get_key_lifecycle_manager() -> KeyLifecycleManager:
        """Get or create the key lifecycle manager"""
        policy = LifecyclePolicy(
            rotation_interval_days=30,
            max_versions=5,
            grace_period_hours=24,
            auto_rotate=True,
            auto_expire=True,
            cache_enabled=True,
            cache_ttl_seconds=300
        )
        return get_lifecycle_manager(policy=policy)

    @router.post("/create")
    async def create_lifecycle_key(
        key_id: str = Query(..., min_length=1, max_length=128),
        key_type: str = Query(default="encryption"),
        created_by: str = Query(default="system"),
        description: str = Query(default=""),
        expires_in_days: Optional[int] = Query(default=None, ge=1, le=365)
    ):
        """Create a new key with complete lifecycle management."""
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

    @router.get("/{key_id}")
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

    @router.post("/{key_id}/rotate")
    async def rotate_lifecycle_key(
        key_id: str,
        created_by: str = Query(default="system"),
        force: bool = Query(default=False)
    ):
        """Rotate a key to a new version."""
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

    @router.post("/{key_id}/revoke")
    async def revoke_lifecycle_key(
        key_id: str,
        reason: str = Query(default="manual"),
        invalidated_by: str = Query(default="system")
    ):
        """Revoke a key immediately."""
        manager = get_key_lifecycle_manager()
        success = manager.revoke_key(key_id, reason=reason, invalidated_by=invalidated_by)
        
        if not success:
            raise HTTPException(status_code=404, detail=f"Key not found: {key_id}")
        
        return {
            "success": True,
            "key_id": key_id,
            "status": "revoked"
        }

    @router.post("/{key_id}/expire")
    async def expire_lifecycle_key(key_id: str):
        """Manually expire a key."""
        manager = get_key_lifecycle_manager()
        success = manager.expire_key(key_id)
        
        if not success:
            raise HTTPException(status_code=404, detail=f"Key not found or already expired: {key_id}")
        
        return {
            "success": True,
            "key_id": key_id,
            "status": "expired"
        }

    @router.get("")
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

    @router.get("/{key_id}/events")
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

    @router.get("/stats")
    async def get_lifecycle_stats():
        """Get lifecycle manager statistics"""
        manager = get_key_lifecycle_manager()
        return manager.get_stats()

    @router.post("/workflow/{workflow}")
    async def execute_lifecycle_workflow(
        workflow: str,
        key_id: str = Query(..., min_length=1, max_length=128),
        created_by: str = Query(default="system"),
        expires_in_days: Optional[int] = Query(default=None, ge=1, le=365),
        rotate_count: int = Query(default=2, ge=1, le=10)
    ):
        """Execute a predefined lifecycle workflow."""
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

    return router
