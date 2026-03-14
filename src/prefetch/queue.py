import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

import redis
from redis.exceptions import RedisError

from config.settings import settings

logger = logging.getLogger(__name__)


def _get_setting(name: str, default: Any) -> Any:
    return getattr(settings, name, default)


class PrefetchQueue:
    """Redis-backed queue for async prefetch jobs."""

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
        self._client = redis.Redis.from_url(
            effective_redis_url,
            decode_responses=True,
            socket_connect_timeout=effective_connect_timeout,
            socket_timeout=effective_socket_timeout,
            retry_on_timeout=False,
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
        effective_timeout = (
            timeout if timeout is not None else int(_get_setting("prefetch_worker_block_timeout", 5))
        )
        self.promote_due_retries()

        try:
            item = self._client.brpop(self._queue_key, timeout=effective_timeout)
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
        }

    def ping(self) -> bool:
        if not self._is_available():
            return False
        try:
            return bool(self._client.ping())
        except RedisError as exc:
            self._record_failure("ping", exc)
            return False

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
