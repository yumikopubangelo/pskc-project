# ============================================================
# PSKC — Data Collector Module
# Collect key access history for ML training
# ============================================================
import time
import threading
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict, deque
from datetime import datetime, timedelta
import logging
import json
import os

logger = logging.getLogger(__name__)


# Redis client for shared storage
_redis_client = None


def _get_redis_client():
    """Get Redis client for shared storage"""
    global _redis_client
    if _redis_client is None:
        try:
            import redis
            redis_host = os.environ.get('REDIS_HOST', 'redis')
            redis_port = int(os.environ.get('REDIS_PORT', '6379'))
            redis_db = int(os.environ.get('REDIS_DB', '0'))
            redis_password = os.environ.get('REDIS_PASSWORD', 'pskc_redis_secret')
            _redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                password=redis_password,
                decode_responses=False,
                socket_connect_timeout=5,
            )
            _redis_client.ping()
            logger.info("DataCollector: Connected to Redis for shared storage")
        except Exception as e:
            logger.warning(f"DataCollector: Redis not available: {e}. Using in-memory only.")
            _redis_client = False  # Mark as unavailable
    return _redis_client if _redis_client else None


@dataclass
class AccessEvent:
    """Single key access event"""
    key_id: str
    service_id: str
    timestamp: float
    access_type: str = "read"  # read, write, delete
    latency_ms: float = 0.0
    cache_hit: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KeyAccessStats:
    """Aggregated statistics for a key"""
    key_id: str
    total_accesses: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    avg_latency_ms: float = 0.0
    first_access: float = field(default_factory=time.time)
    last_access: float = field(default_factory=time.time)
    access_by_service: Dict[str, int] = field(default_factory=dict)
    hourly_access_counts: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    
    @property
    def cache_hit_rate(self) -> float:
        if self.total_accesses == 0:
            return 0.0
        return self.cache_hits / self.total_accesses


class DataCollector:
    """
    Collects and aggregates key access patterns.
    Provides data for ML feature engineering and training.
    Uses Redis for shared storage between processes.
    """
    
    REDIS_KEY_PREFIX = "pskc:ml:events"
    REDIS_KEY_STATS = "pskc:ml:collector_stats"
    
    def __init__(
        self,
        max_events: int = None,
        window_seconds: int = None
    ):
        # Use config defaults if not provided
        from config.settings import settings
        max_events = max_events if max_events is not None else settings.ml_collector_max_events
        window_seconds = window_seconds if window_seconds is not None else settings.ml_collector_window_seconds
        
        self._max_events = max_events
        self._window_seconds = window_seconds
        
        # Historical stats cleanup
        self._historical_stats_ttl_seconds = settings.ml_collector_historical_stats_ttl_hours * 3600
        self._historical_stats_max_entries = settings.ml_collector_historical_stats_max_entries
        self._last_stats_cleanup = time.time()
        
        # Event storage
        self._events: deque = deque(maxlen=max_events)
        self._lock = threading.RLock()
        
        # Aggregated statistics
        self._key_stats: Dict[str, KeyAccessStats] = {}
        
        # Time windows for different time scales
        self._recent_events: deque = deque(maxlen=25000)  # ~last few hours
        self._historical_stats: Dict[str, List[float]] = defaultdict(list)
        
        # Redis for shared storage
        self._redis = _get_redis_client()
        
        # Load existing events from Redis
        self._load_from_redis()
        
        redis_status = "enabled" if self._redis else "disabled"
        logger.info(f"DataCollector initialized: max_events={max_events}, window={window_seconds}s, redis={redis_status}")
    
    def record_access(
        self,
        key_id: str,
        service_id: str,
        access_type: str = "read",
        latency_ms: float = 0.0,
        cache_hit: bool = False,
        timestamp: float = None,
        **metadata
    ):
        """
        Record a key access event with input validation.
        
        Args:
            key_id: Identifier for the accessed key (required, non-empty)
            service_id: Service making the request (default: "default")
            access_type: "read", "write", or "delete" (default: "read")
            latency_ms: Request latency in milliseconds (must be >= 0)
            cache_hit: Whether access was served from cache
            timestamp: Unix timestamp (defaults to current time)
            **metadata: Additional event metadata
            
        Raises:
            ValueError: If input validation fails
        """
        # Input validation (Issue #48)
        if not key_id or not isinstance(key_id, str):
            raise ValueError("key_id must be a non-empty string")
        
        if latency_ms < 0:
            logger.warning(f"Invalid latency_ms ({latency_ms}) for key {key_id}, setting to 0")
            latency_ms = 0.0
        
        if not isinstance(cache_hit, bool):
            cache_hit = bool(cache_hit)
        
        if access_type not in ("read", "write", "delete"):
            logger.warning(f"Invalid access_type '{access_type}', defaulting to 'read'")
            access_type = "read"
        
        # Use provided timestamp or current time
        event_timestamp = timestamp if timestamp is not None else time.time()
        if event_timestamp <= 0:
            event_timestamp = time.time()
        
        event = AccessEvent(
            key_id=key_id,
            service_id=service_id or "default",
            timestamp=event_timestamp,
            access_type=access_type,
            latency_ms=latency_ms,
            cache_hit=cache_hit,
            metadata=metadata
        )
        
        with self._lock:
            self._events.append(event)
            self._recent_events.append(event)
            
            # Update aggregated stats
            self._update_stats(event)
            
            # Periodic cleanup of historical stats
            self._cleanup_historical_stats()
        
        # Save to Redis periodically (every 50 events) to avoid O(n²) cost
        # during bulk imports and to reduce lock contention.
        if len(self._events) % 50 == 0:
            self._save_to_redis()
    
    def _cleanup_historical_stats(self):
        """
        Clean up old historical stats to prevent unbounded memory growth (Issue #11).
        Called periodically during record_access.
        """
        now = time.time()
        
        # Only cleanup every 100 records to reduce overhead
        if not hasattr(self, '_cleanup_counter'):
            self._cleanup_counter = 0
        self._cleanup_counter += 1
        
        if self._cleanup_counter < 100:
            return
        
        self._cleanup_counter = 0
        
        # Remove entries older than TTL
        cutoff_time = now - self._historical_stats_ttl_seconds
        keys_to_remove = []
        for key, values in self._historical_stats.items():
            # Filter out old values
            self._historical_stats[key] = [v for v in values if v > cutoff_time]
            if not self._historical_stats[key]:
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del self._historical_stats[key]
        
        # If still over limit, remove oldest entries
        if len(self._historical_stats) > self._historical_stats_max_entries:
            num_to_remove = len(self._historical_stats) - int(self._historical_stats_max_entries * 0.8)
            keys_sorted = sorted(self._historical_stats.keys())
            for key in keys_sorted[:num_to_remove]:
                del self._historical_stats[key]
            
            logger.debug(f"DataCollector: Pruned {num_to_remove} old historical stat entries")
    
    def _update_stats(self, event: AccessEvent):
        """Update aggregated statistics for a key"""
        key_id = event.key_id
        
        if key_id not in self._key_stats:
            self._key_stats[key_id] = KeyAccessStats(key_id=key_id)
        
        stats = self._key_stats[key_id]
        stats.total_accesses += 1
        stats.last_access = event.timestamp
        
        if event.cache_hit:
            stats.cache_hits += 1
        else:
            stats.cache_misses += 1
        
        # Update latency
        if stats.total_accesses == 1:
            stats.avg_latency_ms = event.latency_ms
        else:
            stats.avg_latency_ms = (
                (stats.avg_latency_ms * (stats.total_accesses - 1) + event.latency_ms)
                / stats.total_accesses
            )
        
        # Update service breakdown
        stats.access_by_service[event.service_id] = (
            stats.access_by_service.get(event.service_id, 0) + 1
        )
        
        # Update hourly counts
        hour = datetime.fromtimestamp(event.timestamp).hour
        stats.hourly_access_counts[hour] += 1
    
    def get_key_stats(self, key_id: str) -> Optional[KeyAccessStats]:
        """Get aggregated stats for a key"""
        with self._lock:
            return self._key_stats.get(key_id)
    
    def get_all_key_stats(self) -> Dict[str, KeyAccessStats]:
        """Get stats for all keys"""
        with self._lock:
            return self._key_stats.copy()
    
    def get_hot_keys(self, limit: int = 10) -> List[tuple]:
        """Get most frequently accessed keys"""
        with self._lock:
            sorted_keys = sorted(
                self._key_stats.items(),
                key=lambda x: x[1].total_accesses,
                reverse=True
            )
            return [(k, v.total_accesses) for k, v in sorted_keys[:limit]]
    
    def get_recent_events(
        self,
        key_id: str = None,
        service_id: str = None,
        limit: int = 100
    ) -> List[AccessEvent]:
        """Get recent access events"""
        with self._lock:
            events = list(self._recent_events)
        
        if key_id:
            events = [e for e in events if e.key_id == key_id]
        if service_id:
            events = [e for e in events if e.service_id == service_id]
        
        return events[-limit:]
    
    def get_access_sequence(
        self,
        window_seconds: int = None,
        max_events: int = 20000
    ) -> List[Dict[str, Any]]:
        """
        Get access sequence for sequence modeling.
        
        Returns list of events as dicts suitable for ML training.
        """
        window_seconds = window_seconds or self._window_seconds
        cutoff = time.time() - window_seconds
        
        with self._lock:
            events = [
                e for e in self._events
                if e.timestamp >= cutoff
            ]
        
        # Limit events
        events = events[-max_events:]
        
        # Convert to dict format
        return [
            {
                "key_id": e.key_id,
                "service_id": e.service_id,
                "timestamp": e.timestamp,
                "hour": datetime.fromtimestamp(e.timestamp).hour,
                "day_of_week": datetime.fromtimestamp(e.timestamp).weekday(),
                "cache_hit": int(e.cache_hit),
                "latency_ms": e.latency_ms
            }
            for e in events
        ]
    
    def get_temporal_features(self, key_id: str) -> Dict[str, float]:
        """Extract temporal features for a key"""
        events = self.get_recent_events(key_id=key_id, limit=1000)
        
        if not events:
            return {}
        
        # Calculate features
        timestamps = [e.timestamp for e in events]
        
        # Access intervals
        if len(timestamps) > 1:
            intervals = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps)-1)]
            avg_interval = sum(intervals) / len(intervals)
        else:
            avg_interval = 0.0
        
        # Hourly distribution
        hour_counts = defaultdict(int)
        for e in events:
            hour_counts[datetime.fromtimestamp(e.timestamp).hour] += 1
        
        peak_hour = max(hour_counts.items(), key=lambda x: x[1])[0] if hour_counts else 0
        
        # Access regularity (variance in intervals)
        if len(intervals) > 1:
            import statistics
            interval_variance = statistics.variance(intervals) if len(intervals) > 1 else 0.0
        else:
            interval_variance = 0.0
        
        return {
            "avg_interval_seconds": avg_interval,
            "interval_variance": interval_variance,
            "peak_hour": peak_hour,
            "unique_services": len(set(e.service_id for e in events)),
            "total_accesses": len(events)
        }
    
    def export_training_data(
        self,
        output_path: str,
        window_seconds: int = 3600
    ):
        """Export training data to file"""
        data = self.get_access_sequence(window_seconds=window_seconds)
        
        with open(output_path, 'w') as f:
            json.dump(data, f)
        
        logger.info(f"Exported {len(data)} events to {output_path}")
    
    def import_events(self, events: List[Dict[str, Any]]) -> int:
        """
        Import access events from external source.
        
        Args:
            events: List of event dicts with keys: key_id, service_id, timestamp, 
                   access_type, cache_hit, latency_ms
        
        Returns:
            Number of events imported
        """
        imported = 0
        for event_data in events:
            try:
                self.record_access(
                    key_id=event_data.get("key_id", ""),
                    service_id=event_data.get("service_id", "default"),
                    access_type=event_data.get("access_type", "read"),
                    latency_ms=event_data.get("latency_ms", 0.0),
                    cache_hit=event_data.get("cache_hit", False),
                    timestamp=event_data.get("timestamp")  # Pass the timestamp!
                )
                imported += 1
            except Exception as e:
                logger.warning(f"Failed to import event: {e}")
        
        logger.info(f"Imported {imported} events")
        return imported
    
    def get_stats(self) -> Dict[str, Any]:
        """Get collector statistics"""
        with self._lock:
            return {
                "total_events": len(self._events),
                "unique_keys": len(self._key_stats),
                "unique_services": len(set(e.service_id for e in self._events)),
                "window_seconds": self._window_seconds
            }
    
    def clear_old_events(self, hours: int = 24):
        """Clear events older than specified hours"""
        cutoff = time.time() - (hours * 3600)
        
        with self._lock:
            # Clear old events
            while self._events and self._events[0].timestamp < cutoff:
                self._events.popleft()
            
            while self._recent_events and self._recent_events[0].timestamp < cutoff:
                self._recent_events.popleft()
        
        logger.info(f"Cleared events older than {hours} hours")
    
    def _load_from_redis(self):
        """Load events from Redis shared storage"""
        if not self._redis:
            return
        try:
            events_data = self._redis.lrange(self.REDIS_KEY_PREFIX, 0, -1)
            for event_data in events_data:
                try:
                    event_dict = json.loads(event_data)
                    event = AccessEvent(
                        key_id=event_dict.get("key_id", ""),
                        service_id=event_dict.get("service_id", "default"),
                        timestamp=event_dict.get("timestamp", time.time()),
                        access_type=event_dict.get("access_type", "read"),
                        latency_ms=event_dict.get("latency_ms", 0.0),
                        cache_hit=event_dict.get("cache_hit", False),
                    )
                    self._events.append(event)
                    self._recent_events.append(event)
                    self._update_stats(event)
                except Exception:
                    pass
            logger.info(f"Loaded {len(events_data)} events from Redis")
        except Exception as e:
            logger.warning(f"Could not load from Redis: {e}")
    
    def _save_to_redis(self):
        """Save events to Redis shared storage (thread-safe snapshot)."""
        if not self._redis:
            return
        # Take a snapshot inside the lock so no other thread can mutate the deque
        # while we're serialising it.
        with self._lock:
            events_snapshot = list(self._events)
        try:
            if not events_snapshot:
                return
            events_data = [
                json.dumps({
                    "key_id": e.key_id,
                    "service_id": e.service_id,
                    "timestamp": e.timestamp,
                    "access_type": e.access_type,
                    "latency_ms": e.latency_ms,
                    "cache_hit": e.cache_hit,
                })
                for e in events_snapshot
            ]
            self._redis.delete(self.REDIS_KEY_PREFIX)
            self._redis.rpush(self.REDIS_KEY_PREFIX, *events_data)
            logger.debug(f"Saved {len(events_snapshot)} events to Redis")
        except Exception as e:
            logger.warning(f"Could not save to Redis: {e}")
    
    def flush_to_redis(self):
        """Force flush all events to Redis immediately (non-periodic)."""
        self._save_to_redis()


# Global data collector instance
_collector_instance: Optional[DataCollector] = None


def get_data_collector() -> DataCollector:
    """Get global data collector"""
    global _collector_instance
    if _collector_instance is None:
        _collector_instance = DataCollector()
    return _collector_instance
