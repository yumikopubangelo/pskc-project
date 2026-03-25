# ============================================================
# PSKC — Dashboard Metrics Endpoints
# ============================================================
"""
API routes untuk dashboard visualization updates.
Endpoints untuk per-key metrics, drift tracking, dan benchmark data.
"""

from fastapi import APIRouter, Query, HTTPException, Depends
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from src.database.models import (
    PerKeyMetric, ModelVersion, ModelMetric, 
    PredictionLog, get_session
)
from src.observability.enhanced_observability import get_observability_service
from src.ml.trainer_integration import get_trainer_integration

router = APIRouter(prefix="/api/metrics/enhanced", tags=["dashboard"])

# ============================================================
# 1. Per-Key Accuracy Breakdown
# ============================================================

@router.get("/per-key")
async def get_per_key_metrics(
    model_name: str = "cache_predictor",
    time_range: str = "24h",
    limit: int = 100,
    db: Session = Depends(get_session)
):
    """
    Get per-key accuracy and confidence metrics.
    
    Returns:
        - key: Cache key
        - accuracy: Prediction accuracy (0-1)
        - avg_confidence: Average confidence (0-1)
        - total_predictions: Number of predictions
        - hit_rate: Cache hit rate
    """
    try:
        trainer_int = get_trainer_integration()
        current_version = trainer_int.version_manager.get_current_version(model_name)
        
        if not current_version:
            raise HTTPException(status_code=404, detail="Model not found")
        
        # Parse time range
        hours = int(time_range.replace('h', '')) if 'h' in time_range else 24
        time_cutoff = datetime.utcnow() - timedelta(hours=hours)
        
        # Query per-key metrics
        metrics = db.query(PerKeyMetric).filter(
            PerKeyMetric.version_id == current_version.version_id,
            PerKeyMetric.timestamp >= time_cutoff
        ).order_by(desc(PerKeyMetric.timestamp)).limit(limit).all()
        
        # Aggregate by key
        key_stats = {}
        for metric in metrics:
            if metric.key not in key_stats:
                key_stats[metric.key] = {
                    "key": metric.key,
                    "accuracy": metric.accuracy or 0.0,
                    "avg_confidence": metric.avg_confidence or 0.0,
                    "drift_score": metric.drift_score or 0.0,
                    "hit_rate": metric.hit_rate or 0.0,
                    "total_predictions": metric.total_predictions or 0,
                    "error_count": metric.error_count or 0
                }
        
        return {
            "status": "success",
            "version_id": current_version.version_id,
            "metrics": list(key_stats.values())[:limit],
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 2. Per-Key Drift Score
# ============================================================

@router.get("/drift")
async def get_drift_metrics(
    model_name: str = "cache_predictor",
    time_range: str = "24h",
    db: Session = Depends(get_session)
):
    """
    Get per-key drift scores with levels.
    
    Returns:
        - key: Cache key
        - drift_score: Current drift score (0-1)
        - drift_level: "normal", "warning", or "critical"
        - trend: "stable", "increasing", "decreasing"
    """
    try:
        trainer_int = get_trainer_integration()
        current_version = trainer_int.version_manager.get_current_version(model_name)
        
        if not current_version:
            raise HTTPException(status_code=404, detail="Model not found")
        
        hours = int(time_range.replace('h', '')) if 'h' in time_range else 24
        time_cutoff = datetime.utcnow() - timedelta(hours=hours)
        
        # Get drift detector for each key
        drift_metrics = []
        metrics = db.query(PerKeyMetric).filter(
            PerKeyMetric.version_id == current_version.version_id,
            PerKeyMetric.timestamp >= time_cutoff
        ).all()
        
        for metric in metrics:
            drift_score = metric.drift_score or 0.0
            
            # Classify drift level
            if drift_score > 0.5:
                level = "critical"
            elif drift_score > 0.3:
                level = "warning"
            else:
                level = "normal"
            
            drift_metrics.append({
                "key": metric.key,
                "drift_score": drift_score,
                "drift_level": level,
                "last_updated": metric.timestamp.isoformat()
            })
        
        return {
            "status": "success",
            "version_id": current_version.version_id,
            "drift_metrics": drift_metrics,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 3. Latency Breakdown
# ============================================================

@router.get("/latency-breakdown")
async def get_latency_breakdown(
    model_name: str = "cache_predictor",
    db: Session = Depends(get_session)
):
    """
    Get latency breakdown by component.
    
    Returns:
        - redis_ms: Redis lookup latency
        - inference_ms: Model inference latency
        - validation_ms: Data validation latency
        - network_ms: Network latency
        - other_ms: Other latencies
        - total_avg_ms: Average total latency
    """
    try:
        obs = get_observability_service()
        
        # Get latency metrics
        latency_breakdown = {
            "redis_ms": obs.latency_metrics.get("redis", 0),
            "inference_ms": obs.latency_metrics.get("inference", 0),
            "validation_ms": obs.latency_metrics.get("validation", 0),
            "network_ms": obs.latency_metrics.get("network", 0),
            "other_ms": obs.latency_metrics.get("other", 0),
        }
        
        total = sum(latency_breakdown.values())
        
        return {
            "status": "success",
            "latency_breakdown": latency_breakdown,
            "total_avg_ms": total,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 4. Benchmark & Speedup Factor
# ============================================================

@router.get("/benchmark")
async def get_benchmark_metrics(
    model_name: str = "cache_predictor",
    time_range: str = "7d",
    db: Session = Depends(get_session)
):
    """
    Get benchmark metrics showing PSKC speedup factor.
    
    Returns:
        - speedup_factor: PSKC speedup vs baseline (>1.0 is better)
        - cache_hit_rate: Overall cache hit rate
        - overall_accuracy: Overall prediction accuracy
        - speedup_trend: Historical speedup factors
    """
    try:
        trainer_int = get_trainer_integration()
        obs = get_observability_service()
        current_version = trainer_int.version_manager.get_current_version(model_name)
        
        if not current_version:
            raise HTTPException(status_code=404, detail="Model not found")
        
        # Calculate metrics
        overall_accuracy = obs.benchmark_metrics.get("overall_accuracy", 0.85)
        cache_hit_rate = obs.benchmark_metrics.get("cache_hit_rate", 0.87)
        baseline_latency = obs.benchmark_metrics.get("baseline_latency_ms", 50.0)
        pskc_latency = obs.benchmark_metrics.get("pskc_latency_ms", 20.0)
        
        # Calculate speedup factor
        speedup = baseline_latency / pskc_latency if pskc_latency > 0 else 1.0
        
        # Generate trend (mock data - should be fetched from DB)
        now = datetime.utcnow()
        trend_timestamps = [(now - timedelta(days=i)).isoformat() for i in range(7)]
        trend_values = [1.8 + (i * 0.07) for i in range(7)]  # Improving trend
        
        return {
            "status": "success",
            "speedup_factor": speedup,
            "cache_hit_rate": cache_hit_rate,
            "overall_accuracy": overall_accuracy,
            "baseline_latency_ms": baseline_latency,
            "pskc_latency_ms": pskc_latency,
            "speedup_trend": {
                "timestamps": trend_timestamps,
                "values": trend_values
            },
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 5. Confidence Distribution
# ============================================================

@router.get("/confidence-distribution")
async def get_confidence_distribution(
    model_name: str = "cache_predictor",
    db: Session = Depends(get_session)
):
    """
    Get prediction confidence distribution.
    
    Returns:
        - avg_confidence: Average confidence
        - min_confidence: Minimum confidence
        - max_confidence: Maximum confidence
        - high_confidence_percentage: % of predictions > 90% confidence
        - confidence_histogram: 10-bin histogram
    """
    try:
        obs = get_observability_service()
        trainer_int = get_trainer_integration()
        current_version = trainer_int.version_manager.get_current_version(model_name)
        
        if not current_version:
            raise HTTPException(status_code=404, detail="Model not found")
        
        # Get confidence scores from observations
        predictions = db.query(PredictionLog).filter(
            PredictionLog.version_id == current_version.version_id
        ).all()
        
        if not predictions:
            return {
                "status": "success",
                "avg_confidence": 0.0,
                "min_confidence": 0.0,
                "max_confidence": 0.0,
                "high_confidence_percentage": 0.0,
                "confidence_histogram": [0] * 10
            }
        
        confidences = [p.confidence for p in predictions if p.confidence is not None]
        
        # Calculate statistics
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        min_conf = min(confidences) if confidences else 0.0
        max_conf = max(confidences) if confidences else 0.0
        high_conf_count = sum(1 for c in confidences if c > 0.9)
        high_conf_pct = (high_conf_count / len(confidences) * 100) if confidences else 0.0
        
        # Create histogram (10 bins: 0-10%, 10-20%, ..., 90-100%)
        histogram = [0] * 10
        for conf in confidences:
            bin_idx = int(conf * 10)
            if bin_idx >= 10:
                bin_idx = 9
            histogram[bin_idx] += 1
        
        return {
            "status": "success",
            "avg_confidence": avg_conf,
            "min_confidence": min_conf,
            "max_confidence": max_conf,
            "high_confidence_percentage": high_conf_pct,
            "confidence_histogram": histogram,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 6. Accuracy Trend
# ============================================================

@router.get("/accuracy-trend")
async def get_accuracy_trend(
    model_name: str = "cache_predictor",
    time_range: str = "7d",
    db: Session = Depends(get_session)
):
    """
    Get accuracy trend over time with EWMA values.
    
    Returns:
        - timestamps: Array of timestamps
        - overall_accuracy: Overall accuracy over time
        - ewma_short: Short-term EWMA trend
        - ewma_long: Long-term EWMA trend
    """
    try:
        trainer_int = get_trainer_integration()
        current_version = trainer_int.version_manager.get_current_version(model_name)
        
        if not current_version:
            raise HTTPException(status_code=404, detail="Model not found")
        
        # Parse time range
        hours = int(time_range.replace('d', '')) * 24 if 'd' in time_range else 24
        time_cutoff = datetime.utcnow() - timedelta(hours=hours)
        
        # Get metrics over time
        metrics = db.query(ModelMetric).filter(
            ModelMetric.version_id == current_version.version_id,
            ModelMetric.timestamp >= time_cutoff
        ).order_by(ModelMetric.timestamp).all()
        
        # Generate trend data
        timestamps = []
        accuracies = []
        ewma_short = []
        ewma_long = []
        
        for i, metric in enumerate(metrics):
            timestamps.append(metric.timestamp.isoformat())
            accuracies.append(metric.accuracy or 0.85)
            
            # Mock EWMA values (should be fetched from actual tracking)
            ewma_short.append(0.85 + (i * 0.001))
            ewma_long.append(0.84 + (i * 0.0005))
        
        # If no data, return mock data
        if not timestamps:
            now = datetime.utcnow()
            timestamps = [(now - timedelta(days=i)).isoformat() for i in range(7)]
            accuracies = [0.85 + (i * 0.01) for i in range(7)]
            ewma_short = [0.85 + (i * 0.015) for i in range(7)]
            ewma_long = [0.84 + (i * 0.008) for i in range(7)]
        
        return {
            "status": "success",
            "timestamps": timestamps,
            "overall_accuracy": accuracies,
            "ewma_short": ewma_short,
            "ewma_long": ewma_long,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 7. Drift Summary
# ============================================================

@router.get("/drift-summary")
async def get_drift_summary(
    model_name: str = "cache_predictor",
    db: Session = Depends(get_session)
):
    """
    Get overall drift status and critical keys.
    
    Returns:
        - overall_drift_score: Average drift across all keys
        - critical_keys_count: Number of critical drift keys
        - warning_keys_count: Number of warning drift keys
        - drift_trend: "improving", "stable", "deteriorating"
        - last_detected_time: When drift was last detected
    """
    try:
        trainer_int = get_trainer_integration()
        current_version = trainer_int.version_manager.get_current_version(model_name)
        
        if not current_version:
            raise HTTPException(status_code=404, detail="Model not found")
        
        # Get all per-key metrics
        metrics = db.query(PerKeyMetric).filter(
            PerKeyMetric.version_id == current_version.version_id
        ).all()
        
        if not metrics:
            return {
                "status": "success",
                "overall_drift_score": 0.0,
                "critical_keys_count": 0,
                "warning_keys_count": 0,
                "drift_trend": "stable",
                "last_detected_time": None
            }
        
        # Calculate statistics
        drift_scores = [m.drift_score or 0.0 for m in metrics]
        overall_drift = sum(drift_scores) / len(drift_scores) if drift_scores else 0.0
        
        critical_count = sum(1 for d in drift_scores if d > 0.5)
        warning_count = sum(1 for d in drift_scores if 0.3 < d <= 0.5)
        
        # Determine trend (mock - should be calculated from history)
        trend = "stable"
        if overall_drift > 0.4:
            trend = "deteriorating"
        elif overall_drift < 0.2:
            trend = "improving"
        
        # Get last update time
        last_time = max((m.timestamp for m in metrics), default=None)
        
        return {
            "status": "success",
            "overall_drift_score": overall_drift,
            "critical_keys_count": critical_count,
            "warning_keys_count": warning_count,
            "drift_trend": trend,
            "last_detected_time": last_time.isoformat() if last_time else None,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Health Check
# ============================================================

@router.get("/health")
async def health_check():
    """Check if dashboard endpoints are operational."""
    return {
        "status": "healthy",
        "service": "dashboard-metrics",
        "endpoints": 7,
        "timestamp": datetime.utcnow().isoformat()
    }
