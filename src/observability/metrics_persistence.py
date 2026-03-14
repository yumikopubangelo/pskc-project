# ============================================================
# PSKC — Metrics Persistence Service
# ============================================================
#
# Provides persistent metrics storage using Redis.
# Metrics survive process restarts and enable historical analysis.
#
# Metrics are stored with timestamps for time-series analysis:
#   pskc:metrics:requests - Counter with timestamps
#   pskc:metrics:cache_hits - Counter
#   pskc:metrics:cache_misses - Counter  
#   pskc:metrics:latency - List of latency samples
#   pskc:metrics:active_keys - Gauge
#
# ============================================================

import json
import logging
import time
from typing import Any, Dict, List, Optional
from collections import deque

import redis
from redis.exceptions import RedisError

from config.settings import settings

logger = logging.getLogger(__name__)


def _get_setting(name: str, default: Any) -> Any:
    return getattr(settings, name, default)


class MetricsPersistence:
    """Redis-backed metrics persistence for historical analysis."""
    
    # Key prefixes
    METRICS_PREFIX = "pskc:metrics"
    REQUESTS_KEY = f"{METRICS_PREFIX}:requests"
    CACHE_HITS_KEY = f"{METRICS_PREFIX}:cache_hits"
    CACHE_MISSES_KEY = f"{METRICS_PREFIX}:cache_misses"
    LATENCY_KEY = f"{METRICS_PREFIX}:latency"
    ACTIVE_KEYS_KEY = f"{METRICS_PREFIX}:active_keys"
    TIMESTAMP_KEY = f"{METRICS_PREFIX}:last_updated"
    
    # Settings
    MAX_LATENCY_SAMPLES = 10000  # Keep last 10k latency samples
    
    def __init__(
        self,
        redis_url: Optional[str] = None,
        retention_seconds: int = 86400,  # 24 hours default
    ):
        effective_redis_url = redis_url or _get_setting("redis_url", "redis://localhost:6379/0")
        effective_connect_timeout = float(_get_setting("redis_socket_connect_timeout_seconds", 0.5))
        effective_socket_timeout = float(_get_setting("redis_socket_timeout_seconds", 0.5))
        
        self._retention_seconds = retention_seconds
        self._disabled_until = 0.0
        self._failure_backoff_seconds = float(_get_setting("redis_failure_backoff_seconds", 30.0))
        
        self._client = redis.Redis.from_url(
            effective_redis_url,
            decode_responses=False,  # Binary for performance
            socket_connect_timeout=effective_connect_timeout,
            socket_timeout=effective_socket_timeout,
            retry_on_timeout=False,
        )
        logger.info("MetricsPersistence initialized with retention=%ds", self._retention_seconds)
    
    def _is_available(self) -> bool:
        return time.time() >= self._disabled_until
    
    def _record_failure(self, operation: str, exc: Exception) -> None:
        self._disabled_until = time.time() + self._failure_backoff_seconds
        logger.warning("MetricsPersistence %s failed: %s", operation, exc)
    
    def _is_key_expired(self, timestamp: float) -> bool:
        """Check if a timestamp is older than retention period."""
        return (time.time() - timestamp) > self._retention_seconds
    
    def ping(self) -> bool:
        """Check if Redis is available."""
        if not self._is_available():
            return False
        try:
            return bool(self._client.ping())
        except RedisError as exc:
            self._record_failure("ping", exc)
            return False
    
    def record_request(self, cache_hit: bool, latency_ms: float, key_id: str) -> None:
        """Record a request with its outcome and latency."""
        if not self._is_available():
            return
        
        timestamp = time.time()
        
        try:
            pipe = self._client.pipeline()
            
            # Increment request counter with timestamp
            # Use sorted set for time-series: member is timestamp, score is timestamp
            pipe.zadd(self.REQUESTS_KEY, {json.dumps({"ts": timestamp, "hit": cache_hit}): timestamp})
            
            # Increment cache hits or misses
            if cache_hit:
                pipe.incr(self.CACHE_HITS_KEY)
            else:
                pipe.incr(self.CACHE_MISSES_KEY)
            
            # Store latency sample
            pipe.zadd(self.LATENCY_KEY, {json.dumps({"ts": timestamp, "latency": latency_ms}): timestamp})
            
            # Trim old latency samples
            pipe.zremrangebyrank(self.LATENCY_KEY, 0, -(self.MAX_LATENCY_SAMPLES + 1))
            
            # Update timestamp
            pipe.set(self.TIMESTAMP_KEY, str(timestamp), ex=self._retention_seconds)
            
            pipe.execute()
            
        except RedisError as exc:
            self._record_failure("record_request", exc)
    
    def record_active_keys(self, keys: List[str]) -> None:
        """Record the current set of active keys."""
        if not self._is_available():
            return
        
        timestamp = time.time()
        
        try:
            pipe = self._client.pipeline()
            
            # Store active keys as a sorted set with timestamp
            for key in keys:
                pipe.sadd(self.ACTIVE_KEYS_KEY, key)
            
            pipe.set(f"{self.ACTIVE_KEYS_KEY}:updated", str(timestamp), ex=self._retention_seconds)
            
            pipe.execute()
            
        except RedisError as exc:
            self._record_failure("record_active_keys", exc)
    
    def get_cache_hit_rate(self, window_seconds: Optional[int] = None) -> Dict[str, Any]:
        """Calculate cache hit rate over a time window."""
        if not self._is_available():
            return {"hit_rate": 0.0, "hits": 0, "misses": 0, "window_seconds": window_seconds or 0}
        
        window = window_seconds or 3600  # Default 1 hour
        cutoff = time.time() - window
        
        try:
            # Get all hits
            hits = int(self._client.get(self.CACHE_HITS_KEY) or 0)
            misses = int(self._client.get(self.CACHE_MISSES_KEY) or 0)
            
            total = hits + misses
            hit_rate = hits / total if total > 0 else 0.0
            
            return {
                "hit_rate": hit_rate,
                "hits": hits,
                "misses": misses,
                "total": total,
                "window_seconds": window,
            }
            
        except RedisError as exc:
            self._record_failure("get_cache_hit_rate", exc)
            return {"hit_rate": 0.0, "hits": 0, "misses": 0, "error": str(exc)}
    
    def get_latency_stats(self, window_seconds: Optional[int] = None) -> Dict[str, Any]:
        """Get latency statistics over a time window."""
        if not self._is_available():
            return {"avg_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "count": 0}
        
        window = window_seconds or 3600
        cutoff = time.time() - window
        
        try:
            # Get latency samples in window
            samples_raw = self._client.zrangebyscore(
                self.LATENCY_KEY, 
                min=cutoff, 
                max="+inf"
            )
            
            if not samples_raw:
                return {"avg_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "count": 0}
            
            # Parse samples
            latencies = []
            for sample in samples_raw:
                try:
                    data = json.loads(sample)
                    latencies.append(float(data.get("latency", 0)))
                except (json.JSONDecodeError, TypeError):
                    continue
            
            if not latencies:
                return {"avg_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "count": 0}
            
            # Calculate percentiles
            sorted_latencies = sorted(latencies)
            n = len(sorted_latencies)
            
            def percentile(p: float) -> float:
                idx = int(n * p)
                return sorted_latencies[min(idx, n - 1)]
            
            return {
                "avg_ms": sum(latencies) / n,
                "p50_ms": percentile(0.50),
                "p95_ms": percentile(0.95),
                "p99_ms": percentile(0.99),
                "min_ms": min(latencies),
                "max_ms": max(latencies),
                "count": n,
            }
            
        except RedisError as exc:
            self._record_failure("get_latency_stats", exc)
            return {"avg_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "error": str(exc)}
    
    def get_request_count(self) -> int:
        """Get total request count."""
        if not self._is_available():
            return 0
        
        try:
            # Get count from sorted set
            count = self._client.zcard(self.REQUESTS_KEY)
            return int(count)
        except RedisError as exc:
            self._record_failure("get_request_count", exc)
            return 0
    
    def get_last_updated(self) -> Optional[float]:
        """Get timestamp of last metrics update."""
        if not self._is_available():
            return None
        
        try:
            ts = self._client.get(self.TIMESTAMP_KEY)
            return float(ts) if ts else None
        except RedisError:
            return None
    
    def cleanup_old_metrics(self) -> Dict[str, int]:
        """Remove metrics older than retention period."""
        if not self._is_available():
            return {"cleaned": 0}
        
        cutoff = time.time() - self._retention_seconds
        cleaned = 0
        
        try:
            # Clean old requests
            cleaned += self._client.zremrangebyscore(self.REQUESTS_KEY, min="-inf", max=cutoff)
            
            # Clean old latency samples
            cleaned += self._client.zremrangebyscore(self.LATENCY_KEY, min="-inf", max=cutoff)
            
            logger.info("Cleaned %d old metric entries", cleaned)
            return {"cleaned": cleaned}
            
        except RedisError as exc:
            self._record_failure("cleanup_old_metrics", exc)
            return {"cleaned": 0, "error": str(exc)}
    
    def close(self) -> None:
        """Close Redis connection."""
        try:
            self._client.close()
        except RedisError as exc:
            logger.warning("Error closing metrics persistence: %s", exc)


# Global instance
_metrics_persistence: Optional[MetricsPersistence] = None


def get_metrics_persistence() -> Optional[MetricsPersistence]:
    """Get or create the global metrics persistence instance."""
    global _metrics_persistence
    
    if _metrics_persistence is None:
        try:
            _metrics_persistence = MetricsPersistence()
        except Exception as e:
            logger.warning("Failed to initialize metrics persistence: %s", e)
            return None
    
    return _metrics_persistence


def is_metrics_available() -> bool:
    """Check if metrics persistence is available."""
    mp = get_metrics_persistence()
    return mp is not None and mp.ping()
