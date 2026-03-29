"""
Training loop runner encapsulates epoch/batch execution and progress callbacks.

This module is a stepping stone in the refactor: the heavy training logic
still lives in ModelTrainer.train() but this class provides the interface
that future phases will migrate to.
"""
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class TrainingLoop:
    """Run training epochs and report progress via callback.

    ``model`` may be None initially; the caller provides it when training
    is actually triggered.
    """

    def __init__(
        self,
        model: Optional[Any] = None,
        engineer: Optional[Any] = None,
    ):
        self.model = model
        self.engineer = engineer
        self._last_metrics: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def attach_model(self, model: Any) -> None:
        """Swap in a freshly built model before a training run."""
        self.model = model

    def run_training_loop(
        self,
        samples: List[Dict[str, Any]],
        epochs: int,
        batch_size: int,
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Run a simplified training loop returning final metrics.

        Calls ``on_progress`` occasionally with a progress dict.
        Real training logic will plug into ``model.train_batch`` in
        a future phase; for now the model's own ``.fit()`` is used
        directly in ModelTrainer.train() and this method serves as
        a callback harness.
        """
        total = len(samples)
        if total == 0:
            self._last_metrics = {
                "accuracy": 0.0,
                "loss": 0.0,
                "trained_samples": 0,
                "epochs_completed": 0,
            }
            return self._last_metrics

        for epoch in range(1, max(1, epochs) + 1):
            processed = min(total, epoch * batch_size)
            if on_progress:
                on_progress({
                    "phase": "training",
                    "epoch": epoch,
                    "total_epochs": epochs,
                    "processed": processed,
                    "total": total,
                    "percent": int(processed / total * 100) if total else 0,
                })

        self._last_metrics = {
            "accuracy": 0.5,
            "loss": 1.0,
            "trained_samples": total,
            "epochs_completed": epochs,
        }
        return self._last_metrics

    @property
    def last_metrics(self) -> Dict[str, Any]:
        return self._last_metrics
