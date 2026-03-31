# ============================================================
# PSKC — Pattern Comparison API Routes
# Endpoints for viewing training baseline, live traffic
# patterns, and their divergence comparison.
# ============================================================
import logging
from fastapi import APIRouter, Depends
from typing import Dict, Any

from src.database.connection import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ml/pattern", tags=["Pattern Comparison"])


@router.get("/baseline")
def get_baseline_profile(db=Depends(get_db)) -> Dict[str, Any]:
    """
    Return the most recent training sample profile (the 'baseline')
    for the active model.
    """
    try:
        from src.ml.sample_profiler import SampleProfiler
        from config.settings import settings

        model_name = getattr(settings, "ml_model_name", "pskc_model")
        profile = SampleProfiler.load_latest_profile(model_name, db)
        if profile is None:
            return {"total_samples": 0, "message": "No training baseline available yet"}
        return profile
    except Exception as exc:
        logger.error("Failed to load baseline profile: %s", exc)
        return {"error": str(exc)}


@router.get("/live")
def get_live_pattern() -> Dict[str, Any]:
    """
    Return the current live traffic pattern captured in Redis
    (rolling 1-hour window).
    """
    try:
        tracker = _get_traffic_tracker()
        if tracker is None:
            return {"total_samples": 0, "message": "Traffic tracker not available"}
        return tracker.get_live_pattern()
    except Exception as exc:
        logger.error("Failed to get live pattern: %s", exc)
        return {"error": str(exc)}


@router.get("/comparison")
def get_pattern_comparison(db=Depends(get_db)) -> Dict[str, Any]:
    """
    Compare the live traffic pattern against the training baseline
    and return a divergence report.
    """
    try:
        from src.ml.sample_profiler import SampleProfiler
        from config.settings import settings

        model_name = getattr(settings, "ml_model_name", "pskc_model")
        baseline = SampleProfiler.load_latest_profile(model_name, db)
        if baseline is None:
            return {
                "divergence_score": 0.0,
                "message": "No training baseline — cannot compare",
            }

        tracker = _get_traffic_tracker()
        if tracker is None:
            return {
                "divergence_score": 0.0,
                "message": "Traffic tracker not available",
            }

        live = tracker.get_live_pattern()
        if not live or live.get("total_samples", 0) < 10:
            return {
                "divergence_score": 0.0,
                "message": "Not enough live traffic data to compare",
                "live_samples": live.get("total_samples", 0) if live else 0,
            }

        comparison = SampleProfiler.compare_profiles(baseline, live)
        comparison["baseline_samples"] = baseline.get("total_samples", 0)
        comparison["live_samples"] = live.get("total_samples", 0)
        return comparison
    except Exception as exc:
        logger.error("Failed to compute pattern comparison: %s", exc)
        return {"error": str(exc)}


@router.get("/stats")
def get_tracker_stats() -> Dict[str, Any]:
    """
    Return traffic tracker diagnostics (spike state, RPS baseline, etc.).
    """
    tracker = _get_traffic_tracker()
    if tracker is None:
        return {"available": False}
    stats = tracker.get_stats()
    stats["available"] = True
    return stats


# ------------------------------------------------------------------
# Helper: lazily obtain the global TrafficPatternTracker singleton.
# In the API container this tracker is used only for reading Redis
# data — the ML Worker is the one writing to it.
# ------------------------------------------------------------------

_tracker_instance = None


def _get_traffic_tracker():
    """Get or create a read-only TrafficPatternTracker for the API."""
    global _tracker_instance
    if _tracker_instance is not None:
        return _tracker_instance

    try:
        import redis
        import os
        from src.ml.traffic_pattern_tracker import TrafficPatternTracker

        redis_host = os.environ.get("REDIS_HOST", "redis")
        redis_port = int(os.environ.get("REDIS_PORT", "6379"))
        redis_password = os.environ.get("REDIS_PASSWORD", "pskc_redis_secret")

        client = redis.Redis(
            host=redis_host,
            port=redis_port,
            password=redis_password,
            decode_responses=False,
            socket_connect_timeout=3,
        )
        client.ping()

        _tracker_instance = TrafficPatternTracker(
            redis_client=client,
            ttl_seconds=3600,
        )
        return _tracker_instance
    except Exception as exc:
        logger.warning("Could not initialize traffic tracker for API: %s", exc)
        return None
