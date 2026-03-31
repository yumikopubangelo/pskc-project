# ============================================================
# PSKC — Traffic Pattern Tracker
# Real-time traffic pattern capture in Redis with TTL and
# spike detection for pattern-divergence retraining.
# ============================================================
import os
import time
import json
import math
import logging
from collections import defaultdict
from datetime import datetime
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class TrafficPatternTracker:
    """
    Captures live traffic patterns in Redis with a 1-hour TTL.

    Redis keys
    ----------
    ``pskc:traffic:pattern``
        Hash storing current 1-hour rolling counters:
        ``total_events``, ``cache_hits``, ``hour_<H>``, ``key:<K>``, ``svc:<S>``
    ``pskc:traffic:spike_events``
        List of JSON event snapshots captured during a traffic spike (TTL 1 h).
    ``pskc:traffic:rps``
        String holding a compact JSON array of per-minute RPS measurements
        (last 60 entries).  Used for spike detection baseline.

    All keys automatically expire after ``TTL_SECONDS`` (default 3600 s).
    """

    PATTERN_KEY = "pskc:traffic:pattern"
    SPIKE_KEY = "pskc:traffic:spike_events"
    RPS_KEY = "pskc:traffic:rps"

    def __init__(
        self,
        redis_client=None,
        ttl_seconds: int = 3600,
        spike_multiplier: float = None,
        max_spike_events: int = 5000,
    ):
        self._redis = redis_client
        self._ttl = ttl_seconds
        self._spike_multiplier = spike_multiplier or float(
            os.environ.get("TRAFFIC_SPIKE_MULTIPLIER", "2.0")
        )
        self._max_spike_events = max_spike_events

        # In-memory counters for the current minute (flushed to Redis).
        self._minute_event_count: int = 0
        self._current_minute: int = 0  # minute-of-hour at last reset

        # Spike state
        self._spike_active: bool = False
        self._spike_start: float = 0.0

        logger.info(
            "TrafficPatternTracker initialized: ttl=%ds, spike_multiplier=%.1fx",
            self._ttl,
            self._spike_multiplier,
        )

    # ----------------------------------------------------------------
    # Record
    # ----------------------------------------------------------------

    def record_event(self, event: Dict[str, Any]) -> None:
        """
        Record one access event into the rolling 1-hour Redis pattern.

        Parameters
        ----------
        event : dict
            Must contain at least ``key_id``, ``service_id``, ``cache_hit``.
            ``timestamp`` is optional (defaults to now).
        """
        if not self._redis:
            return

        try:
            ts = float(event.get("timestamp", time.time()))
            hour = datetime.fromtimestamp(ts).hour
            key_id = str(event.get("key_id", "?"))[:128]
            svc_id = str(event.get("service_id", "?"))[:64]
            cache_hit = bool(event.get("cache_hit", False))

            pipe = self._redis.pipeline(transaction=False)
            pipe.hincrby(self.PATTERN_KEY, "total_events", 1)
            pipe.hincrby(self.PATTERN_KEY, f"hour_{hour}", 1)
            pipe.hincrby(self.PATTERN_KEY, f"key:{key_id}", 1)
            pipe.hincrby(self.PATTERN_KEY, f"svc:{svc_id}", 1)
            if cache_hit:
                pipe.hincrby(self.PATTERN_KEY, "cache_hits", 1)
            pipe.expire(self.PATTERN_KEY, self._ttl)
            pipe.execute()

            # Track per-minute count for RPS / spike detection
            self._minute_event_count += 1
            now_minute = int(time.time()) // 60
            if now_minute != self._current_minute:
                self._flush_rps_minute()
                self._current_minute = now_minute

        except Exception as exc:
            logger.debug("TrafficPatternTracker.record_event failed: %s", exc)

    # ----------------------------------------------------------------
    # Spike detection
    # ----------------------------------------------------------------

    def detect_spike(self) -> bool:
        """
        Return ``True`` if the current-minute event rate exceeds
        ``spike_multiplier × baseline_rps``.

        Baseline RPS is calculated as the median of the last 60 per-minute
        counts stored in ``pskc:traffic:rps``.
        """
        baseline = self._get_baseline_rps()
        if baseline <= 0:
            # No history yet — can't detect spikes
            return False

        current_rps = self._minute_event_count
        is_spike = current_rps > (baseline * self._spike_multiplier)

        if is_spike and not self._spike_active:
            self._spike_active = True
            self._spike_start = time.time()
            logger.warning(
                "Traffic spike DETECTED: current=%d events/min, "
                "baseline=%.1f events/min (%.1fx threshold)",
                current_rps,
                baseline,
                self._spike_multiplier,
            )
        elif not is_spike and self._spike_active:
            duration = time.time() - self._spike_start
            self._spike_active = False
            logger.info(
                "Traffic spike ended after %.1fs",
                duration,
            )

        return is_spike

    def capture_spike_events(self, events: List[Dict[str, Any]]) -> int:
        """
        Store a batch of events captured during a spike window.
        Events are pushed to ``pskc:traffic:spike_events`` with TTL.
        Returns the number of events stored.
        """
        if not self._redis or not events:
            return 0
        try:
            pipe = self._redis.pipeline(transaction=False)
            stored = 0
            for ev in events[: self._max_spike_events]:
                pipe.lpush(
                    self.SPIKE_KEY,
                    json.dumps(
                        {
                            "key_id": ev.get("key_id"),
                            "service_id": ev.get("service_id"),
                            "cache_hit": ev.get("cache_hit"),
                            "timestamp": ev.get("timestamp", time.time()),
                        }
                    ),
                )
                stored += 1
            pipe.ltrim(self.SPIKE_KEY, 0, self._max_spike_events - 1)
            pipe.expire(self.SPIKE_KEY, self._ttl)
            pipe.execute()
            logger.info("Captured %d spike events to Redis", stored)
            return stored
        except Exception as exc:
            logger.debug("capture_spike_events failed: %s", exc)
            return 0

    # ----------------------------------------------------------------
    # Live pattern retrieval
    # ----------------------------------------------------------------

    def get_live_pattern(self) -> Dict[str, Any]:
        """
        Read the current 1-hour pattern from Redis and reshape it into
        a format compatible with ``SampleProfiler.compare_profiles()``.
        """
        if not self._redis:
            return {}

        try:
            raw = self._redis.hgetall(self.PATTERN_KEY)
        except Exception:
            return {}

        if not raw:
            return {}

        # Decode byte keys if needed
        data: Dict[str, str] = {}
        for k, v in raw.items():
            dk = k.decode() if isinstance(k, bytes) else k
            dv = v.decode() if isinstance(v, bytes) else v
            data[dk] = dv

        total = int(data.get("total_events", 0))
        cache_hits = int(data.get("cache_hits", 0))

        # Temporal profile
        temporal: Dict[str, int] = {}
        for h in range(24):
            val = int(data.get(f"hour_{h}", 0))
            if val:
                temporal[str(h)] = val

        # Key frequency (top 50)
        key_freq: Dict[str, int] = {}
        for k, v in data.items():
            if k.startswith("key:"):
                key_freq[k[4:]] = int(v)
        # Sort descending and take top 50
        key_freq = dict(
            sorted(key_freq.items(), key=lambda x: x[1], reverse=True)[:50]
        )

        # Service distribution
        svc_counts: Dict[str, int] = {}
        for k, v in data.items():
            if k.startswith("svc:"):
                svc_counts[k[4:]] = int(v)
        svc_dist = {
            s: round(c / total, 4) for s, c in svc_counts.items()
        } if total else {}

        return {
            "total_samples": total,
            "unique_keys": len(key_freq),
            "unique_services": len(svc_counts),
            "temporal_profile": temporal,
            "key_frequency_profile": key_freq,
            "service_distribution": svc_dist,
            "cache_hit_rate": round(cache_hits / total, 4) if total else 0.0,
            "avg_latency_ms": 0.0,  # Not tracked per-event in Redis
            "latency_p95_ms": 0.0,
            "spike_active": self._spike_active,
        }

    # ----------------------------------------------------------------
    # Internal helpers
    # ----------------------------------------------------------------

    def _flush_rps_minute(self) -> None:
        """Push the current-minute event count to the RPS history."""
        if not self._redis:
            return
        try:
            self._redis.lpush(self.RPS_KEY, str(self._minute_event_count))
            self._redis.ltrim(self.RPS_KEY, 0, 59)  # Keep last 60 minutes
            self._redis.expire(self.RPS_KEY, self._ttl)
        except Exception:
            pass
        self._minute_event_count = 0

    def _get_baseline_rps(self) -> float:
        """Median of the last 60 per-minute event counts."""
        if not self._redis:
            return 0.0
        try:
            raw = self._redis.lrange(self.RPS_KEY, 0, 59)
            if not raw:
                return 0.0
            values = []
            for v in raw:
                try:
                    values.append(int(v))
                except (ValueError, TypeError):
                    pass
            if not values:
                return 0.0
            values.sort()
            mid = len(values) // 2
            if len(values) % 2 == 0:
                return (values[mid - 1] + values[mid]) / 2.0
            return float(values[mid])
        except Exception:
            return 0.0

    def get_stats(self) -> Dict[str, Any]:
        """Return tracker diagnostics."""
        return {
            "spike_active": self._spike_active,
            "spike_multiplier": self._spike_multiplier,
            "ttl_seconds": self._ttl,
            "current_minute_events": self._minute_event_count,
            "baseline_rps": self._get_baseline_rps(),
        }
