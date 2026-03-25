# ============================================================
# PSKC — Enhanced Observability API Routes
# ============================================================
"""
API endpoints for enhanced observability metrics.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
import logging

from src.database.connection import get_db
from src.observability.enhanced_observability import EnhancedObservabilityService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/observability", tags=["observability"])


def get_observability_service(
    db: Session = Depends(get_db)
) -> EnhancedObservabilityService:
    """Dependency injection for observability service."""
    return EnhancedObservabilityService(db)


@router.get("/metrics/per-key")
async def get_per_key_metrics(
    version_id: int = Query(..., description="Model version ID"),
    key: Optional[str] = Query(None, description="Specific key (optional)"),
    service: EnhancedObservabilityService = Depends(get_observability_service)
):
    """
    Get per-key metrics (accuracy, drift score, cache hit rate).
    
    Parameters:
    - version_id: Model version ID
    - key: Specific key to filter (optional)
    """
    metrics = service.get_per_key_metrics(version_id, key)
    return {
        "version_id": version_id,
        "count": len(metrics),
        "metrics": metrics
    }


@router.get("/metrics/latency")
async def get_latency_metrics(
    key: Optional[str] = Query(None, description="Specific key (optional)"),
    service: EnhancedObservabilityService = Depends(get_observability_service)
):
    """
    Get latency metrics and statistics.
    
    Parameters:
    - key: Specific key to get latency for (optional, all keys if None)
    """
    latency_metrics = service.get_latency_metrics(key)
    return {
        "latency": latency_metrics
    }


@router.get("/metrics/benchmark")
async def get_benchmark_metrics(
    version_id: int = Query(..., description="Model version ID"),
    baseline_latency_ms: Optional[float] = Query(
        None,
        description="Baseline latency for comparison"
    ),
    service: EnhancedObservabilityService = Depends(get_observability_service)
):
    """
    Get benchmark metrics showing PSKC effectiveness.
    
    Parameters:
    - version_id: Model version ID
    - baseline_latency_ms: Baseline latency to compare against (optional)
    
    Returns:
    - hit_rate: Percentage of correct predictions
    - latency_reduction_percent: Percentage latency reduction vs baseline
    - speedup_factor: How much faster than baseline
    - cache_hit_rate: Cache efficiency
    """
    benchmark = service.get_benchmark_metrics(version_id, baseline_latency_ms)
    return benchmark


@router.get("/metrics/drift")
async def get_drift_summary(
    version_id: int = Query(..., description="Model version ID"),
    service: EnhancedObservabilityService = Depends(get_observability_service)
):
    """
    Get drift detection summary across all keys.
    
    Parameters:
    - version_id: Model version ID
    
    Returns:
    - avg_drift_score: Average concept drift across keys
    - keys_with_drift: Number of keys experiencing drift
    - max_drift_score: Highest drift score
    """
    drift_summary = service.get_drift_summary(version_id)
    return drift_summary


@router.get("/metrics/accuracy-trend")
async def get_accuracy_trend(
    key: Optional[str] = Query(None, description="Specific key (optional)"),
    days: int = Query(7, description="Days to look back"),
    service: EnhancedObservabilityService = Depends(get_observability_service)
):
    """
    Get accuracy trend over time (hourly aggregation).
    
    Parameters:
    - key: Specific key to get trend for (optional)
    - days: Number of days to look back (default: 7)
    """
    trend = service.get_accuracy_trend(key, days)
    return {
        "key": key,
        "days": days,
        "trend": trend
    }


@router.get("/metrics/comprehensive")
async def get_comprehensive_metrics(
    version_id: int = Query(..., description="Model version ID"),
    baseline_latency_ms: Optional[float] = Query(None),
    service: EnhancedObservabilityService = Depends(get_observability_service)
):
    """
    Get all metrics in a single comprehensive response.
    
    Parameters:
    - version_id: Model version ID
    - baseline_latency_ms: Baseline for benchmark (optional)
    
    Returns combined:
    - per_key_metrics: Accuracy and drift per key
    - latency_metrics: Latency statistics
    - benchmark_metrics: Speedup and effectiveness
    - drift_summary: Concept drift overview
    """
    return {
        "version_id": version_id,
        "per_key_metrics": service.get_per_key_metrics(version_id),
        "latency_metrics": service.get_latency_metrics(),
        "benchmark_metrics": service.get_benchmark_metrics(
            version_id,
            baseline_latency_ms
        ),
        "drift_summary": service.get_drift_summary(version_id),
        "timestamp": service.drift_detector.drift_scores or None
    }
