import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional
from collections import deque
from threading import Lock

import redis
from redis.exceptions import RedisError

from config.settings import settings

logger = logging.getLogger(__name__)


def _get_setting(name: str, default: Any) -> Any:
    return getattr(settings, name, default)


class RateLimiter:
    """
    Token bucket rate limiter for prefetch operations.
    
    Controls the rate at which prefetch jobs are processed to prevent
    overwhelming the system.
    
    Features:
    - Configurable rate (jobs per second)
    - Burst allowance
    - Thread-safe
    - Adaptive rate limiting based on system load
    """
    
    def __init__(
        self,
        rate: float = 10.0,        # jobs per second
        burst: int = 20,           # max burst allowance
        adaptive: bool = True,      # enable adaptive rate limiting
        increase_threshold: float = 0.3,  # increase rate if idle for this fraction
        decrease_threshold: float = 0.8,  # decrease rate if at capacity for this fraction
    ):
        self._rate = rate
        self._burst = burst
        self._adaptive = adaptive
        self._increase_threshold = increase_threshold
        self._decrease_threshold = decrease_threshold
        
        self._tokens = float(burst)
        self._last_update = time.time()
        self._lock = Lock()
        
        # Adaptive metrics
        self._processed_count = 0
        self._total_processed = 0
        self._last_check = time.time()
        self._capacity_history = deque(maxlen=60)  # 60 seconds of history
        
    @property
    def rate(self) -> float:
        return self._rate
    
    @property
    def burst(self) -> int:
        return self._burst

    def _refill_tokens(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self._last_update
        self._last_update = now
        
        # Add tokens based on rate
        self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
    
    def acquire(self, tokens: int = 1, blocking: bool = False, timeout: float = 5.0) -> bool:
        """
        Try to acquire tokens for processing.
        
        Args:
            tokens: Number of tokens to acquire
            blocking: If True, wait for tokens to become available
            timeout: Maximum time to wait (only if blocking=True)
            
        Returns:
            True if tokens acquired, False otherwise
        """
        with self._lock:
            self._refill_tokens()
            
            if self._tokens >= tokens:
                self._tokens -= tokens
                self._processed_count += 1
                self._total_processed += 1
                return True
            
            if not blocking:
                return False
            
            # Blocking wait for tokens
            start_time = time.time()
            while self._tokens < tokens:
                if time.time() - start_time >= timeout:
                    return False
                # Wait a bit and refill
                time.sleep(0.01)
                self._refill_tokens()
            
            self._tokens -= tokens
            self._processed_count += 1
            self._total_processed += 1
            return True
    
    def record_processed(self, tokens: int = 1) -> None:
        """Record successful processing for adaptive rate limiting."""
        with self._lock:
            self._processed_count += tokens
            self._total_processed += tokens
    
    def record_skipped(self) -> None:
        """Record skipped processing for adaptive rate limiting."""
        pass  # Could track skipped for adaptive logic
    
    def get_stats(self) -> Dict[str, Any]:
        """Get rate limiter statistics."""
        with self._lock:
            # Record capacity for last check period
            now = time.time()
            elapsed = now - self._last_check
            if elapsed >= 1.0:  # Update every second
                capacity = self._processed_count / (self._rate * elapsed) if elapsed > 0 else 0
                self._capacity_history.append(capacity)
                self._processed_count = 0
                self._last_check = now
            
            avg_capacity = sum(self._capacity_history) / len(self._capacity_history) if self._capacity_history else 0
            
            return {
                "rate": round(self._rate, 2),
                "burst": self._burst,
                "current_tokens": round(self._tokens, 2),
                "adaptive": self._adaptive,
                "avg_capacity_percent": round(avg_capacity * 100, 1),
                "total_processed": self._total_processed,
            }
    
    def set_rate(self, rate: float) -> None:
        """Manually set the rate."""
        with self._lock:
            self._rate = max(0.1, min(1000.0, rate))
    
    def adjust_rate(self, factor: float) -> None:
        """Adjust rate by a multiplicative factor."""
        with self._lock:
            new_rate = self._rate * factor
            self._rate = max(0.1, min(1000.0, new_rate))
            logger.info(f"Rate limiter adjusted: rate={self._rate:.2f}")
    
    def adaptive_adjust(self) -> None:
        """
        Automatically adjust rate based on recent capacity.
        
        Called periodically to adapt to system load.
        """
        if not self._adaptive:
            return
            
        with self._lock:
            if not self._capacity_history:
                return
            
            avg_capacity = sum(self._capacity_history) / len(self._capacity_history)
            
            # If consistently running below threshold, increase rate
            if avg_capacity < self._increase_threshold:
                self._rate = min(1000.0, self._rate * 1.2)
                logger.info(f"Rate increased: rate={self._rate:.2f}, capacity={avg_capacity:.1%}")
            # If consistently at capacity, decrease rate
            elif avg_capacity > self._decrease_threshold:
                self._rate = max(0.1, self._rate * 0.8)
                logger.info(f"Rate decreased: rate={self._rate:.2f}, capacity={avg_capacity:.1%}")


class PrefetchQueue:
    """Redis-backed queue for async prefetch jobs with rate limiting and replay support."""

    def __init__(
        self,
        redis_url: Optional[str] = None,
        queue_key: Optional[str] = None,
    ):
        effective_redis_url = redis_url or _get_setting("redis_url", "redis://localhost:6379/0")
        effective_queue_key = queue_key or _get_setting("prefetch_queue_key", "pskc:prefetch:jobs")
        effective_connect_timeout = float(_get_setting("redis_socket_connect_timeout_seconds", 0.5))
        effective_socket_timeout = float(_get_setting("redis_socket_timeout_seconds", 0.5))
        self._failure_backoff_seconds = float(_get_setting("redis_failure_backoff_seconds", 30.0))
        self._disabled_until = 0.0
        self._queue_key = str(effective_queue_key)
        self._retry_key = f"{self._queue_key}:retry"
        self._dlq_key = f"{self._queue_key}:dlq"
        self._stats_key = f"{self._queue_key}:stats"
        self._replay_key = f"{self._queue_key}:replay"  # Track replay history
        self._worker_key = f"{self._queue_key}:workers"
        self._worker_events_key = f"{self._queue_key}:worker_events"
        self._client = redis.Redis.from_url(
            effective_redis_url,
            decode_responses=True,
            socket_connect_timeout=effective_connect_timeout,
            socket_timeout=effective_socket_timeout,
            retry_on_timeout=False,
        )
        
        # Rate limiter initialization
        self._rate_limiter = RateLimiter(
            rate=float(_get_setting("prefetch_rate_limit_rps", 10.0)),
            burst=int(_get_setting("prefetch_rate_limit_burst", 20)),
            adaptive=bool(_get_setting("prefetch_rate_adaptive", True)),
        )
        
        logger.info("PrefetchQueue initialized: key=%s", self._queue_key)

    def _is_available(self) -> bool:
        return time.time() >= self._disabled_until

    def _record_failure(self, operation: str, exc: Exception) -> None:
        self._disabled_until = time.time() + self._failure_backoff_seconds
        logger.warning("Prefetch queue %s failed: %s", operation, exc)

    def _serialize(self, payload: Dict[str, Any]) -> str:
        return json.dumps(payload, sort_keys=True)

    def _deserialize(self, raw_payload: str) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            logger.warning("Dropped invalid prefetch job payload: %s", exc)
            return None

    def _increment_stat(self, name: str, amount: int = 1) -> None:
        if not self._is_available():
            return
        try:
            self._client.hincrby(self._stats_key, name, amount)
        except RedisError as exc:
            self._record_failure(f"stat:{name}", exc)

    def enqueue(self, payload: Dict[str, Any]) -> bool:
        if not self._is_available():
            return False
        try:
            job = dict(payload)
            job.setdefault("job_id", str(uuid.uuid4()))
            job.setdefault("attempt", 0)
            job.setdefault("created_at", time.time())
            self._client.lpush(self._queue_key, self._serialize(job))
            self._increment_stat("enqueued_total")
            return True
        except (RedisError, TypeError, ValueError) as exc:
            self._record_failure("enqueue", exc)
            return False

    def promote_due_retries(self, limit: int = 50) -> int:
        if not self._is_available():
            return 0
        try:
            due_items = self._client.zrangebyscore(self._retry_key, min=0, max=time.time(), start=0, num=limit)
        except RedisError as exc:
            self._record_failure("inspect_retry", exc)
            return 0

        if not due_items:
            return 0

        moved = 0
        pipeline = self._client.pipeline()
        for item in due_items:
            pipeline.zrem(self._retry_key, item)
            pipeline.lpush(self._queue_key, item)
            moved += 1

        try:
            pipeline.execute()
            self._increment_stat("promoted_total", moved)
        except RedisError as exc:
            self._record_failure("promote_retry", exc)
            return 0

        return moved

    def dequeue(self, timeout: Optional[int] = None) -> Optional[Dict[str, Any]]:
        if not self._is_available():
            return None
        
        # Apply rate limiting before processing
        if not self._rate_limiter.acquire(blocking=False):
            # Rate limited - try again later
            self._increment_stat("rate_limited")
            return None
        
        effective_timeout = (
            timeout if timeout is not None else int(_get_setting("prefetch_worker_block_timeout", 5))
        )
        self.promote_due_retries()

        try:
            item = self._client.brpop(self._queue_key, timeout=effective_timeout)
        except (TimeoutError, redis.exceptions.TimeoutError):
            # brpop returned nothing because the queue is empty — this is normal,
            # NOT a Redis failure.  Do not engage the backoff circuit-breaker.
            return None
        except RedisError as exc:
            self._record_failure("dequeue", exc)
            return None

        if item is None:
            return None

        _, raw_payload = item
        payload = self._deserialize(raw_payload)
        if payload is not None:
            self._increment_stat("dequeued_total")
        return payload

    def mark_completed(self, payload: Dict[str, Any]) -> None:
        self._increment_stat("completed_total")

    def retry(self, payload: Dict[str, Any], error: str, candidates: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        next_attempt = int(payload.get("attempt", 0)) + 1
        job = dict(payload)
        job["attempt"] = next_attempt
        job["last_error"] = error
        job["last_failed_at"] = time.time()
        if candidates is not None:
            job["candidates"] = candidates

        max_retries = int(_get_setting("prefetch_max_retries", 3))
        retry_backoff_seconds = int(_get_setting("prefetch_retry_backoff_seconds", 5))

        if next_attempt > max_retries:
            self.move_to_dlq(job, error=error)
            return {"status": "dlq", "attempt": next_attempt}

        ready_at = time.time() + retry_backoff_seconds * (2 ** (next_attempt - 1))
        try:
            self._client.zadd(self._retry_key, {self._serialize(job): ready_at})
            self._increment_stat("retried_total")
            return {"status": "retried", "attempt": next_attempt, "ready_at": ready_at}
        except RedisError as exc:
            self._record_failure("retry", exc)
            self.move_to_dlq(job, error=f"{error}; retry_enqueue_failed={exc}")
            return {"status": "dlq", "attempt": next_attempt}

    def move_to_dlq(self, payload: Dict[str, Any], error: str) -> bool:
        if not self._is_available():
            return False
        job = dict(payload)
        job["dlq_at"] = time.time()
        job["last_error"] = error

        try:
            self._client.lpush(self._dlq_key, self._serialize(job))
            self._increment_stat("dlq_total")
            return True
        except RedisError as exc:
            self._record_failure("move_to_dlq", exc)
            return False

    def get_dlq(self, limit: int = 20) -> List[Dict[str, Any]]:
        if not self._is_available():
            return []
        try:
            items = self._client.lrange(self._dlq_key, 0, max(0, limit - 1))
        except RedisError as exc:
            self._record_failure("read_dlq", exc)
            return []

        jobs: List[Dict[str, Any]] = []
        for item in items:
            payload = self._deserialize(item)
            if payload is not None:
                jobs.append(payload)
        return jobs

    # ----------------------------------------------------------
    # Replay Functionality
    # ----------------------------------------------------------
    
    def replay_from_dlq(self, job_id: Optional[str] = None, limit: int = 10) -> Dict[str, Any]:
        """
        Replay jobs from DLQ back to the main queue.
        
        Args:
            job_id: Specific job ID to replay, or None for all
            limit: Maximum number of jobs to replay
            
        Returns:
            Result dict with replay count and details
        """
        if not self._is_available():
            return {"success": False, "reason": "unavailable"}
        
        try:
            if job_id:
                # Replay specific job
                items = self._client.lrange(self._dlq_key, 0, -1)
                target_job = None
                for item in items:
                    payload = self._deserialize(item)
                    if payload and payload.get("job_id") == job_id:
                        target_job = payload
                        break
                
                if target_job is None:
                    return {"success": False, "reason": "job_not_found", "job_id": job_id}
                
                # Remove from DLQ and re-enqueue
                self._remove_from_dlq(job_id)
                target_job["replayed_at"] = time.time()
                target_job["replay_count"] = target_job.get("replay_count", 0) + 1
                self.enqueue(target_job)
                
                self._increment_stat("replayed_total")
                self._track_replay(target_job)
                
                return {
                    "success": True,
                    "replayed_count": 1,
                    "job_id": job_id,
                }
            else:
                # Replay multiple jobs
                items = self._client.lrange(self._dlq_key, 0, min(limit - 1, 99))
                replayed = 0
                
                for item in items[:limit]:
                    payload = self._deserialize(item)
                    if payload:
                        self._remove_from_dlq(payload.get("job_id", ""))
                        payload["replayed_at"] = time.time()
                        payload["replay_count"] = payload.get("replay_count", 0) + 1
                        
                        if self.enqueue(payload):
                            replayed += 1
                
                self._increment_stat("replayed_total", replayed)
                
                return {
                    "success": True,
                    "replayed_count": replayed,
                }
                
        except RedisError as exc:
            self._record_failure("replay_dlq", exc)
            return {"success": False, "reason": str(exc)}
    
    def _remove_from_dlq(self, job_id: str) -> bool:
        """Remove a specific job from DLQ."""
        try:
            items = self._client.lrange(self._dlq_key, 0, -1)
            for i, item in enumerate(items):
                payload = self._deserialize(item)
                if payload and payload.get("job_id") == job_id:
                    self._client.lrem(self._dlq_key, 1, item)
                    return True
            return False
        except RedisError:
            return False
    
    def _track_replay(self, job: Dict[str, Any]) -> None:
        """Track replay history for analysis."""
        try:
            replay_entry = {
                "job_id": job.get("job_id"),
                "original_attempt": job.get("attempt", 0),
                "replay_count": job.get("replay_count", 1),
                "replayed_at": time.time(),
            }
            self._client.lpush(self._replay_key, self._serialize(replay_entry))
            # Keep only last 1000 replay entries
            self._client.ltrim(self._replay_key, 0, 999)
        except RedisError:
            pass  # Non-critical
    
    def get_replay_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get replay history."""
        if not self._is_available():
            return []
        try:
            items = self._client.lrange(self._replay_key, 0, max(0, limit - 1))
            return [self._deserialize(item) for item in items if self._deserialize(item)]
        except RedisError:
            return []

    # ----------------------------------------------------------
    # Worker Heartbeat / Evidence
    # ----------------------------------------------------------

    def record_worker_heartbeat(
        self,
        worker_id: str,
        status: str = "idle",
        details: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if not self._is_available():
            return False
        heartbeat = {
            "worker_id": worker_id,
            "status": status,
            "last_seen": time.time(),
            "details": details or {},
        }
        try:
            self._client.hset(self._worker_key, worker_id, self._serialize(heartbeat))
            return True
        except RedisError as exc:
            self._record_failure("worker_heartbeat", exc)
            return False

    def get_worker_status(self, stale_after_seconds: int = 30) -> List[Dict[str, Any]]:
        if not self._is_available():
            return []
        try:
            raw_workers = self._client.hgetall(self._worker_key)
        except RedisError as exc:
            self._record_failure("worker_status", exc)
            return []

        now = time.time()
        workers: List[Dict[str, Any]] = []
        for worker_id, raw_payload in raw_workers.items():
            payload = self._deserialize(raw_payload)
            if payload is None:
                continue
            last_seen = float(payload.get("last_seen", 0) or 0)
            payload["worker_id"] = worker_id
            payload["active"] = (now - last_seen) <= stale_after_seconds if last_seen else False
            workers.append(payload)

        workers.sort(key=lambda item: item.get("last_seen", 0), reverse=True)
        return workers

    def record_worker_event(
        self,
        worker_id: str,
        job: Dict[str, Any],
        result: Dict[str, Any],
    ) -> None:
        if not self._is_available():
            return
        event = {
            "worker_id": worker_id,
            "timestamp": time.time(),
            "job_id": job.get("job_id"),
            "service_id": job.get("service_id"),
            "source_key_id": job.get("source_key_id"),
            "status": result.get("status"),
            "prefetched_count": result.get("prefetched_count", 0),
            "predictions_considered": result.get("predictions_considered", 0),
            "prefetched_keys": list(result.get("prefetched_keys", [])[:10]),
        }
        try:
            self._client.lpush(self._worker_events_key, self._serialize(event))
            self._client.ltrim(self._worker_events_key, 0, 99)
        except RedisError as exc:
            self._record_failure("worker_event", exc)

    def get_recent_worker_events(self, limit: int = 20) -> List[Dict[str, Any]]:
        if not self._is_available():
            return []
        try:
            items = self._client.lrange(self._worker_events_key, 0, max(0, limit - 1))
        except RedisError as exc:
            self._record_failure("worker_events", exc)
            return []

        events: List[Dict[str, Any]] = []
        for item in items:
            payload = self._deserialize(item)
            if payload is not None:
                events.append(payload)
        return events
    
    def replay_from_retry(self, limit: int = 50) -> int:
        """
        Manually promote jobs from retry queue to main queue.
        Useful for draining the retry queue during maintenance.
        """
        if not self._is_available():
            return 0
        
        try:
            # Get all retry jobs (regardless of scheduled time)
            due_items = self._client.zrangebyscore(self._retry_key, min=0, max=time.time() + 3600, start=0, num=limit)
            
            if not due_items:
                return 0
            
            moved = 0
            pipeline = self._client.pipeline()
            for item in due_items:
                pipeline.zrem(self._retry_key, item)
                pipeline.lpush(self._queue_key, item)
                moved += 1
            
            pipeline.execute()
            self._increment_stat("manual_replay_total", moved)
            
            return moved
            
        except RedisError as exc:
            self._record_failure("manual_replay_retry", exc)
            return 0
    
    def clear_dlq(self) -> Dict[str, Any]:
        """Clear all jobs from DLQ. Use with caution!"""
        if not self._is_available():
            return {"success": False, "reason": "unavailable"}
        
        try:
            dlq_length = int(self._client.llen(self._dlq_key))
            self._client.delete(self._dlq_key)
            self._increment_stat("dlq_cleared", dlq_length)
            
            return {
                "success": True,
                "cleared_count": dlq_length,
            }
        except RedisError as exc:
            self._record_failure("clear_dlq", exc)
            return {"success": False, "reason": str(exc)}

    def get_stats(self) -> Dict[str, Any]:
        if not self._is_available():
            return {
                "available": False,
                "queue_length": 0,
                "retry_length": 0,
                "dlq_length": 0,
                "stats": {},
            }
        try:
            queue_length = int(self._client.llen(self._queue_key))
            retry_length = int(self._client.zcard(self._retry_key))
            dlq_length = int(self._client.llen(self._dlq_key))
            raw_stats = self._client.hgetall(self._stats_key)
        except RedisError as exc:
            self._record_failure("stats", exc)
            return {
                "available": False,
                "queue_length": 0,
                "retry_length": 0,
                "dlq_length": 0,
                "stats": {},
            }

        stats = {key: int(value) for key, value in raw_stats.items()}
        return {
            "available": True,
            "queue_key": self._queue_key,
            "queue_length": queue_length,
            "retry_length": retry_length,
            "dlq_length": dlq_length,
            "max_retries": int(_get_setting("prefetch_max_retries", 3)),
            "retry_backoff_seconds": int(_get_setting("prefetch_retry_backoff_seconds", 5)),
            "stats": stats,
            "rate_limiter": self._rate_limiter.get_stats(),
            "workers": self.get_worker_status(),
            "recent_worker_events": self.get_recent_worker_events(limit=10),
        }

    def ping(self) -> bool:
        if not self._is_available():
            return False
        try:
            return bool(self._client.ping())
        except RedisError as exc:
            self._record_failure("ping", exc)
            return False

    # ----------------------------------------------------------
    # Rate Limiter Control
    # ----------------------------------------------------------
    
    def set_rate_limit(self, rate: float) -> Dict[str, Any]:
        """Set the rate limit (jobs per second)."""
        self._rate_limiter.set_rate(rate)
        return {"success": True, "rate": rate}
    
    def adjust_rate_limit(self, factor: float) -> Dict[str, Any]:
        """Adjust rate by multiplicative factor."""
        old_rate = self._rate_limiter.rate
        self._rate_limiter.adjust_rate(factor)
        return {
            "success": True,
            "old_rate": old_rate,
            "new_rate": self._rate_limiter.rate,
        }
    
    def get_rate_limit_stats(self) -> Dict[str, Any]:
        """Get detailed rate limiter statistics."""
        return self._rate_limiter.get_stats()
    
    def trigger_adaptive_adjust(self) -> Dict[str, Any]:
        """Trigger adaptive rate adjustment."""
        self._rate_limiter.adaptive_adjust()
        return {
            "success": True,
            "new_rate": self._rate_limiter.rate,
        }

    def close(self) -> None:
        try:
            self._client.close()
        except RedisError as exc:
            self._record_failure("close", exc)


_prefetch_queue: Optional[PrefetchQueue] = None


def get_prefetch_queue() -> PrefetchQueue:
    global _prefetch_queue
    if _prefetch_queue is None:
        _prefetch_queue = PrefetchQueue()
    return _prefetch_queue
