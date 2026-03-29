"""
Adaptive hyperparameter tuner used by ModelTrainer during planning.

Wraps the upstream ``HyperparameterTuner`` from model_improvements and
adds lightweight heuristics for epoch/batch tuning based on sample
count and profile caps.
"""
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class AdaptiveHyperparameterTuner:
    """Compute epochs/batch sizes based on sample counts and time budget.

    The ``propose()`` method returns quick heuristic overrides that
    are applied on top of the profile caps inside ``_build_training_plan``.
    The ``estimate_training_minutes()`` method gives a rough wall-clock
    estimate for a given sample count + hyperparameter set.
    """

    def __init__(self):
        # Per-sample rate in minutes — rough CPU benchmark
        # ~12 000 samples ≈ 1 minute for RF+Markov, tuned from production telemetry.
        self._samples_per_minute = 12_000.0

    # ------------------------------------------------------------------
    # Core API used by get_training_plan()
    # ------------------------------------------------------------------

    def propose(
        self,
        *,
        sample_count: int,
        time_budget_minutes: int,
        profile: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Return adaptive overrides for epochs and batch_size.

        Args:
            sample_count: Total available training samples.
            time_budget_minutes: Requested time budget.
            profile: The TRAINING_PROFILE_DEFAULTS dict for the chosen profile.

        Returns:
            Dict with ``epochs`` and ``batch_size`` keys.
        """
        max_epochs = int(profile.get("epochs_cap", 10))
        batch_floor = int(profile.get("batch_size_floor", 32))

        # More samples → more epochs (logarithmic), but bounded by profile cap
        if sample_count <= 0:
            base_epochs = 1
        elif sample_count < 500:
            base_epochs = max(1, min(max_epochs, 4))
        elif sample_count < 2000:
            base_epochs = max(1, min(max_epochs, 8))
        elif sample_count < 10000:
            base_epochs = max(1, min(max_epochs, sample_count // 1000))
        else:
            base_epochs = max(1, min(max_epochs, 10 + (sample_count - 10000) // 5000))

        epochs = max(1, min(max_epochs, base_epochs))

        # Batch size: increase for large datasets to keep epoch time bounded
        batch_size = batch_floor
        if sample_count > 50_000:
            batch_size = max(batch_size, 64)
        if sample_count > 100_000:
            batch_size = max(batch_size, 128)

        return {"epochs": epochs, "batch_size": batch_size}

    def estimate_minutes(
        self,
        *,
        sample_count: int,
        unique_keys: int,
        profile_name: str = "balanced",
        rf_trees: int = 50,
        lstm_epochs: int = 10,
        lstm_hidden: int = 64,
    ) -> int:
        """Estimate wall-clock minutes for a full training run.

        Uses a simplified scoring formula that matches the one in
        ``ModelTrainer._estimate_training_minutes`` so the planner
        and the actual trainer share a consistent estimate.
        """
        profile_factor = {
            "fast": 0.75,
            "balanced": 1.0,
            "thorough": 1.3,
        }.get(profile_name, 1.0)

        score = (
            (sample_count / self._samples_per_minute)
            + (unique_keys / 180.0)
            + (rf_trees / 55.0)
            + (lstm_epochs * max(lstm_hidden, 32) / 420.0)
        ) * profile_factor

        return max(2, int(round(score)))
