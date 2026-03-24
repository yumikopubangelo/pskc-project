# ============================================================
# Routes Prefetch & Cache Management Endpoints Module
# ============================================================
import logging
from typing import Optional
from fastapi import APIRouter, Query, status, HTTPException
from src.prefetch.queue import get_prefetch_queue

logger = logging.getLogger(__name__)


def create_prefetch_router() -> APIRouter:
    """Create and return the prefetch management router"""
    router = APIRouter(prefix="/prefetch", tags=["prefetch"])

    @router.get("/dlq")
    async def get_prefetch_dlq(limit: int = 20):
        """Inspect the latest dead-lettered prefetch jobs."""
        from src.api.ml_service import get_prefetch_dlq_payload
        return get_prefetch_dlq_payload(limit=limit)

    @router.post("/dlq/replay")
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

    @router.post("/retry/replay")
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

    @router.delete("/dlq")
    async def clear_prefetch_dlq():
        """Clear all jobs from DLQ. Use with caution!"""
        queue = get_prefetch_queue()
        return queue.clear_dlq()

    @router.get("/rate-limit")
    async def get_rate_limit_stats():
        """Get rate limiter statistics."""
        queue = get_prefetch_queue()
        return queue.get_rate_limit_stats()

    @router.post("/rate-limit/adjust")
    async def adjust_rate_limit(
        factor: float = Query(default=1.5, ge=0.1, le=10.0),
    ):
        """
        Adjust rate limit by multiplicative factor.
        
        Example: factor=1.5 increases rate by 50%, factor=0.5 decreases by 50%
        """
        queue = get_prefetch_queue()
        return queue.adjust_rate_limit(factor)

    @router.post("/rate-limit/set")
    async def set_rate_limit(
        rate: float = Query(default=10.0, ge=0.1, le=1000.0),
    ):
        """Set the rate limit to a specific value (jobs per second)."""
        queue = get_prefetch_queue()
        return queue.set_rate_limit(rate)

    @router.post("/rate-limit/adaptive")
    async def trigger_adaptive_rate():
        """Trigger adaptive rate adjustment based on recent capacity."""
        queue = get_prefetch_queue()
        return queue.trigger_adaptive_adjust()

    @router.get("/replay-history")
    async def get_replay_history(limit: int = 20):
        """Get replay history."""
        queue = get_prefetch_queue()
        return {"history": queue.get_replay_history(limit=limit)}

    return router
