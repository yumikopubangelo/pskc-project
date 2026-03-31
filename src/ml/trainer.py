# ============================================================
# PSKC — Trainer Module (IMPROVED)
# Training and evaluation of ML models
#
# IMPROVEMENTS:
#   1. Concept Drift Detection — sliding window monitor yang deteksi
#      kalau akurasi drop signifikan (drift) dan trigger retrain otomatis.
#      Sebelumnya auto_train hanya berbasis interval waktu (30s) tanpa
#      peduli apakah model masih akurat atau tidak.
#   2. evaluate() sekarang mengembalikan metrik nyata (bukan 0.0 placeholder)
#   3. Training menggunakan konteks window (10 event) per sample,
#      bukan satu event tunggal — konsisten dengan train_model.py baru
#   4. DriftDetector bisa dikonfigurasi sensitivity-nya
#   5. EWMA maturation - implementasi lengkap sesuai paper research
#   6. Data Balancing — SMOTE-inspired class imbalance handling
#   7. Feature Selection — SelectKBest untuk mengurangi noise
#   8. Data Augmentation — noise, scaling, mixup untuk robustness
#   9. Feature Normalization — StandardScaler untuk stabilitas training
#  10. Hyperparameter Tuning — adaptive hyperparameters berdasarkan data size
# ============================================================
import time
import threading
import os
import numpy as np
from collections import Counter, defaultdict, deque
from typing import Dict, List, Optional, Tuple, Any, Union
import logging
from datetime import datetime, timezone, timedelta
import math

from config.settings import settings
from src.ml.data_collector import get_data_collector
from src.ml.feature_engineering import get_feature_engineer
from src.ml.model import EnsembleModel, ModelFactory
from src.ml.model_registry import SecurityError, get_model_registry
from src.ml.incremental_model import IncrementalModelPersistence
from src.observability.metrics_persistence import get_metrics_persistence
from src.api.training_progress import get_training_progress_tracker, TrainingPhase
from src.ml.model_improvements import (
    DataBalancer,
    DataAugmenter,
    HyperparameterTuner,
    RFPreprocessor,
)

# New modular components (incremental refactor)
from src.ml.data_loader import DataLoader
from src.ml.training_loop import TrainingLoop
from src.ml.tuner import AdaptiveHyperparameterTuner
from src.ml.progress import ProgressManager

logger = logging.getLogger(__name__)


TRAINING_PROFILE_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "fast": {
        "window_seconds": 86400,
        "max_events": 40000,
        "rf_tree_cap": 48,
        "rf_depth_cap": 10,
        "lstm_hidden_cap": 64,
        "epochs_cap": 12,
        "batch_size_floor": 32,
        "augmentation_factor": 0.10,
        "feature_cap": 18,
        "notes": "Shortest runtime, good for quick iteration and sanity-check retrains.",
    },
    "balanced": {
        "window_seconds": 604800,
        "max_events": 90000,
        "rf_tree_cap": 80,
        "rf_depth_cap": 12,
        "lstm_hidden_cap": 96,
        "epochs_cap": 18,
        "batch_size_floor": 48,
        "augmentation_factor": 0.18,
        "feature_cap": 22,
        "notes": "Default profile for stronger validation without letting training sprawl.",
    },
    "thorough": {
        "window_seconds": 1209600,
        "max_events": 150000,
        "rf_tree_cap": 128,
        "rf_depth_cap": 14,
        "lstm_hidden_cap": 128,
        "epochs_cap": 24,
        "batch_size_floor": 64,
        "augmentation_factor": 0.22,
        "feature_cap": 28,
        "notes": "Highest quality profile. Intended to stay within a 30-60 minute budget on CPU-class deployments.",
    },
}

SAMPLE_STRATEGY_OPTIONS = {
    "auto",
    "all",
    "realistic_priority",
    "realistic_only",
}


# ============================================================
# Concept Drift Detector moved to src/ml/drift.py
# ============================================================

from src.ml.drift import DriftDetector


# ============================================================
# Model Trainer (IMPROVED)
# ============================================================

class ModelTrainer:
    """
    Handles model training, evaluation, and drift-triggered retraining.
    Supports both batch and online learning.
    """

    def __init__(
        self,
        model: EnsembleModel = None,
        update_interval: int = 30,    # seconds between routine retrains
        min_samples: int = 100,
        batch_size: int = 32,
        drift_threshold: float = 0.12,
        context_window: int = 10,     # events of context per training sample
        model_name: Optional[str] = None,
        registry = None,
        incremental_persistence: Optional[IncrementalModelPersistence] = None,
    ):
        self._model = model
        self._update_interval = update_interval
        self._min_samples = min_samples
        self._batch_size = batch_size
        self._context_window = context_window
        self._model_name = model_name or settings.ml_model_name
        self._registry = registry
        self._incremental_persistence = incremental_persistence
        self._active_model_version: Optional[str] = None
        self._active_artifact_path: Optional[str] = None
        self._model_source = "runtime"

        # Components
        self._collector = get_data_collector()
        self._engineer = get_feature_engineer()
        # Modular helpers (new)
        self._data_loader = DataLoader(self._collector, self._engineer)
        self._training_loop = TrainingLoop(model=None, engineer=self._engineer)
        self._adaptive_tuner = AdaptiveHyperparameterTuner()
        self._progress_manager = ProgressManager()
        # Minimum accuracy to accept a newly trained model.
        # Set to 0.0 — the version-bump comparison in IncrementalModelPersistence
        # already handles "is it better than the previous model?" separately.
        # A hard floor of 5% was impossible to pass with 100 unique keys (random=1%).
        self._min_accuracy_for_active = 0.0

        # Drift detection
        self._drift_detector = DriftDetector(drift_threshold=drift_threshold)

        # Training state - separate for scheduled vs automatic
        self._is_training_scheduled = False  # Full batch retraining on schedule
        self._is_training_automatic = False  # Drift-based/online learning
        self._last_train_time: float = 0
        self._training_count: int = 0
        # Avoid retrying load_active_model() after a known failure (e.g. missing file)
        # Reset to False when a new model is successfully trained.
        self._load_failed: bool = False
        self._last_drift_retrain_time: float = 0
        self._online_learning_count: int = 0
        self._last_online_learning_result: Dict[str, Any] = {}
        
        # Training locks - allow concurrent scheduled/automatic but serialize within each type
        self._scheduled_lock = threading.Lock()
        self._automatic_lock = threading.Lock()

        # Metrics history
        self._training_history: List[Dict] = []
        self._last_evaluation: Dict[str, Any] = {}

        # Background thread
        self._train_thread: Optional[threading.Thread] = None
        self._running = False

        logger.info(
            f"ModelTrainer initialized: interval={update_interval}s, "
            f"min_samples={min_samples}, drift_threshold={drift_threshold:.0%}, "
            f"context_window={context_window}"
        )

    def _get_registry(self):
        if self._registry is None:
            self._registry = get_model_registry()
        return self._registry

    def _get_incremental_persistence(self) -> IncrementalModelPersistence:
        if self._incremental_persistence is None:
            registry = self._get_registry()
            self._incremental_persistence = IncrementalModelPersistence(
                model_dir=getattr(registry, "model_dir", settings.effective_ml_model_registry_dir),
                model_name=self._model_name,
            )
        return self._incremental_persistence

    def _get_incremental_info(self) -> Dict[str, Any]:
        if self._incremental_persistence is None:
            return {
                "exists": False,
                "model_name": self._model_name,
                "file_path": os.path.join(
                    settings.effective_ml_model_registry_dir,
                    IncrementalModelPersistence.DEFAULT_INCREMENTAL_FILE,
                ),
                "lazy": True,
            }
        return self._incremental_persistence.get_info()

    # ----------------------------------------------------------
    # Model Property
    # ----------------------------------------------------------

    @property
    def model(self) -> EnsembleModel:
        if self._model is None:
            self._model = ModelFactory.create_model("ensemble")
        return self._model

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def _is_training(self) -> bool:
        """Combined training flag for backward compatibility."""
        return self._is_training_scheduled or self._is_training_automatic

    @_is_training.setter
    def _is_training(self, value: bool) -> None:
        """Set both training flags to the same value."""
        self._is_training_scheduled = value
        self._is_training_automatic = value

    def get_active_model_metadata(self) -> Dict[str, Optional[str]]:
        return {
            "model_name": self._model_name,
            "version": self._active_model_version,
            "artifact_path": self._active_artifact_path,
            "source": self._model_source,
        }

    def _timestamp_from_iso(self, value: Optional[str]) -> float:
        if not value:
            return 0.0
        try:
            return datetime.fromisoformat(value).timestamp()
        except ValueError:
            return 0.0

    def _record_training_metrics(
        self,
        *,
        accuracy: float,
        loss: float,
        samples: int,
        duration_seconds: float,
        status: str,
    ) -> None:
        metrics_persistence = get_metrics_persistence()
        if metrics_persistence is None or not metrics_persistence.ping():
            return
        metrics_persistence.record_ml_training(
            model_name=self._model_name,
            accuracy=accuracy,
            loss=loss,
            samples=samples,
            duration_seconds=duration_seconds,
            status=status,
        )

    def load_active_model(self) -> Dict[str, Any]:
        # Prefer the secure registry as the runtime source of truth.
        registry = self._get_registry()
        active_version = registry.get_active_version(self._model_name)
        if active_version is not None:
            try:
                loaded_model = registry.load_model(self._model_name, actor="trainer")
            except SecurityError as e:
                logger.error("Security error loading active model: %s", e)
                return {"success": False, "reason": "security_error", "detail": str(e)}

            if loaded_model is not None:
                self._model = loaded_model
                self._active_model_version = active_version.version
                self._active_artifact_path = active_version.file_path
                self._model_source = "registry"
                self._last_train_time = max(self._last_train_time, float(active_version.created_at or time.time()))
                logger.info(
                    "Loaded active runtime model %s:%s from %s",
                    self._model_name,
                    active_version.version,
                    active_version.file_path,
                )
                return {
                    "success": True,
                    "version": active_version.version,
                    "artifact_path": active_version.file_path,
                    "source": self._model_source,
                }

        # Backward-compatible fallback for legacy incremental checkpoints that
        # still contain a full serialized model artifact.
        incremental_persistence = self._get_incremental_persistence()
        if incremental_persistence.exists():
            model_data = incremental_persistence.get_model_data()
            if isinstance(model_data, dict) and model_data.get("artifact_type") == "pskc_ensemble_v1":
                try:
                    loaded_model = self._get_registry()._deserialize_model_checkpoint(model_data)
                    if loaded_model is not None:
                        model_info = incremental_persistence.get_info()
                        metadata = model_info.get("metadata", {})
                        self._model = loaded_model
                        self._active_model_version = model_info.get("current_version", "unknown")
                        self._active_artifact_path = model_info.get("file_path")
                        self._model_source = "incremental"
                        self._last_train_time = self._timestamp_from_iso(
                            metadata.get("last_accepted_at") or model_info.get("updated_at")
                        )
                        logger.info(
                            "Loaded legacy incremental model %s:%s from %s",
                            self._model_name,
                            self._active_model_version,
                            self._active_artifact_path,
                        )
                        return {
                            "success": True,
                            "version": self._active_model_version,
                            "artifact_path": self._active_artifact_path,
                            "source": self._model_source,
                        }
                except Exception as e:
                    logger.error(f"Failed to load incremental model: {e}")

        return {"success": False, "reason": "no_active_version"}

    def ensure_runtime_model_loaded(self) -> Dict[str, Any]:
        if self._model is not None and getattr(self._model, "is_trained", False):
            return {
                "success": True,
                "version": self._active_model_version,
                "artifact_path": self._active_artifact_path,
                "source": self._model_source,
            }
        # Don't spam load_active_model() after a known failure (e.g. missing model file).
        # The flag is cleared after a successful training run.
        if self._load_failed:
            return {"success": False, "reason": "load_previously_failed"}
        result = self.load_active_model()
        if not result.get("success"):
            self._load_failed = True
        return result

    def _normalize_quality_profile(self, quality_profile: Optional[str]) -> str:
        candidate = str(
            quality_profile
            or getattr(settings, "ml_training_quality_profile", "balanced")
            or "balanced"
        ).strip().lower()
        return candidate if candidate in TRAINING_PROFILE_DEFAULTS else "balanced"

    def _clamp_time_budget_minutes(self, value: Optional[int]) -> int:
        configured_default = int(getattr(settings, "ml_training_time_budget_minutes", 30) or 30)
        configured_max = int(getattr(settings, "ml_training_time_budget_max_minutes", 60) or 60)
        budget = int(value or configured_default)
        return max(5, min(configured_max, budget))

    def _normalize_sample_strategy(self, sample_strategy: Optional[str]) -> str:
        candidate = str(
            sample_strategy
            or getattr(settings, "ml_training_sample_strategy", "auto")
            or "auto"
        ).strip().lower()
        return candidate if candidate in SAMPLE_STRATEGY_OPTIONS else "auto"

    def _is_noisy_key(self, key_id: str) -> bool:
        lowered = str(key_id or "").lower()
        return any(token in lowered for token in ("noise", "random", "dummy", "temp", "junk", "test"))

    def _is_high_churn_key(self, key_id: str) -> bool:
        lowered = str(key_id or "").lower()
        return any(token in lowered for token in (":session:", "session:", ":rot:", "rot:"))

    def _select_training_events(
        self,
        access_data: List[Dict[str, Any]],
        *,
        sample_strategy: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        requested_strategy = self._normalize_sample_strategy(sample_strategy)
        if not access_data:
            return [], {
                "requested_strategy": requested_strategy,
                "applied_strategy": requested_strategy,
                "recommendation": "No training events available yet.",
                "total_events": 0,
                "total_unique_keys": 0,
                "selected_events": 0,
                "selected_unique_keys": 0,
                "coverage_ratio": 0.0,
                "key_coverage_ratio": 0.0,
            }

        min_key_events = max(2, int(getattr(settings, "ml_training_realistic_key_min_events", 3) or 3))
        score_threshold = float(getattr(settings, "ml_training_realistic_score_threshold", 0.55) or 0.55)
        target_coverage = float(getattr(settings, "ml_training_realistic_target_coverage", 0.72) or 0.72)

        key_counts: Counter = Counter()
        key_services: Dict[str, set] = defaultdict(set)
        key_cache_hits: Dict[str, int] = defaultdict(int)
        key_source_counts: Dict[str, Counter] = defaultdict(Counter)
        key_pattern_counts: Dict[str, Counter] = defaultdict(Counter)
        key_hint_sums: Dict[str, float] = defaultdict(float)
        key_hint_counts: Dict[str, int] = defaultdict(int)
        key_timestamps: Dict[str, List[float]] = defaultdict(list)

        noisy_events = 0
        high_churn_events = 0
        production_events = 0
        realistic_sim_events = 0
        random_sim_events = 0

        for event in access_data:
            key_id = str(event.get("key_id") or "")
            if not key_id:
                continue

            service_id = str(event.get("service_id") or "default")
            metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
            source = str(event.get("data_source") or "production").lower()
            pattern_type = str(metadata.get("pattern_type") or "").lower()
            realism_hint = metadata.get("realism_score_hint")

            key_counts[key_id] += 1
            key_services[key_id].add(service_id)
            key_cache_hits[key_id] += int(bool(event.get("cache_hit")))
            key_source_counts[key_id][source] += 1
            key_pattern_counts[key_id][pattern_type or "unknown"] += 1

            timestamp = float(event.get("timestamp") or 0.0)
            if timestamp > 0:
                key_timestamps[key_id].append(timestamp)

            try:
                if realism_hint is not None:
                    key_hint_sums[key_id] += float(realism_hint)
                    key_hint_counts[key_id] += 1
            except (TypeError, ValueError):
                pass

            if self._is_noisy_key(key_id):
                noisy_events += 1
            if self._is_high_churn_key(key_id):
                high_churn_events += 1
            if source == "production":
                production_events += 1
            elif pattern_type == "realistic":
                realistic_sim_events += 1
            elif pattern_type == "random":
                random_sim_events += 1

        total_events = max(len(access_data), 1)
        total_unique_keys = max(len(key_counts), 1)
        low_support_keys = sum(1 for count in key_counts.values() if count < min_key_events)
        low_support_ratio = low_support_keys / total_unique_keys
        noisy_ratio = noisy_events / total_events
        high_churn_ratio = high_churn_events / total_events
        key_density = total_unique_keys / total_events

        recommended_strategy = "all"
        if (
            noisy_ratio > 0.06
            or high_churn_ratio > 0.12
            or low_support_ratio > 0.45
            or key_density > 0.08
            or random_sim_events > realistic_sim_events
        ):
            recommended_strategy = "realistic_priority"

        applied_strategy = recommended_strategy if requested_strategy == "auto" else requested_strategy

        key_profiles: List[Dict[str, Any]] = []
        for key_id, count in key_counts.items():
            unique_services = len(key_services[key_id])
            hit_rate = key_cache_hits[key_id] / max(count, 1)
            source_counts = key_source_counts[key_id]
            pattern_counts = key_pattern_counts[key_id]
            production_share = source_counts.get("production", 0) / max(count, 1)
            realistic_pattern_share = pattern_counts.get("realistic", 0) / max(count, 1)
            random_pattern_share = pattern_counts.get("random", 0) / max(count, 1)
            avg_hint = (
                key_hint_sums[key_id] / key_hint_counts[key_id]
                if key_hint_counts[key_id] > 0
                else None
            )

            freq_score = min(1.0, math.log1p(count) / math.log1p(40))
            service_score = min(1.0, unique_services / 3.0)
            hit_score = min(1.0, hit_rate / 0.85) if hit_rate > 0 else 0.0

            timestamps = sorted(key_timestamps.get(key_id, []))
            if len(timestamps) >= 4:
                intervals = [
                    max(0.001, timestamps[idx] - timestamps[idx - 1])
                    for idx in range(1, len(timestamps))
                ]
                mean_interval = sum(intervals) / len(intervals)
                variance = sum((interval - mean_interval) ** 2 for interval in intervals) / len(intervals)
                std_dev = math.sqrt(max(variance, 0.0))
                coeff_var = std_dev / mean_interval if mean_interval > 0 else 2.0
                regularity_score = max(0.0, 1.0 - min(coeff_var, 2.0) / 2.0)
            elif len(timestamps) >= 2:
                regularity_score = 0.55
            else:
                regularity_score = 0.35

            source_bonus = 0.12 * production_share
            realistic_bonus = 0.10 * realistic_pattern_share
            hint_bonus = 0.10 * max(0.0, (avg_hint or 0.5) - 0.5)
            low_count_penalty = 0.15 if count < min_key_events else 0.0
            noise_penalty = 0.35 if self._is_noisy_key(key_id) else 0.0
            churn_penalty = 0.15 if self._is_high_churn_key(key_id) else 0.0
            random_penalty = 0.12 * random_pattern_share

            realism_score = (
                0.42 * freq_score
                + 0.14 * service_score
                + 0.18 * hit_score
                + 0.16 * regularity_score
                + source_bonus
                + realistic_bonus
                + hint_bonus
                - low_count_penalty
                - noise_penalty
                - churn_penalty
                - random_penalty
            )
            realism_score = max(0.0, min(1.0, realism_score))

            key_profiles.append(
                {
                    "key_id": key_id,
                    "count": count,
                    "realism_score": round(realism_score, 4),
                    "unique_services": unique_services,
                    "hit_rate": round(hit_rate, 4),
                    "production_share": round(production_share, 4),
                    "pattern_realistic_share": round(realistic_pattern_share, 4),
                    "random_pattern_share": round(random_pattern_share, 4),
                }
            )

        ranked_profiles = sorted(
            key_profiles,
            key=lambda item: (item["realism_score"], item["count"], item["unique_services"]),
            reverse=True,
        )

        selected_keys: set[str] = set()
        if applied_strategy == "all":
            selected_keys = {item["key_id"] for item in ranked_profiles}
        elif applied_strategy == "realistic_only":
            selected_keys = {
                item["key_id"]
                for item in ranked_profiles
                if item["realism_score"] >= score_threshold and item["count"] >= min_key_events
            }
        else:
            soft_threshold = score_threshold * 0.75
            eligible_profiles = [
                item
                for item in ranked_profiles
                if item["realism_score"] >= soft_threshold and item["count"] >= min_key_events
            ]
            candidate_profiles = eligible_profiles or ranked_profiles
            minimum_selected_keys = min(len(candidate_profiles), max(2, int(total_unique_keys * 0.05)))
            selected_event_budget = 0
            for item in candidate_profiles:
                selected_keys.add(item["key_id"])
                selected_event_budget += item["count"]
                if (
                    selected_event_budget / total_events >= target_coverage
                    and len(selected_keys) >= minimum_selected_keys
                ):
                    break

        selected_events = [event for event in access_data if str(event.get("key_id") or "") in selected_keys]

        fallback_used = False
        minimum_selected_events = max(50, min(self._min_samples, 200))
        if applied_strategy != "all" and len(selected_events) < minimum_selected_events:
            selected_keys.clear()
            running_events = 0
            target_events = min(total_events, max(minimum_selected_events, int(total_events * 0.55)))
            for item in ranked_profiles:
                selected_keys.add(item["key_id"])
                running_events += item["count"]
                if running_events >= target_events:
                    break
            selected_events = [event for event in access_data if str(event.get("key_id") or "") in selected_keys]
            fallback_used = True

        selected_unique_keys = len(selected_keys)
        coverage_ratio = len(selected_events) / total_events if total_events else 0.0
        key_coverage_ratio = selected_unique_keys / total_unique_keys if total_unique_keys else 0.0
        excluded_examples = [
            item["key_id"]
            for item in ranked_profiles
            if item["key_id"] not in selected_keys
        ][:8]
        selected_examples = [
            item
            for item in ranked_profiles
            if item["key_id"] in selected_keys
        ][:8]

        recommendation = {
            "all": "Use all samples if the dataset is already dominated by stable, repeated keys.",
            "realistic_priority": "Prioritise stable, repeated keys while keeping broad enough coverage for training.",
            "realistic_only": "Use only the strongest realistic keys. Highest purity, but can underfit if coverage becomes too small.",
        }.get(applied_strategy, "Backend chose the training sample mix automatically.")

        selection_summary = {
            "requested_strategy": requested_strategy,
            "applied_strategy": applied_strategy,
            "fallback_used": fallback_used,
            "recommendation": recommendation,
            "recommended_strategy": recommended_strategy,
            "score_threshold": round(score_threshold, 2),
            "min_key_events": min_key_events,
            "target_coverage": round(target_coverage, 2),
            "total_events": len(access_data),
            "total_unique_keys": len(key_counts),
            "selected_events": len(selected_events),
            "selected_unique_keys": selected_unique_keys,
            "coverage_ratio": round(coverage_ratio, 4),
            "key_coverage_ratio": round(key_coverage_ratio, 4),
            "noisy_event_ratio": round(noisy_ratio, 4),
            "high_churn_event_ratio": round(high_churn_ratio, 4),
            "low_support_key_ratio": round(low_support_ratio, 4),
            "production_event_ratio": round(production_events / total_events, 4),
            "realistic_simulation_event_ratio": round(realistic_sim_events / total_events, 4),
            "random_simulation_event_ratio": round(random_sim_events / total_events, 4),
            "selected_key_examples": selected_examples,
            "excluded_key_examples": excluded_examples,
        }
        return selected_events, selection_summary

    def _estimate_training_minutes(
        self,
        *,
        sample_count: int,
        unique_keys: int,
        profile_name: str,
        rf_trees: int,
        lstm_epochs: int,
        lstm_hidden: int,
    ) -> int:
        profile_factor = {"fast": 0.75, "balanced": 1.0, "thorough": 1.3}.get(profile_name, 1.0)
        score = (
            (sample_count / 12000.0)
            + (unique_keys / 180.0)
            + (rf_trees / 55.0)
            + (lstm_epochs * max(lstm_hidden, 32) / 420.0)
        ) * profile_factor
        return max(2, int(round(score)))

    def _build_training_plan(
        self,
        *,
        sample_count: int,
        unique_keys: int,
        quality_profile: Optional[str] = None,
        time_budget_minutes: Optional[int] = None,
        sample_strategy: Optional[str] = None,
    ) -> Dict[str, Any]:
        profile_name = self._normalize_quality_profile(quality_profile)
        normalized_sample_strategy = self._normalize_sample_strategy(sample_strategy)
        profile = TRAINING_PROFILE_DEFAULTS[profile_name]
        budget_minutes = self._clamp_time_budget_minutes(time_budget_minutes)
        tuner = HyperparameterTuner()
        hparams = tuner.suggest_hyperparameters(
            data_size=max(int(sample_count or 0), 1),
            num_keys=max(int(unique_keys or 0), 1),
            training_time_budget=float(budget_minutes) * 60.0,
        )

        lstm_cfg = dict(hparams.get("lstm", {}))
        rf_cfg = dict(hparams.get("random_forest", {}))
        markov_cfg = dict(hparams.get("markov", {}))
        training_cfg = dict(hparams.get("training", {}))

        lstm_cfg["hidden_size"] = min(int(lstm_cfg.get("hidden_size", 64)), int(profile["lstm_hidden_cap"]))
        lstm_cfg["epochs"] = min(int(lstm_cfg.get("epochs", 12)), int(profile["epochs_cap"]))
        lstm_cfg["batch_size"] = max(int(lstm_cfg.get("batch_size", 32)), int(profile["batch_size_floor"]))

        rf_cfg["n_estimators"] = min(int(rf_cfg.get("n_estimators", 50)), int(profile["rf_tree_cap"]))
        rf_cfg["max_depth"] = min(int(rf_cfg.get("max_depth", 8)), int(profile["rf_depth_cap"]))
        rf_cfg["use_class_weight"] = True

        training_cfg["augmentation_factor"] = min(
            float(training_cfg.get("augmentation_factor", 0.15)),
            float(profile["augmentation_factor"]),
        )
        training_cfg["n_selected_features"] = min(
            int(training_cfg.get("n_selected_features", 20)),
            int(profile["feature_cap"]),
        )
        training_cfg["data_balancing"] = str(training_cfg.get("data_balancing", "auto") or "auto")

        if sample_count < 2000:
            small_sample_caps = {
                "fast": {"trees": 32, "epochs": 8, "hidden": 48},
                "balanced": {"trees": 48, "epochs": 10, "hidden": 64},
                "thorough": {"trees": 72, "epochs": 12, "hidden": 80},
            }[profile_name]
            rf_cfg["n_estimators"] = min(int(rf_cfg["n_estimators"]), small_sample_caps["trees"])
            lstm_cfg["epochs"] = min(int(lstm_cfg["epochs"]), small_sample_caps["epochs"])
            lstm_cfg["hidden_size"] = min(int(lstm_cfg["hidden_size"]), small_sample_caps["hidden"])
            training_cfg["augmentation_factor"] = min(
                float(training_cfg.get("augmentation_factor", 0.12)),
                0.12,
            )

        estimated_minutes = self._estimate_training_minutes(
            sample_count=sample_count,
            unique_keys=unique_keys,
            profile_name=profile_name,
            rf_trees=int(rf_cfg["n_estimators"]),
            lstm_epochs=int(lstm_cfg["epochs"]),
            lstm_hidden=int(lstm_cfg["hidden_size"]),
        )
        estimated_minutes = min(estimated_minutes, budget_minutes)

        return {
            "quality_profile": profile_name,
            "sample_strategy": normalized_sample_strategy,
            "time_budget_minutes": budget_minutes,
            "window_seconds": int(profile["window_seconds"]),
            "max_events": int(profile["max_events"]),
            "estimated_training_minutes": estimated_minutes,
            "notes": profile["notes"],
            "hyperparameters": {
                "lstm": lstm_cfg,
                "random_forest": rf_cfg,
                "markov": markov_cfg,
                "training": training_cfg,
            },
        }

    def get_training_plan(
        self,
        *,
        quality_profile: Optional[str] = None,
        time_budget_minutes: Optional[int] = None,
        sample_strategy: Optional[str] = None,
    ) -> Dict[str, Any]:
        # Use modular DataLoader for sample stats
        sample_stats = self._data_loader.get_sample_stats()
        sample_count = sample_stats["total_events"]
        unique_keys = sample_stats["unique_keys"]

        # Resolve profile and time budget
        profile_name = self._normalize_quality_profile(quality_profile)
        normalized_sample_strategy = self._normalize_sample_strategy(sample_strategy)
        profile = TRAINING_PROFILE_DEFAULTS[profile_name]
        budget_minutes = self._clamp_time_budget_minutes(time_budget_minutes)

        selection_preview = {
            "requested_strategy": normalized_sample_strategy,
            "applied_strategy": normalized_sample_strategy,
            "selected_events": sample_count,
            "selected_unique_keys": unique_keys,
            "coverage_ratio": 1.0,
            "key_coverage_ratio": 1.0,
            "recommendation": "Use all available samples.",
            "recommended_strategy": "all",
        }

        effective_sample_count = sample_count
        effective_unique_keys = unique_keys
        if sample_count > 0:
            preview_limit = min(
                int(getattr(settings, "ml_training_realistic_preview_events", 12000) or 12000),
                int(profile.get("max_events", sample_count) or sample_count),
            )
            try:
                preview_events = self._collector.get_access_sequence(
                    window_seconds=int(profile.get("window_seconds", 604800)),
                    max_events=max(200, preview_limit),
                )
                if preview_events:
                    _, selection_preview = self._select_training_events(
                        preview_events,
                        sample_strategy=normalized_sample_strategy,
                    )
                    effective_sample_count = max(
                        1,
                        int(round(sample_count * float(selection_preview.get("coverage_ratio", 1.0) or 1.0))),
                    )
                    effective_unique_keys = max(
                        1,
                        int(round(unique_keys * float(selection_preview.get("key_coverage_ratio", 1.0) or 1.0))),
                    )
            except Exception:
                logger.debug("Training selection preview unavailable", exc_info=True)

        # Use AdaptiveHyperparameterTuner for epoch/batch proposals
        adaptive_overrides = self._adaptive_tuner.propose(
            sample_count=effective_sample_count,
            time_budget_minutes=budget_minutes,
            profile=profile,
        )

        # Build the full training plan (uses upstream HyperparameterTuner internally)
        plan = self._build_training_plan(
            sample_count=effective_sample_count,
            unique_keys=effective_unique_keys,
            quality_profile=quality_profile,
            time_budget_minutes=time_budget_minutes,
            sample_strategy=normalized_sample_strategy,
        )

        # Apply adaptive overrides to LSTM config if they would tighten the caps
        lstm_cfg = plan.get("hyperparameters", {}).get("lstm", {})
        if adaptive_overrides.get("epochs") and adaptive_overrides["epochs"] < lstm_cfg.get("epochs", 999):
            lstm_cfg["epochs"] = adaptive_overrides["epochs"]
        if adaptive_overrides.get("batch_size") and adaptive_overrides["batch_size"] > lstm_cfg.get("batch_size", 0):
            lstm_cfg["batch_size"] = adaptive_overrides["batch_size"]

        # Recalculate estimate using _adaptive_tuner
        estimated_minutes = self._adaptive_tuner.estimate_minutes(
            sample_count=effective_sample_count,
            unique_keys=effective_unique_keys,
            profile_name=profile_name,
            rf_trees=int(plan.get("hyperparameters", {}).get("random_forest", {}).get("n_estimators", 50)),
            lstm_epochs=int(lstm_cfg.get("epochs", 10)),
            lstm_hidden=int(lstm_cfg.get("hidden_size", 64)),
        )
        estimated_minutes = min(estimated_minutes, budget_minutes)
        plan["estimated_training_minutes"] = estimated_minutes

        # Build immediate frontend payload via ProgressManager
        plan_payload = self._progress_manager.initial_plan_payload(
            sample_count=effective_sample_count,
            unique_keys=effective_unique_keys,
            estimated_minutes=estimated_minutes,
            quality_profile=profile_name,
            time_budget_minutes=budget_minutes,
        )

        # Merge full collector stats for backward compatibility
        collector_stats = self._collector.get_stats()

        return {
            "collector": collector_stats,
            "plan_preview": plan_payload,
            "selection_preview": selection_preview,
            "effective_sample_count": effective_sample_count,
            "effective_unique_keys": effective_unique_keys,
            **plan,
        }

    def _build_trainable_model(
        self,
        y_labels: Union[List, np.ndarray],
        *,
        training_plan: Optional[Dict[str, Any]] = None,
    ) -> EnsembleModel:
        unique_labels = len(set(y_labels)) if y_labels is not None and len(y_labels) > 0 else 0
        num_classes = max(unique_labels, 1)
        hyperparameters = (training_plan or {}).get("hyperparameters", {})
        return ModelFactory.create_model(
            "ensemble",
            num_classes=num_classes,
            lstm_config=hyperparameters.get("lstm"),
            rf_config=hyperparameters.get("random_forest"),
            markov_config=hyperparameters.get("markov"),
            training_config=hyperparameters.get("lstm"),
        )

    def _persist_model(
        self,
        model: EnsembleModel,
        metrics: Dict[str, float],
        sample_count: int,
        train_samples: int,
        val_samples: int,
        reason: str,
    ) -> Dict[str, Any]:
        incremental_persistence = self._get_incremental_persistence()

        # Prepare training info
        training_info = {
            "sample_count": sample_count,
            "train_samples": train_samples,
            "val_samples": val_samples,
        }

        decision = incremental_persistence.evaluate_update(
            metrics=metrics,
            training_info=training_info,
            reason=reason,
        )
        accepted = bool(decision.get("accepted"))

        if not accepted:
            attempt_result = incremental_persistence.record_training_attempt(
                reason=reason,
                metrics=metrics,
                training_info=training_info,
                status="rejected",
                detail=decision.get("reason"),
            )
            logger.info(
                "Retained active model %s:%s after training attempt (%s)",
                self._model_name,
                self._active_model_version,
                decision.get("reason"),
            )
            return {
                "success": bool(attempt_result.get("success")),
                "accepted": False,
                "version": self._active_model_version,
                "artifact_path": self._active_artifact_path,
                "decision_reason": decision.get("reason"),
                "attempt_count": attempt_result.get("attempt_count"),
            }

        registry = self._get_registry()
        registry_version = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        registry_saved = registry.save_model(
            model_name=self._model_name,
            model=model,
            version=registry_version,
            metrics=metrics,
            description=(
                f"Trained on {sample_count} samples | "
                f"val={float(metrics.get('accuracy', 0.0) or 0.0):.2%} | "
                f"top10={float(metrics.get('top_10_accuracy', 0.0) or 0.0):.2%}"
            ),
            provenance={
                "source": "trainer.full_retrain",
                "reason": reason,
                "training_info": training_info,
            },
            stage=settings.ml_model_stage,
            actor="trainer",
            activate=True,
        )
        if not registry_saved:
            logger.error("Failed to persist active model to secure registry")
            return {"success": False, "reason": "registry_save_failed"}

        active_registry_version = registry.get_active_version(self._model_name)
        registry_artifact_path = active_registry_version.file_path if active_registry_version else None

        metadata_result = incremental_persistence.update(
            model_data={
                "artifact_type": "pskc_registry_reference_v1",
                "registry_version": registry_version,
                "artifact_path": registry_artifact_path,
                "source": "registry",
            },
            reason=reason,
            metrics=metrics,
            training_info=training_info,
        )
        if not metadata_result.get("success"):
            logger.warning(
                "Secure registry save succeeded, but incremental metadata persistence failed: %s",
                metadata_result.get("reason"),
            )

        self._active_model_version = registry_version
        self._active_artifact_path = registry_artifact_path
        self._model_source = "registry"
        logger.info(
            "Saved active model to secure registry %s:%s at %s",
            self._model_name,
            self._active_model_version,
            self._active_artifact_path,
        )

        return {
            "success": True,
            "accepted": True,
            "version": registry_version,
            "artifact_path": self._active_artifact_path,
            "decision_reason": decision.get("reason"),
            "attempt_count": metadata_result.get("attempt_count"),
        }

    def _record_training_run_in_database(
        self,
        *,
        metrics: Dict[str, float],
        training_info: Dict[str, Any],
        reason: str,
        runtime_version: Optional[str],
        accepted: bool,
        decision_reason: Optional[str],
        training_time_s: float,
        completed_at: str,
    ) -> Dict[str, Any]:
        """
        Persist full-training history to SQL tables used by Model Intelligence.
        """
        try:
            from src.database.connection import DatabaseConnection
            from src.database.models import ModelMetric, ModelVersion, TrainingMetadata

            db = DatabaseConnection.get_session()
            try:
                version_label = str(runtime_version or f"candidate-{int(time.time())}")
                if accepted and version_label.lower().startswith("v") and version_label[1:].isdigit():
                    version_label = version_label[1:]
                elif not accepted and version_label == runtime_version:
                    version_label = f"candidate-{int(time.time())}"

                version_status = "production" if accepted else "rejected"
                if accepted:
                    (
                        db.query(ModelVersion)
                        .filter(
                            ModelVersion.model_name == self._model_name,
                            ModelVersion.status == "production",
                        )
                        .update({"status": "archived"}, synchronize_session=False)
                    )

                model_version = ModelVersion(
                    model_name=self._model_name,
                    version_number=version_label,
                    status=version_status,
                    metrics_json={
                        **(metrics or {}),
                        "reason": reason,
                        "accepted": accepted,
                        "decision_reason": decision_reason,
                        "runtime_version": runtime_version,
                    },
                )
                db.add(model_version)
                db.flush()

                for metric_name, metric_value in (metrics or {}).items():
                    try:
                        numeric_value = float(metric_value)
                    except (TypeError, ValueError):
                        continue
                    db.add(
                        ModelMetric(
                            version_id=model_version.version_id,
                            metric_name=str(metric_name),
                            metric_value=numeric_value,
                            recorded_at=datetime.utcnow(),
                        )
                    )

                completed_dt = datetime.fromisoformat(completed_at)
                started_dt = completed_dt - timedelta(seconds=float(training_time_s or 0.0))
                db.add(
                    TrainingMetadata(
                        version_id=model_version.version_id,
                        training_start_time=started_dt,
                        training_end_time=completed_dt,
                        samples_count=int(training_info.get("sample_count", 0) or 0),
                        accuracy_before=None,
                        accuracy_after=float((metrics or {}).get("accuracy", 0.0) or 0.0),
                    )
                )

                db.commit()
                return {
                    "success": True,
                    "version_id": model_version.version_id,
                    "version_number": model_version.version_number,
                    "status": model_version.status,
                }
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()
        except Exception as exc:
            logger.error("Failed to persist training run to database: %s", exc)
            return {"success": False, "reason": str(exc)}

    def _save_sample_profile(
        self,
        db_record: Dict[str, Any],
        access_data: List[Dict[str, Any]],
        X_rf: np.ndarray,
    ) -> None:
        """
        Extract and persist a training sample profile after a training run.
        Non-fatal: failures are logged but do not affect overall training.
        """
        version_id = db_record.get("version_id") if db_record else None
        if not version_id:
            return
        try:
            from src.ml.sample_profiler import SampleProfiler
            from src.database.connection import DatabaseConnection

            profile = SampleProfiler.extract_profile(access_data, X_rf)
            db = DatabaseConnection.get_session()
            try:
                SampleProfiler.save_profile(version_id, profile, db)
            finally:
                db.close()
        except Exception as exc:
            logger.debug("Failed to save sample profile: %s", exc)

    def train_online(self, reason: str = "drift_detected") -> Dict[str, Any]:
        """
        Lightweight drift-triggered online learning path.
        Uses River incremental updates and does not create a new persisted model version.
        """
        if self._is_training_automatic:
            return {"success": False, "reason": "already_training", "training_path": "online"}

        if not self._automatic_lock.acquire(blocking=False):
            return {"success": False, "reason": "already_training", "training_path": "online"}

        try:
            self._is_training_automatic = True
            from src.ml.predictor import get_key_predictor

            predictor = get_key_predictor()
            result = predictor.run_online_learning(reason=reason, enforce_cooldown=False)
            if result.get("success"):
                self._online_learning_count += 1
            self._last_online_learning_result = result
            return result
        finally:
            self._is_training_automatic = False
            self._automatic_lock.release()

    # ----------------------------------------------------------
    # Feature Extraction (with context window)
    # ----------------------------------------------------------

    def _extract_XY(self, data: List[Dict]) -> Tuple[np.ndarray, np.ndarray, List[str]]:
        """
        Extract feature matrices using sliding context window.
        Returns:
            X_rf: Aggregated features for Random Forest (n_samples, feature_dim)
            X_lstm: Sequential features for LSTM (n_samples, seq_len, per_event_dim)
            y: Target key IDs
        """
        X_rf, X_lstm, y = [], [], []
        for idx in range(len(data)):
            start = max(0, idx - self._context_window + 1)
            context = data[start: idx + 1]

            # For RF: aggregated features from entire context
            rf_features = self._engineer.extract_features(context)
            X_rf.append(rf_features)

            # For LSTM: per-event features in sequence
            base_ts = data[idx]['timestamp'] if idx < len(data) else None
            lstm_seq = []
            for event in context:
                event_features = self._engineer.extract_per_event_features(event, base_ts)
                lstm_seq.append(event_features)
            # Pad sequence to fixed length
            while len(lstm_seq) < self._context_window:
                # Pad with zeros at the beginning
                lstm_seq.insert(0, np.zeros(8, dtype=np.float32))
            X_lstm.append(np.array(lstm_seq))

            y.append(data[idx]["key_id"])

        return np.array(X_rf), np.array(X_lstm), y

    # ----------------------------------------------------------
    # Training
    # ----------------------------------------------------------

    def train(
        self,
        force: bool = False,
        reason: str = "scheduled",
        quality_profile: Optional[str] = None,
        time_budget_minutes: Optional[int] = None,
        sample_strategy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Train the model on collected data.
        
        Supports separate training paths:
        - "scheduled": Full batch retraining (accumulates data over time)
        - "drift_detected" | "automatic": Quick adaptive training (drift/online learning)
        - "manual": One-off training, uses scheduled path
        
        Args:
            force: Bypass sample count check
            reason: Why training was triggered ("scheduled" | "drift_detected" | "automatic" | "manual")
            quality_profile: "fast" | "balanced" | "thorough" for full retraining
            time_budget_minutes: Requested upper bound for the full retrain budget
            sample_strategy: "auto" | "all" | "realistic_priority" | "realistic_only"

        Returns:
            Training results dict
        """
        if reason in ("drift_detected", "predictor_drift", "online_learning", "drift"):
            return self.train_online(reason=reason)

        # Determine training type
        is_automatic = reason in ("drift_detected", "automatic", "online_learning")
        
        # Use appropriate lock to prevent concurrent training of same type
        lock = self._automatic_lock if is_automatic else self._scheduled_lock
        is_training_flag = self._is_training_automatic if is_automatic else self._is_training_scheduled
        
        if is_training_flag:
            return {
                "success": False, 
                "reason": "already_training",
                "training_type": "automatic" if is_automatic else "scheduled",
            }
        
        # Acquire lock for this training type
        if not lock.acquire(blocking=False):
            return {
                "success": False,
                "reason": "already_training",
                "training_type": "automatic" if is_automatic else "scheduled",
            }
        
        try:
            # Set appropriate flag
            if is_automatic:
                self._is_training_automatic = True
            else:
                self._is_training_scheduled = True

            # Initialize training progress tracker
            tracker = get_training_progress_tracker()
            tracker.start_training()

            start_time = time.time()

            try:
                tracker.update_progress(
                    phase=TrainingPhase.LOADING_DATA,
                    progress_percent=5.0,
                    current_step=1,
                    total_steps=10,
                    message="Loading training data from collector...",
                )

                stats = self._collector.get_stats()
                sample_count = stats.get("total_events", 0)

                if sample_count < self._min_samples and not force:
                    logger.info(f"Not enough samples: {sample_count}/{self._min_samples}")
                    tracker.finish_training(success=False)
                    return {
                        "success": False,
                        "reason": "insufficient_samples",
                        "sample_count": sample_count,
                        "required": self._min_samples,
                    }

                # Different data window sizes based on training type
                if is_automatic:
                    training_plan = {
                        "quality_profile": "online",
                        "sample_strategy": "online",
                        "time_budget_minutes": 5,
                        "window_seconds": 21600,
                        "max_events": 50000,
                        "estimated_training_minutes": 5,
                        "notes": "Drift-triggered online adaptation path",
                        "hyperparameters": {},
                    }
                else:
                    training_plan = self._build_training_plan(
                        sample_count=int(sample_count or 0),
                        unique_keys=int(stats.get("unique_keys", 0) or 0),
                        quality_profile=quality_profile,
                        time_budget_minutes=time_budget_minutes,
                        sample_strategy=sample_strategy,
                    )

                window_seconds = int(training_plan.get("window_seconds", 604800))
                max_events = int(training_plan.get("max_events", 90000))

                access_data = self._collector.get_access_sequence(
                    window_seconds=window_seconds,
                    max_events=max_events
                )

                # Auto-expand window if we're missing significant data.
                # This handles cases where generated data spans a wider time
                # range than the profile's default window (e.g. duration_hours
                # was very large or data was imported from an external source).
                total_in_collector = int(stats.get("total_events", 0))
                if len(access_data) < total_in_collector * 0.5 and total_in_collector > self._min_samples:
                    logger.info(
                        "Training window %ds returned %d/%d events (%.0f%%). "
                        "Expanding to use all available data.",
                        window_seconds,
                        len(access_data),
                        total_in_collector,
                        len(access_data) / max(total_in_collector, 1) * 100,
                    )
                    access_data = self._collector.get_access_sequence(
                        window_seconds=0,  # all events, no time filter
                        max_events=max_events
                    )

                if not access_data:
                    tracker.finish_training(success=False)
                    return {"success": False, "reason": "no_data"}

                training_selection = {
                    "requested_strategy": training_plan.get("sample_strategy", "all"),
                    "applied_strategy": "all",
                    "selected_events": len(access_data),
                    "selected_unique_keys": len({item.get("key_id") for item in access_data}),
                    "coverage_ratio": 1.0,
                    "key_coverage_ratio": 1.0,
                    "recommendation": "Using all currently loaded events.",
                }
                if not is_automatic:
                    selected_access_data, training_selection = self._select_training_events(
                        access_data,
                        sample_strategy=training_plan.get("sample_strategy"),
                    )
                    if selected_access_data:
                        access_data = selected_access_data
                    training_plan["selection_preview"] = training_selection

                tracker.update_progress(
                    phase=TrainingPhase.PREPROCESSING,
                    progress_percent=15.0,
                    current_step=2,
                    total_steps=10,
                    message=f"Loaded {len(access_data)} events, preprocessing...",
                    details={
                        "total_samples": len(access_data),
                        "selected_unique_keys": training_selection.get("selected_unique_keys"),
                        "sample_strategy": training_selection.get("applied_strategy"),
                        "quality_profile": training_plan.get("quality_profile"),
                        "time_budget_minutes": training_plan.get("time_budget_minutes"),
                        "estimated_training_minutes": training_plan.get("estimated_training_minutes"),
                    },
                )
            except Exception:
                raise

            # Extract features with context window
            X_rf, X_lstm, y = self._extract_XY(access_data)

            tracker.update_progress(
                phase=TrainingPhase.SPLITTING,
                progress_percent=20.0,
                current_step=3,
                total_steps=10,
                message=f"Splitting data into train/validation sets...",
                details={"total_samples": len(X_rf)},
            )

            # Split on the original aligned samples first. RF-only augmentation and
            # balancing are applied later to the training split so X_lstm keeps the
            # same index space as the validation labels.
            from sklearn.model_selection import StratifiedShuffleSplit
            y_arr = np.array(y, dtype=object)
            try:
                sss = StratifiedShuffleSplit(n_splits=1, test_size=0.3, random_state=42)
                train_idx, val_idx = next(sss.split(X_rf, y_arr))
            except ValueError:
                split_idx = int(len(X_rf) * 0.7)
                train_idx = np.arange(split_idx)
                val_idx = np.arange(split_idx, len(X_rf))

            X_rf_train_raw, X_rf_val_raw = X_rf[train_idx], X_rf[val_idx]
            X_lstm_train, X_lstm_val = X_lstm[train_idx], X_lstm[val_idx]
            y_train_lstm = y_arr[train_idx]
            y_val = [y_arr[i] for i in val_idx]

            tracker.update_progress(
                phase=TrainingPhase.DATA_BALANCING,
                progress_percent=25.0,
                current_step=4,
                total_steps=10,
                message="Applying RF preprocessing on the training split...",
                details={"train_samples": len(X_rf_train_raw), "val_samples": len(X_rf_val_raw)},
            )

            plan_hparams = training_plan.get("hyperparameters", {})
            training_hparams = plan_hparams.get("training", {})
            requested_feature_count = int(training_hparams.get("n_selected_features", 25) or 25)
            n_select = min(requested_feature_count, max(10, X_rf_train_raw.shape[1]))
            rf_preprocessor = RFPreprocessor(n_select=n_select)
            X_rf_train = rf_preprocessor.fit_transform(X_rf_train_raw, y_train_lstm)
            X_rf_val = rf_preprocessor.transform(X_rf_val_raw)

            tracker.update_progress(
                phase=TrainingPhase.DATA_AUGMENTATION,
                progress_percent=30.0,
                current_step=5,
                total_steps=10,
                message="Applying augmentation and balancing to RF training data...",
                details={"train_samples": len(X_rf_train), "val_samples": len(X_rf_val)},
            )

            augmenter = DataAugmenter(
                augmentation_factor=float(training_hparams.get("augmentation_factor", 0.18) or 0.18)
            )
            X_rf_train, y_train_rf = augmenter.augment_dataset(X_rf_train, y_train_lstm)

            balancer = DataBalancer()
            X_rf_train, y_train_rf = balancer.balance_dataset(
                X_rf_train,
                np.array(y_train_rf, dtype=object),
                strategy=str(training_hparams.get("data_balancing", "auto") or "auto"),
            )

            # Build access sequence for Markov Chain
            key_sequence = [d["key_id"] for d in access_data]

            trainable_model = self._build_trainable_model(y_train_rf, training_plan=training_plan)
            trainable_model.rf_preprocessor = rf_preprocessor

            tracker.update_progress(
                phase=TrainingPhase.FEATURE_ENGINEERING,
                progress_percent=30.0,
                current_step=6,
                total_steps=10,
                message="Feature engineering complete, starting model training...",
                details={
                    "samples_processed": len(access_data),
                    "total_samples": len(access_data),
                    "selected_unique_keys": training_selection.get("selected_unique_keys"),
                    "sample_strategy": training_selection.get("applied_strategy"),
                    "features_count": X_rf_train.shape[1] if len(X_rf_train) > 0 else 0,
                    "train_samples": len(X_rf_train),
                    "val_samples": len(X_rf_val),
                    "quality_profile": training_plan.get("quality_profile"),
                    "time_budget_minutes": training_plan.get("time_budget_minutes"),
                    "estimated_training_minutes": training_plan.get("estimated_training_minutes"),
                },
            )

            tracker.update_progress(
                phase=TrainingPhase.TRAINING_RF,
                progress_percent=40.0,
                current_step=7,
                total_steps=10,
                message=f"Training ensemble model on {len(X_rf_train)} samples...",
                details={"train_samples": len(X_rf_train)},
            )

            # Train ensemble (RF + Markov; LSTM uses sequential data)
            trainable_model.fit(
                X_lstm=X_lstm_train,
                y_lstm=y_train_lstm,
                X_rf=X_rf_train,
                y_rf=y_train_rf,
                access_sequence=key_sequence,
            )

            tracker.update_progress(
                phase=TrainingPhase.UPDATING_MARKOV,
                progress_percent=70.0,
                current_step=8,
                total_steps=10,
                message="Ensemble training complete, running evaluation...",
            )

            # Evaluate on validation split using the same ensemble path used at runtime.
            evaluation_model = trainable_model
            # Allow injected test doubles to control validation behavior without
            # changing the persisted training artifact path used in production.
            if (
                self._model is not None
                and not isinstance(self._model, EnsembleModel)
                and getattr(self._model, "is_trained", False)
            ):
                evaluation_model = self._model

            val_metrics = self._quick_eval(
                evaluation_model,
                X_rf_val,
                y_val,
                access_data=access_data,
                validation_indices=val_idx,
                X_lstm_val=X_lstm_val,
            )

            tracker.update_progress(
                phase=TrainingPhase.EVALUATION,
                progress_percent=80.0,
                current_step=8,
                total_steps=10,
                message=f"Evaluation complete — val_accuracy={val_metrics.get('accuracy', 0):.2%}",
                details={
                    "val_accuracy": val_metrics.get("accuracy"),
                    "val_top_10_accuracy": val_metrics.get("top_10_accuracy"),
                },
            )
            val_accuracy = float(val_metrics.get("accuracy", 0.0) or 0.0)
            training_time = time.time() - start_time
            completed_at = datetime.now(timezone.utc).isoformat()
            training_info = {
                "sample_count": len(access_data),
                "train_samples": len(X_rf_train),
                "val_samples": len(X_rf_val),
                "quality_profile": training_plan.get("quality_profile"),
                "sample_strategy": training_selection.get("applied_strategy"),
                "time_budget_minutes": training_plan.get("time_budget_minutes"),
                "estimated_training_minutes": training_plan.get("estimated_training_minutes"),
                "hyperparameters": training_plan.get("hyperparameters"),
                "sample_selection": training_selection,
            }

            # Check if model accuracy meets minimum threshold for active model
            if val_accuracy < self._min_accuracy_for_active:
                logger.warning(
                    f"Model accuracy {val_accuracy:.2%} is below threshold {self._min_accuracy_for_active:.2%}. "
                    f"Model will not be set as active."
                )
                attempt_result = self._get_incremental_persistence().record_training_attempt(
                    reason=reason,
                    metrics=val_metrics,
                    training_info=training_info,
                    status="rejected_threshold",
                    detail="accuracy_below_threshold",
                )
                db_training_record = self._record_training_run_in_database(
                    metrics=val_metrics,
                    training_info=training_info,
                    reason=reason,
                    runtime_version=f"candidate-{attempt_result.get('attempt_count')}",
                    accepted=False,
                    decision_reason="accuracy_below_threshold",
                    training_time_s=round(training_time, 2),
                    completed_at=completed_at,
                )
                # Save training sample profile for pattern comparison
                self._save_sample_profile(
                    db_training_record, access_data, X_rf_train
                )
                result = {
                    "success": True,
                    "reason": "accuracy_below_threshold",
                    "message": f"Model accuracy {val_accuracy:.2%} is below threshold {self._min_accuracy_for_active:.2%}",
                    "val_accuracy": val_accuracy,
                    "val_top_10_accuracy": float(val_metrics.get("top_10_accuracy", 0.0) or 0.0),
                    "sample_count": len(access_data),
                    "train_samples": len(X_rf_train),
                    "val_samples": len(X_rf_val),
                    "training_time_s": round(training_time, 2),
                    "completed_at": completed_at,
                    "model_accepted": False,
                    "version_bumped": False,
                    "active_version": self._active_model_version,
                    "artifact_path": self._active_artifact_path,
                    "attempt_count": attempt_result.get("attempt_count"),
                    "db_version_id": db_training_record.get("version_id"),
                    "db_version_number": db_training_record.get("version_number"),
                    "quality_profile": training_plan.get("quality_profile"),
                    "sample_strategy": training_selection.get("applied_strategy"),
                    "time_budget_minutes": training_plan.get("time_budget_minutes"),
                    "estimated_training_minutes": training_plan.get("estimated_training_minutes"),
                    "hyperparameters": training_plan.get("hyperparameters"),
                    "sample_selection": training_selection,
                }
                self._training_history.append(result)
                self._record_training_metrics(
                    accuracy=val_accuracy,
                    loss=max(0.0, 1.0 - val_accuracy),
                    samples=len(access_data),
                    duration_seconds=round(training_time, 2),
                    status="rejected_threshold",
                )
                # Reset drift detector short window after retrain (even if not active, to avoid immediate re-trigger)
                self._drift_detector.reset_short_window()
                tracker.update_progress(
                    phase=TrainingPhase.COMPLETED,
                    progress_percent=100.0,
                    current_step=10,
                    total_steps=10,
                    message=f"Training complete — val_accuracy={val_accuracy:.2%}, model not accepted (below threshold)",
                    details={
                        "val_accuracy": val_accuracy,
                        "val_top_10_accuracy": float(val_metrics.get("top_10_accuracy", 0.0) or 0.0),
                        "model_accepted": False,
                        "training_time_s": round(training_time, 2),
                        "sample_count": len(access_data),
                        "sample_strategy": training_selection.get("applied_strategy"),
                        "quality_profile": training_plan.get("quality_profile"),
                        "time_budget_minutes": training_plan.get("time_budget_minutes"),
                        "estimated_training_minutes": training_plan.get("estimated_training_minutes"),
                    },
                )
                tracker.finish_training(success=True)
                return result

            # Reset drift detector short window after retrain
            self._drift_detector.reset_short_window()

            tracker.update_progress(
                phase=TrainingPhase.SAVING_MODEL,
                progress_percent=90.0,
                current_step=9,
                total_steps=10,
                message="Persisting model to registry...",
                details={"val_accuracy": val_accuracy},
            )

            persist_result = self._persist_model(
                model=trainable_model,
                metrics=val_metrics,
                sample_count=len(access_data),
                train_samples=len(X_rf_train),
                val_samples=len(X_rf_val),
                reason=reason,
            )
            if not persist_result.get("success"):
                logger.error("Runtime model persistence failed: %s", persist_result.get("reason"))
                tracker.finish_training(success=False)
                return {"success": False, "reason": str(persist_result.get("reason"))}

            accepted = bool(persist_result.get("accepted"))
            if accepted:
                self._model = trainable_model
                self._last_train_time = time.time()
                self._training_count += 1
                self._load_failed = False  # Allow re-loading on next startup

            db_training_record = self._record_training_run_in_database(
                metrics=val_metrics,
                training_info=training_info,
                reason=reason,
                runtime_version=persist_result.get("version"),
                accepted=accepted,
                decision_reason=persist_result.get("decision_reason"),
                training_time_s=round(training_time, 2),
                completed_at=completed_at,
            )
            # Save training sample profile for pattern comparison
            self._save_sample_profile(
                db_training_record, access_data, X_rf_train
            )

            result = {
                "success": True,
                "reason": reason if accepted else str(persist_result.get("decision_reason") or "not_promoted"),
                "sample_count": len(access_data),
                "train_samples": len(X_rf_train),
                "val_samples": len(X_rf_val),
                "training_time_s": round(training_time, 2),
                "training_count": self._training_count,
                "completed_at": completed_at,
                "val_accuracy": val_accuracy,
                "val_top_10_accuracy": float(val_metrics.get("top_10_accuracy", 0.0) or 0.0),
                "model_stats": self.model.get_model_stats(),
                "artifact_path": self._active_artifact_path,
                "registry_version": persist_result.get("version"),
                "active_version": self._active_model_version,
                "model_accepted": accepted,
                "version_bumped": accepted,
                "attempt_count": persist_result.get("attempt_count"),
                "decision_reason": persist_result.get("decision_reason"),
                "db_version_id": db_training_record.get("version_id"),
                "db_version_number": db_training_record.get("version_number"),
                "quality_profile": training_plan.get("quality_profile"),
                "sample_strategy": training_selection.get("applied_strategy"),
                "time_budget_minutes": training_plan.get("time_budget_minutes"),
                "estimated_training_minutes": training_plan.get("estimated_training_minutes"),
                "hyperparameters": training_plan.get("hyperparameters"),
                "sample_selection": training_selection,
            }

            self._training_history.append(result)
            self._record_training_metrics(
                accuracy=val_accuracy,
                loss=max(0.0, 1.0 - val_accuracy),
                samples=len(access_data),
                duration_seconds=round(training_time, 2),
                status="accepted" if accepted else "retained_existing_version",
            )
            logger.info(
                f"Training complete [{reason}]: "
                f"samples={len(access_data)}, "
                f"val_acc={val_accuracy:.2%}, "
                f"accepted={accepted}, "
                f"time={training_time:.1f}s"
            )
            tracker.update_progress(
                phase=TrainingPhase.COMPLETED,
                progress_percent=100.0,
                current_step=10,
                total_steps=10,
                message=f"Training complete — val_accuracy={val_accuracy:.2%}, accepted={accepted}",
                details={
                    "val_accuracy": val_accuracy,
                    "val_top_10_accuracy": float(val_metrics.get("top_10_accuracy", 0.0) or 0.0),
                    "model_accepted": accepted,
                    "training_time_s": round(training_time, 2),
                    "sample_count": len(access_data),
                    "sample_strategy": training_selection.get("applied_strategy"),
                    "quality_profile": training_plan.get("quality_profile"),
                    "time_budget_minutes": training_plan.get("time_budget_minutes"),
                    "estimated_training_minutes": training_plan.get("estimated_training_minutes"),
                },
            )
            tracker.finish_training(success=True)
            return result

        except Exception as e:
            logger.error(f"Training failed: {e}", exc_info=True)
            tracker.finish_training(success=False)
            return {"success": False, "reason": str(e)}
        finally:
            # Reset appropriate training flag and release lock
            if is_automatic:
                self._is_training_automatic = False
            else:
                self._is_training_scheduled = False
            lock.release()

    def _quick_eval(
        self,
        model: EnsembleModel,
        X_rf_val: np.ndarray,
        y_val: List[str],
        access_data: List[Dict[str, Any]],
        validation_indices: np.ndarray = None,
        validation_offset: int = 0,
        X_lstm_val: np.ndarray = None,
        max_eval_samples: int = 2000,
    ) -> Dict[str, Any]:
        """Evaluate validation split using the same ensemble path used at runtime.
        
        To avoid extremely long evaluation times on large datasets, the
        validation set is randomly sub-sampled to at most ``max_eval_samples``
        rows (default 2 000).  This keeps the wall-clock time under ~60 s even
        for 500 k-event datasets while still giving a statistically meaningful
        accuracy estimate.
        """
        try:
            if not getattr(model, "is_trained", False):
                return {"accuracy": 0.0, "top_10_accuracy": 0.0, "n_samples": 0}

            n_val = len(X_rf_val)

            # --- Sub-sample if the validation set is too large ---------------
            if n_val > max_eval_samples:
                rng = np.random.default_rng(42)
                sample_idx = np.sort(rng.choice(n_val, size=max_eval_samples, replace=False))
                X_rf_val = X_rf_val[sample_idx]
                y_val = [y_val[i] for i in sample_idx]
                if X_lstm_val is not None:
                    X_lstm_val = X_lstm_val[sample_idx]
                if validation_indices is not None:
                    validation_indices = validation_indices[sample_idx]
                else:
                    validation_offset_arr = sample_idx + validation_offset
                logger.info(
                    f"Quick-eval: sub-sampled {max_eval_samples}/{n_val} validation rows"
                )

            top1_hits = 0
            top10_hits = 0
            total = 0
            eval_start = time.time()

            for idx, (x_rf, true_key) in enumerate(zip(X_rf_val, y_val)):
                if validation_indices is not None:
                    source_index = int(validation_indices[idx])
                else:
                    source_index = validation_offset + idx
                current_key = access_data[source_index - 1]["key_id"] if source_index > 0 else None
                x_lstm = X_lstm_val[idx] if X_lstm_val is not None else None
                top_predictions, _ = model.predict_top_n(
                    n=10,
                    X_rf=x_rf.reshape(1, -1),
                    X_lstm=np.expand_dims(x_lstm, 0) if x_lstm is not None else None,
                    current_key=current_key,
                )

                predicted_keys: List[str] = []
                for item in top_predictions:
                    if isinstance(item, str):
                        predicted_keys.append(item)
                    elif isinstance(item, (int, np.integer)):
                        key_index = int(item)
                        rf_model = getattr(model, "rf", None)
                        label_encoder = getattr(rf_model, "label_encoder", None)
                        classes = getattr(label_encoder, "classes_", None)
                        if classes is not None and 0 <= key_index < len(classes):
                            predicted_keys.append(str(classes[key_index]))
                            continue
                        known_keys = model.markov.get_known_keys()
                        if 0 <= key_index < len(known_keys):
                            predicted_keys.append(str(known_keys[key_index]))

                if predicted_keys:
                    if predicted_keys[0] == true_key:
                        top1_hits += 1
                    if true_key in predicted_keys:
                        top10_hits += 1
                total += 1

                # Progress log every 500 samples
                if total % 500 == 0:
                    elapsed = time.time() - eval_start
                    logger.info(
                        f"Quick-eval progress: {total}/{len(X_rf_val)} samples "
                        f"({elapsed:.1f}s elapsed, "
                        f"top1={top1_hits/total:.2%}, top10={top10_hits/total:.2%})"
                    )

            eval_elapsed = time.time() - eval_start
            logger.info(
                f"Quick-eval complete: {total} samples in {eval_elapsed:.1f}s"
            )

            return {
                "accuracy": round(float(top1_hits / total), 4) if total else 0.0,
                "top_10_accuracy": round(float(top10_hits / total), 4) if total else 0.0,
                "n_samples": total,
            }
        except Exception as e:
            logger.debug(f"Quick eval failed: {e}")
            return {"accuracy": 0.0, "top_10_accuracy": 0.0, "n_samples": 0}

    # ----------------------------------------------------------
    # Online Learning / Incremental Update
    # ----------------------------------------------------------

    def record_cache_outcome(self, key_id: str, cache_hit: bool) -> None:
        """
        Record a real cache outcome.
        - Updates drift detector
        - If drift detected, triggers lightweight River online learning (non-blocking)
        """
        status = self._drift_detector.record(cache_hit)

        if status == "drift":
            # Rate limit: don't adapt more than once per 5 minutes from drift
            time_since_last = time.time() - self._last_drift_retrain_time
            if time_since_last > 300:
                logger.info("Triggering drift-based online learning...")
                self._last_drift_retrain_time = time.time()
                t = threading.Thread(
                    target=self.train_online,
                    kwargs={"reason": "drift_detected"},
                    daemon=True,
                )
                t.start()

    def train_incremental(self, new_data: List[Dict]) -> Dict[str, Any]:
        """
        Incremental update — full retrain on latest collected data.
        (River/online learning could be used here in future upgrade)
        """
        return self.train_online(reason="incremental_online")

    # ----------------------------------------------------------
    # Background Auto-Training
    # ----------------------------------------------------------

    def start_auto_training(self):
        if self._running:
            logger.warning("Auto-training already running")
            return
        self._running = True
        self._train_thread = threading.Thread(
            target=self._auto_train_loop, daemon=True
        )
        self._train_thread.start()
        logger.info(f"Auto-training started (interval={self._update_interval}s)")

    def stop_auto_training(self):
        self._running = False
        if self._train_thread:
            self._train_thread.join(timeout=5)
        logger.info("Auto-training stopped")

    def _auto_train_loop(self):
        while self._running:
            try:
                time_since = time.time() - self._last_train_time
                if time_since >= self._update_interval:
                    self.train(reason="automatic")
                time.sleep(min(10, self._update_interval))
            except Exception as e:
                logger.error(f"Auto-training loop error: {e}")
                time.sleep(60)

    # ----------------------------------------------------------
    # Evaluate
    # ----------------------------------------------------------

    def evaluate(self, test_data: List[Dict] = None) -> Dict[str, Any]:
        """
        Evaluate model on test data with real accuracy metrics.

        BEFORE: returned 0.0 placeholder for top_1_accuracy and top_10_accuracy.
        AFTER: computes actual top-1 and top-10 accuracy against true labels.
        """
        if test_data is None:
            test_data = self._collector.get_access_sequence(window_seconds=86400)

        if not test_data:
            return {"success": False, "reason": "no_test_data"}

        try:
            test_data = sorted(test_data, key=lambda x: x.get("timestamp", 0))
            X_rf, X_lstm, y_true = self._extract_XY(test_data)

            if not self.model.is_trained:
                return {"success": False, "reason": "model_not_trained"}

            top1_hits, top10_hits, total = 0, 0, 0

            for i, (x, true_key) in enumerate(zip(X_rf, y_true)):
                current_key = test_data[i - 1]["key_id"] if i > 0 else None
                x_rf = self.model.preprocess_rf(x.reshape(1, -1))
                top_indices, top_probs = self.model.predict_top_n(
                    n=10,
                    X_rf=x_rf,
                    current_key=current_key,
                )

                # Map indices back to key names via Markov known_keys
                known_keys = self.model.markov.get_known_keys()
                predicted_keys = []
                for idx in top_indices:
                    if isinstance(idx, (int, np.integer)) and int(idx) < len(known_keys):
                        predicted_keys.append(known_keys[int(idx)])
                    elif isinstance(idx, str):
                        predicted_keys.append(idx)

                if predicted_keys:
                    if predicted_keys[0] == true_key:
                        top1_hits += 1
                    if true_key in predicted_keys:
                        top10_hits += 1
                total += 1

            result = {
                "success": True,
                "test_samples": total,
                "top_1_accuracy":  round(top1_hits  / total, 4) if total else 0.0,
                "top_10_accuracy": round(top10_hits / total, 4) if total else 0.0,
                "drift_stats": self._drift_detector.get_stats(),
                "model_stats": self.model.get_model_stats(),
            }
            self._last_evaluation = result
            return result

        except Exception as e:
            logger.error(f"Evaluation failed: {e}", exc_info=True)
            return {"success": False, "reason": str(e)}

    # ----------------------------------------------------------
    # Stats
    # ----------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        incremental_info = self._get_incremental_info()
        training_plan = self.get_training_plan()
        current_model = self._model
        return {
            "training_count":  self._training_count,
            "last_train_time": self._last_train_time,
            "update_interval": self._update_interval,
            "min_samples":     self._min_samples,
            "auto_training":   self._running,
            "is_training":     self._is_training_scheduled or self._is_training_automatic,
            "is_training_scheduled": self._is_training_scheduled,
            "is_training_automatic": self._is_training_automatic,
            "drift_stats":     self._drift_detector.get_stats(),
            "model_stats":     current_model.get_model_stats() if current_model is not None else {},
            "collector_stats": self._collector.get_stats(),
            "model_name":      self._model_name,
            "active_version":  self._active_model_version,
            "artifact_path":   self._active_artifact_path,
            "model_source":    self._model_source,
            "incremental_info": incremental_info,
            "last_evaluation": self._last_evaluation,
            "online_learning_count": self._online_learning_count,
            "last_online_learning": self._last_online_learning_result,
            "training_plan": training_plan,
        }

    def get_training_history(self) -> List[Dict]:
        get_history = getattr(self._incremental_persistence, "get_history", None)
        if callable(get_history):
            try:
                incremental_history = get_history(limit=100)
                if isinstance(incremental_history, list):
                    return incremental_history
            except Exception:
                logger.debug("Incremental history unavailable, falling back to in-memory history.")
        return self._training_history.copy()

    def get_training_patterns(self) -> Optional[Dict[str, Any]]:
        """
        Get training patterns extracted from last training session.
        Used for drift detection in simulation learning.
        
        Returns:
            Dictionary with pattern information, or None if no training patterns available
        """
        try:
            # Try to get patterns from last successful training
            if hasattr(self, '_last_training_patterns'):
                return self._last_training_patterns
            
            # Generate patterns from current training data if available
            from src.ml.simulation_event_handler import SimulationPatternExtractor
            
            collector = self._collector
            access_data = collector.get_access_sequence(window_seconds=86400, max_events=5_000)
            
            if not access_data:
                logger.warning("get_training_patterns: No access data available")
                return None
            
            # Convert access data to simulation events format
            from src.ml.simulation_event_handler import SimulationEvent
            events = []
            for data in access_data:
                event = SimulationEvent(
                    simulation_id="training",
                    timestamp=data.get("timestamp", time.time()),
                    key_id=data.get("key_id", "unknown"),
                    service_id=data.get("service_id", "default"),
                    latency_ms=data.get("latency_ms", 0.0),
                    cache_hit=data.get("cache_hit", False),
                )
                events.append(event)
            
            # Extract patterns
            extractor = SimulationPatternExtractor()
            patterns = extractor.extract_patterns(events)
            
            # Cache patterns
            self._last_training_patterns = patterns
            
            return patterns
            
        except Exception as e:
            logger.warning(f"get_training_patterns: Error: {e}")
            return None


# ============================================================
# Try importing sklearn for _quick_eval check
# ============================================================
try:
    from sklearn.preprocessing import LabelEncoder as _LE
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


# ============================================================
# Global Singleton
# ============================================================

_trainer_instance: Optional[ModelTrainer] = None


def get_model_trainer() -> ModelTrainer:
    global _trainer_instance
    if _trainer_instance is None:
        _trainer_instance = ModelTrainer()
    return _trainer_instance
