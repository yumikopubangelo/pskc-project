# ============================================================
# Routes Metrics Endpoints Module
# ============================================================
import logging
from fastapi import APIRouter, Depends, Query, Request, status, HTTPException
from src.api.schemas import MetricsResponse
from src.security.intrusion_detection import SecureCacheManager
from src.observability.metrics_persistence import get_metrics_persistence
from src.api.ml_service import (
    get_accuracy_history_payload,
    get_prefetch_metrics_payload,
    get_prefetch_dlq_payload,
)
from src.api.route_keys import get_metrics_storage, get_secure_cache_manager
from src.prefetch.queue import get_prefetch_queue

logger = logging.getLogger(__name__)


def create_metrics_router() -> APIRouter:
    """Create and return the metrics router"""
    router = APIRouter(prefix="/metrics", tags=["metrics"])

    @router.get("", response_model=MetricsResponse)
    async def get_metrics(
        secure_manager: SecureCacheManager = Depends(get_secure_cache_manager)
    ):
        """Get system metrics"""
        metrics = get_metrics_storage()
        hits = metrics["cache_hits"]
        misses = metrics["cache_misses"]
        total = metrics["total_requests"]
        hit_rate = hits / total if total > 0 else 0.0
        avg_latency = sum(metrics["latencies"]) / len(metrics["latencies"]) if metrics["latencies"] else 0.0
        active_keys = len(secure_manager.get_cache_keys())
        
        return MetricsResponse(
            cache_hits=hits,
            cache_misses=misses,
            cache_hit_rate=hit_rate,
            total_requests=total,
            avg_latency_ms=avg_latency,
            active_keys=active_keys
        )

    @router.get("/latency")
    async def get_latency_chart_data():
        """Get latency comparison chart data"""
        # This would reference simulation results if they exist
        return {"data": []}

    @router.get("/cache-distribution")
    async def get_cache_distribution_data():
        """Get cache distribution chart data"""
        metrics = get_metrics_storage()
        total = metrics["total_requests"]
        if total == 0:
            return {"data": []}

        return {
            "data": [
                {"name": "Cache Hits", "value": metrics["cache_hits"], "color": "#059669"},
                {"name": "Cache Misses", "value": metrics["cache_misses"], "color": "#dc2626"},
            ]
        }

    @router.get("/accuracy")
    async def get_accuracy_chart_data():
        """Get ML accuracy chart data"""
        return get_accuracy_history_payload()

    @router.get("/prefetch")
    async def get_prefetch_metrics():
        """Get Redis prefetch queue and worker metrics."""
        return get_prefetch_metrics_payload()

    @router.get("/prometheus", include_in_schema=False)
    async def get_prometheus_metrics(
        secure_manager: SecureCacheManager = Depends(get_secure_cache_manager)
    ):
        """Expose runtime metrics in Prometheus text format."""
        from src.observability.prometheus_exporter import (
            build_prometheus_metrics_payload,
            get_prometheus_content_type,
        )
        from fastapi.responses import Response
        
        return Response(
            content=build_prometheus_metrics_payload(get_metrics_storage(), secure_manager),
            media_type=get_prometheus_content_type(),
        )

    @router.get("/historical/cache")
    async def get_historical_cache_metrics(
        window_seconds: int = Query(default=3600, ge=60, le=86400)
    ):
        """Get historical cache metrics from persistent storage."""
        metrics_persistence = get_metrics_persistence()
        if metrics_persistence is None or not metrics_persistence.ping():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Metrics persistence unavailable"
            )
        
        return metrics_persistence.get_cache_hit_rate(window_seconds=window_seconds)

    @router.get("/historical/latency")
    async def get_historical_latency_metrics(
        window_seconds: int = Query(default=3600, ge=60, le=86400)
    ):
        """Get historical latency metrics from persistent storage."""
        metrics_persistence = get_metrics_persistence()
        if metrics_persistence is None or not metrics_persistence.ping():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Metrics persistence unavailable"
            )
        
        return metrics_persistence.get_latency_stats(window_seconds=window_seconds)

    @router.get("/comprehensive")
    async def get_comprehensive_metrics():
        """Get comprehensive metrics summary including all types."""
        metrics_persistence = get_metrics_persistence()
        if metrics_persistence is None or not metrics_persistence.ping():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Metrics persistence unavailable"
            )
        
        return metrics_persistence.get_comprehensive_metrics()

    @router.get("/ml/training")
    async def get_ml_training_history(
        limit: int = Query(default=10, ge=1, le=100)
    ):
        """Get ML training history from persistent storage."""
        metrics_persistence = get_metrics_persistence()
        if metrics_persistence is None or not metrics_persistence.ping():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Metrics persistence unavailable"
            )
        
        return {
            "training_history": metrics_persistence.get_ml_training_history(limit=limit)
        }

    @router.get("/drift")
    async def get_drift_history(
        limit: int = Query(default=50, ge=1, le=200)
    ):
        """Get concept drift detection history from persistent storage."""
        metrics_persistence = get_metrics_persistence()
        if metrics_persistence is None or not metrics_persistence.ping():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Metrics persistence unavailable"
            )
        
        return {
            "drift_history": metrics_persistence.get_drift_history(limit=limit)
        }

    @router.get("/lifecycle/model")
    async def get_model_lifecycle_history(
        model_name: str = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200)
    ):
        """Get model lifecycle history from persistent storage."""
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

    @router.get("/lifecycle/key-rotation")
    async def get_key_rotation_history(
        key_id: str = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200)
    ):
        """Get key rotation lifecycle history from persistent storage."""
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

    return router
