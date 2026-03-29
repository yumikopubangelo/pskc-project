"""
Progress manager builds and updates progress payloads for the frontend.

Centralises the JSON shape that the frontend expects so both
``get_training_plan()`` and the training loop emit identical schemas.
"""
import time
from typing import Dict, Any, Optional


class ProgressManager:
    """Build and update progress payloads for the frontend."""

    def __init__(self):
        self._start_time: Optional[float] = None

    # ------------------------------------------------------------------
    # Plan payload (returned by GET /ml/training/plan)
    # ------------------------------------------------------------------

    def initial_plan_payload(
        self,
        *,
        sample_count: int,
        unique_keys: int,
        estimated_minutes: int,
        quality_profile: str = "balanced",
        time_budget_minutes: int = 30,
    ) -> Dict[str, Any]:
        """Create the payload sent to the frontend before training starts.

        The frontend uses ``sample_count`` and ``estimated_training_minutes``
        to display a preview of what the training run will look like.
        """
        return {
            "phase": "planned",
            "sample_count": sample_count,
            "unique_keys": unique_keys,
            "estimated_training_minutes": estimated_minutes,
            "quality_profile": quality_profile,
            "time_budget_minutes": time_budget_minutes,
            "started_at": None,
            "progress": 0,
        }

    # ------------------------------------------------------------------
    # Live training updates
    # ------------------------------------------------------------------

    def mark_started(self) -> None:
        """Record the wall-clock start of training."""
        self._start_time = time.time()

    def update_progress(
        self,
        payload: Dict[str, Any],
        *,
        processed: int,
        total: int,
        phase: str = "training",
    ) -> Dict[str, Any]:
        """Return a copy of *payload* with live progress fields updated."""
        payload = dict(payload)
        payload["phase"] = phase
        payload["processed"] = processed
        payload["total"] = total
        payload["progress"] = int(processed / total * 100) if total else 0
        payload["updated_at"] = time.time()
        if self._start_time:
            payload["elapsed_seconds"] = round(time.time() - self._start_time, 1)
        return payload

    def mark_completed(
        self,
        payload: Dict[str, Any],
        *,
        success: bool,
        metrics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return a final progress payload when training finishes."""
        payload = dict(payload)
        payload["phase"] = "completed" if success else "failed"
        payload["progress"] = 100 if success else payload.get("progress", 0)
        payload["completed_at"] = time.time()
        if self._start_time:
            payload["elapsed_seconds"] = round(time.time() - self._start_time, 1)
        if metrics:
            payload["metrics"] = metrics
        return payload
