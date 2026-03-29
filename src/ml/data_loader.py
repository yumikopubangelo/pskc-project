"""
Data selection and sampling utilities for training.

Provides the ModelTrainer with sample counts and batches without the trainer
needing to reach into the collector/engineer internals directly.
"""
import time
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class DataLoader:
    """Selects and samples training examples from the collector.

    Methods are intentionally minimal so they can be expanded and
    unit-tested independently.
    """

    def __init__(self, collector, engineer):
        self.collector = collector
        self.engineer = engineer

    # ------------------------------------------------------------------
    # Quick statistics (no heavy I/O)
    # ------------------------------------------------------------------

    def get_sample_stats(self) -> Dict[str, int]:
        """Return lightweight counts from the collector for planning.

        Returns dict with ``total_events`` and ``unique_keys``.
        """
        try:
            stats = self.collector.get_stats()
            return {
                "total_events": int(stats.get("total_events", 0) or 0),
                "unique_keys": int(stats.get("unique_keys", 0) or 0),
            }
        except Exception:
            logger.debug("DataLoader.get_sample_stats failed, returning zeros")
            return {"total_events": 0, "unique_keys": 0}

    def available_samples(self, *, window_seconds: int = 0) -> int:
        """Return an estimate of available samples within the time window.

        If *window_seconds* is 0 or the collector has no time-filtering
        method, fall back to the total event count.
        """
        try:
            # Prefer a time-windowed count if the collector exposes one
            if window_seconds > 0 and hasattr(self.collector, "count_events_since"):
                return self.collector.count_events_since(window_seconds)
            # Fallback: use get_stats total_events
            stats = self.collector.get_stats()
            return int(stats.get("total_events", 0) or 0)
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # Data retrieval
    # ------------------------------------------------------------------

    def fetch_access_sequence(
        self,
        *,
        window_seconds: int = 604800,
        max_events: int = 90000,
    ) -> List[Dict[str, Any]]:
        """Retrieve the raw access sequence from the collector.

        Wraps ``collector.get_access_sequence()`` so the trainer doesn't
        call it directly.
        """
        try:
            return self.collector.get_access_sequence(
                window_seconds=window_seconds,
                max_events=max_events,
            )
        except Exception:
            logger.exception("DataLoader.fetch_access_sequence failed")
            return []

    def sample_batch(
        self, *, sample_count: int, context_window: int
    ) -> List[Dict[str, Any]]:
        """Return a list of engineered training samples (dicts).

        This function currently delegates to collector and engineer; keep it
        small and deterministic for testing.
        """
        try:
            events = self.collector.get_access_sequence(
                max_events=sample_count * context_window,
            )
            if hasattr(self.engineer, "build_samples_from_events"):
                samples = self.engineer.build_samples_from_events(
                    events, context_window=context_window
                )
                return samples
            # If engineer lacks the method, just return the raw events
            return events
        except Exception:
            logger.exception("DataLoader.sample_batch failed")
            return []
