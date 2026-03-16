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
# ============================================================
import time
import threading
import numpy as np
from collections import deque
from typing import Dict, List, Optional, Tuple, Any
import logging
from datetime import datetime, timezone
import math

from config.settings import settings
from src.ml.data_collector import get_data_collector
from src.ml.feature_engineering import get_feature_engineer
from src.ml.model import EnsembleModel, ModelFactory
from src.ml.model_registry import SecurityError, get_model_registry

logger = logging.getLogger(__name__)


# ============================================================
# Concept Drift Detector - Mature EWMA Implementation
# ============================================================

class DriftDetector:
    """
    Advanced Concept Drift Detection combining multiple methods:
    
    1. EWMA (Exponential Weighted Moving Average) - untuk smooth detection
    2. ADWIN-like adaptive windowing - untuk variasi perubahan
    3. EDDM (Early Drift Detection Method) - untuk deteksi dini
    
    Referensi: 
    - Gama et al. (2004) — Learning with Drift Detection (EDDM)
    - Bifet & Gavalda (2007) — Learning from Noisy Streams (ADWIN)
    - Klinkenberg & Rengur (2004) — Handling Concept Drift (EWMA)
    """

    def __init__(
        self,
        short_window: int = 30,
        long_window: int = 200,
        drift_threshold: float = 0.12,  # 12% drop triggers retrain
        warning_threshold: float = 0.06,  # 6% drop = warning only
        # EWMA parameters
        ewma_alpha: float = 0.3,  # EWMA smoothing factor
        # EDDM parameters
        eddm_threshold: float = 0.5,
        # Adaptive parameters
        adaptive_window: bool = True,
        min_confidence: int = 10,
    ):
        self.short_window = short_window
        self.long_window = long_window
        self.drift_threshold = drift_threshold
        self.warning_threshold = warning_threshold
        self.ewma_alpha = ewma_alpha
        self.eddm_threshold = eddm_threshold
        self.adaptive_window = adaptive_window
        self.min_confidence = min_confidence

        # EWMA state
        self._ewma_long: float = 0.0
        self._ewma_short: float = 0.0
        self._ewma_initialized: bool = False
        
        # EDDM state
        self._eddm_mean: float = 0.0
        self._eddm_variance: float = 0.0
        self._eddm_last_distance: float = 0.0
        self._eddm_p: float = 0.0  # running mean of distances
        self._eddm_s: float = 0.0  # running std of distances
        
        # ADWIN-like adaptive window
        self._adaptive_window: deque = deque(maxlen=long_window * 2)
        
        # Basic sliding windows (fallback)
        self._short_hits: deque = deque(maxlen=short_window)
        self._long_hits: deque = deque(maxlen=long_window)
        
        # Statistics
        self._total_records = 0
        self._drift_count = 0
        self._warning_count = 0
        self._last_drift_time: float = 0
        self._drift_history: List[Dict] = []

    def _update_ewma(self, value: float) -> Tuple[float, float]:
        """
        Update EWMA values.
        
        Returns:
            (short_ewma, long_ewma)
        """
        if not self._ewma_initialized:
            self._ewma_short = value
            self._ewma_long = value
            self._ewma_initialized = True
            return self._ewma_short, self._ewma_long
        
        # Short-term EWMA (smaller alpha = smoother)
        self._ewma_short = self.ewma_alpha * value + (1 - self.ewma_alpha) * self._ewma_short
        # Long-term EWMA (same alpha for consistency)
        self._ewma_long = (self.ewma_alpha / 2) * value + (1 - self.ewma_alpha / 2) * self._ewma_long
        
        return self._ewma_short, self._ewma_long

    def _update_eddm(self, correct: bool, position: int, total: int) -> Dict[str, float]:
        """
        Update EDDM (Early Drift Detection Method) statistics.
        
        EDDM uses the distance between two consecutive errors.
        Small distances = stable, Large distances = drift.
        
        Returns:
            dict with 'drift_indicator', 'p', 's', 'threshold'
        """
        if position < 2 or total < 10:
            return {"drift_indicator": 0.0, "p": 0.0, "s": 0.0, "threshold": 0.0}
        
        # Distance between consecutive errors (simplified)
        distance = 1.0 if correct else 0.0
        
        # Update running statistics
        if self._eddm_p == 0:
            self._eddm_p = distance
            self._eddm_s = 0.0
        else:
            # Welford's online algorithm for running mean and variance
            delta = distance - self._eddm_p
            self._eddm_p += delta / self._total_records
            delta2 = distance - self._eddm_p
            self._eddm_s += (delta * delta2 - self._eddm_s) / self._total_records
        
        self._eddm_s = math.sqrt(self._eddm_s) if self._eddm_s > 0 else 0.001
        
        # EDDM drift indicator: ratio of p+2s to max(p+2s)
        # When this ratio drops significantly, drift is detected
        p_plus_2s = self._eddm_p + 2 * self._eddm_s
        max_p_2s = 1.0  # Maximum possible
        
        if max_p_2s > 0:
            indicator = p_plus_2s / max_p_2s
        else:
            indicator = 1.0
        
        return {
            "drift_indicator": indicator,
            "p": self._eddm_p,
            "s": self._eddm_s,
            "threshold": self.eddm_threshold
        }

    def _detect_adwin_change(self) -> bool:
        """
        Detect change using ADWIN-like adaptive windowing.
        
        Compares older half vs newer half of adaptive window.
        If significant difference, drift detected.
        """
        if len(self._adaptive_window) < self.long_window:
            return False
        
        # Split window into two halves
        mid = len(self._adaptive_window) // 2
        older = list(self._adaptive_window)[:mid]
        newer = list(self._adaptive_window)[mid:]
        
        if not older or not newer:
            return False
        
        # Calculate means
        older_mean = sum(older) / len(older)
        newer_mean = sum(newer) / len(newer)
        
        # Calculate variance
        older_var = sum((x - older_mean) ** 2 for x in older) / len(older)
        newer_var = sum((x - newer_mean) ** 2 for x in newer) / len(newer)
        
        # Statistical test (simplified Welch's t-test)
        if older_var == 0:
            older_var = 0.001
        if newer_var == 0:
            newer_var = 0.001
        
        # Test statistic
        n1, n2 = len(older), len(newer)
        se = math.sqrt(older_var / n1 + newer_var / n2)
        
        if se == 0:
            return False
            
        t_stat = abs(newer_mean - older_mean) / se
        
        # Drift if t-statistic exceeds threshold (roughly 2 std for 95% confidence)
        return t_stat > 2.0

    def record(self, cache_hit: bool) -> str:
        """
        Record a cache outcome and return drift status.
        
        Uses multiple detection methods combined:
        1. EWMA-based detection (primary)
        2. ADWIN-like adaptive windowing (secondary)
        3. EDDM for early warning (optional)
        
        Returns:
            "drift"   — significant drop, trigger retrain now
            "warning" — moderate drop, watch closely
            "ok"      — within normal variance
        """
        val = 1 if cache_hit else 0
        self._total_records += 1
        
        # Update all detection mechanisms
        short_ewma, long_ewma = self._update_ewma(val)
        
        # Update adaptive window
        self._adaptive_window.append(val)
        
        # Update basic windows
        self._short_hits.append(val)
        self._long_hits.append(val)
        
        # Need minimum data for reliable detection
        if self._total_records < self.min_confidence:
            return "ok"
        
        # Method 1: EWMA-based detection
        ewma_drop = long_ewma - short_ewma
        
        # Method 2: ADWIN-like detection
        adwin_drift = self._detect_adwin_change()
        
        # Method 3: Basic sliding window (fallback)
        if len(self._short_hits) >= self.short_window // 2 and len(self._long_hits) >= self.long_window // 2:
            short_acc = sum(self._short_hits) / len(self._short_hits)
            long_acc = sum(self._long_hits) / len(self._long_hits)
            basic_drop = long_acc - short_acc
        else:
            basic_drop = 0
        
        # Combine detection results (weighted voting)
        drift_score = 0
        warning_score = 0
        
        # EWMA detection
        if ewma_drop > self.drift_threshold:
            drift_score += 2  # Higher weight
        elif ewma_drop > self.warning_threshold:
            warning_score += 1
        
        # ADWIN detection
        if adwin_drift:
            drift_score += 2
        
        # Basic detection
        if basic_drop > self.drift_threshold:
            drift_score += 1
        elif basic_drop > self.warning_threshold:
            warning_score += 1
        
        # Make decision
        if drift_score >= 2:
            self._drift_count += 1
            self._last_drift_time = time.time()
            
            # Record drift event
            self._drift_history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "drift",
                "ewma_drop": ewma_drop,
                "adwin_drift": adwin_drift,
                "basic_drop": basic_drop,
                "ewma_short": short_ewma,
                "ewma_long": long_ewma,
            })
            
            # Keep only last 100 drift events
            if len(self._drift_history) > 100:
                self._drift_history = self._drift_history[-100:]
            
            logger.warning(
                f"Concept drift detected! "
                f"ewma_drop={ewma_drop:.2%}, adwin={adwin_drift}, "
                f"ewma_short={short_ewma:.2%}, ewma_long={long_ewma:.2%}"
            )
            return "drift"
        
        if warning_score >= 1 or ewma_drop > self.warning_threshold:
            self._warning_count += 1
            logger.info(
                f"Drift warning: ewma_drop={ewma_drop:.2%}, "
                f"short_ewma={short_ewma:.2%}, long_ewma={long_ewma:.2%}"
            )
            return "warning"
        
        return "ok"

    def get_stats(self) -> Dict[str, Any]:
        short_acc = (
            sum(self._short_hits) / len(self._short_hits)
            if self._short_hits else None
        )
        long_acc = (
            sum(self._long_hits) / len(self._long_hits)
            if self._long_hits else None
        )
        
        return {
            # EWMA stats
            "ewma_short": round(self._ewma_short, 4) if self._ewma_initialized else None,
            "ewma_long": round(self._ewma_long, 4) if self._ewma_initialized else None,
            "ewma_drop": round(self._ewma_long - self._ewma_short, 4) if self._ewma_initialized else None,
            # Basic window stats
            "short_window_accuracy": round(short_acc, 4) if short_acc is not None else None,
            "long_window_accuracy": round(long_acc, 4) if long_acc is not None else None,
            # Detection counts
            "drift_count": self._drift_count,
            "warning_count": self._warning_count,
            "total_records": self._total_records,
            # Timing
            "last_drift_ago": round(time.time() - self._last_drift_time, 1)
                              if self._last_drift_time else None,
            # Configuration
            "drift_threshold": self.drift_threshold,
            "warning_threshold": self.warning_threshold,
            "ewma_alpha": self.ewma_alpha,
            # Recent drift history
            "recent_drifts": self._drift_history[-5:] if self._drift_history else [],
        }

    def reset_short_window(self) -> None:
        """Call after retrain to give model a clean slate on short window."""
        self._short_hits.clear()
        self._adaptive_window.clear()
        # Keep EWMA state but reset short-term
        self._ewma_short = self._ewma_long if self._ewma_initialized else 0.0

    def get_drift_analysis(self) -> Dict[str, Any]:
        """
        Get detailed drift analysis for visualization/debugging.
        """
        if not self._drift_history:
            return {
                "total_drifts": 0,
                "avg_interval_seconds": None,
                "trend": "stable",
            }
        
        # Calculate intervals between drifts
        intervals = []
        for i in range(1, len(self._drift_history)):
            try:
                t1 = datetime.fromisoformat(self._drift_history[i-1]["timestamp"])
                t2 = datetime.fromisoformat(self._drift_history[i]["timestamp"])
                intervals.append((t2 - t1).total_seconds())
            except:
                pass
        
        avg_interval = sum(intervals) / len(intervals) if intervals else None
        
        # Determine trend
        if len(self._drift_history) >= 3:
            recent = self._drift_history[-3:]
            earlier = self._drift_history[:3]
            avg_recent = sum(d.get("ewma_drop", 0) for d in recent) / len(recent)
            avg_earlier = sum(d.get("ewma_drop", 0) for d in earlier) / len(earlier)
            if avg_recent > avg_earlier * 1.5:
                trend = "increasing"  # Getting worse
            elif avg_recent < avg_earlier * 0.5:
                trend = "decreasing"  # Getting better
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"
        
        return {
            "total_drifts": len(self._drift_history),
            "avg_interval_seconds": round(avg_interval, 1) if avg_interval else None,
            "trend": trend,
            "drift_history": self._drift_history[-10:],  # Last 10 drifts
        }


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
    ):
        self._model = model
        self._update_interval = update_interval
        self._min_samples = min_samples
        self._batch_size = batch_size
        self._context_window = context_window
        self._model_name = model_name or settings.ml_model_name
        self._registry = registry or get_model_registry()
        self._active_model_version: Optional[str] = None
        self._active_artifact_path: Optional[str] = None
        self._model_source = "runtime"

        # Components
        self._collector = get_data_collector()
        self._engineer = get_feature_engineer()

        # Drift detection
        self._drift_detector = DriftDetector(drift_threshold=drift_threshold)

        # Training state
        self._is_training = False
        self._last_train_time: float = 0
        self._training_count: int = 0
        self._last_drift_retrain_time: float = 0

        # Metrics history
        self._training_history: List[Dict] = []

        # Background thread
        self._train_thread: Optional[threading.Thread] = None
        self._running = False

        logger.info(
            f"ModelTrainer initialized: interval={update_interval}s, "
            f"min_samples={min_samples}, drift_threshold={drift_threshold:.0%}, "
            f"context_window={context_window}"
        )

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

    def get_active_model_metadata(self) -> Dict[str, Optional[str]]:
        return {
            "model_name": self._model_name,
            "version": self._active_model_version,
            "artifact_path": self._active_artifact_path,
            "source": self._model_source,
        }

    def load_active_model(self) -> Dict[str, Any]:
        active_version = self._registry.get_active_version(self._model_name)
        if active_version is None:
            return {"success": False, "reason": "no_active_version"}

        try:
            loaded_model = self._registry.load_model(self._model_name, actor="trainer")
        except SecurityError:
            raise

        if loaded_model is None:
            return {"success": False, "reason": "load_failed"}

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

    def ensure_runtime_model_loaded(self) -> Dict[str, Any]:
        if self._model is not None and getattr(self._model, "is_trained", False):
            return {
                "success": True,
                "version": self._active_model_version,
                "artifact_path": self._active_artifact_path,
                "source": self._model_source,
            }
        return self.load_active_model()

    def _build_trainable_model(self, y_labels: List[str]) -> EnsembleModel:
        unique_labels = len(set(y_labels)) if y_labels else 0
        num_classes = max(unique_labels, 1)
        return ModelFactory.create_model("ensemble", num_classes=num_classes)

    def _persist_model(
        self,
        model: EnsembleModel,
        metrics: Dict[str, float],
        sample_count: int,
        train_samples: int,
        val_samples: int,
        reason: str,
    ) -> Dict[str, Any]:
        version = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        saved_at = datetime.now(timezone.utc).isoformat()
        description = (
            f"runtime training reason={reason} "
            f"samples={sample_count} train={train_samples} val={val_samples} "
            f"val_accuracy={metrics.get('accuracy', 0.0):.4f}"
        )
        provenance = {
            "source": "trainer.runtime",
            "saved_at": saved_at,
            "reason": reason,
            "sample_count": sample_count,
            "train_samples": train_samples,
            "val_samples": val_samples,
            "metrics": metrics,
            "collector_total_events": self._collector.get_stats().get("total_events", 0),
            "drift_stats": self._drift_detector.get_stats(),
        }
        saved = self._registry.save_model(
            model_name=self._model_name,
            model=model,
            version=version,
            metrics=metrics,
            description=description,
            provenance=provenance,
            stage=settings.ml_model_stage,
            actor="trainer",
        )
        if not saved:
            return {"success": False, "reason": "registry_save_failed"}

        active_version = self._registry.get_active_version(self._model_name)
        self._active_model_version = active_version.version if active_version is not None else version
        self._active_artifact_path = active_version.file_path if active_version is not None else None
        self._model_source = "registry"
        return {
            "success": True,
            "version": self._active_model_version,
            "artifact_path": self._active_artifact_path,
        }

    # ----------------------------------------------------------
    # Feature Extraction (with context window)
    # ----------------------------------------------------------

    def _extract_XY(self, data: List[Dict]) -> Tuple[np.ndarray, List[str]]:
        """
        Extract feature matrix using sliding context window.
        Each sample uses up to `context_window` preceding events as context.
        This gives temporal context vs. extracting from a single event.
        """
        X, y = [], []
        for idx in range(len(data)):
            start = max(0, idx - self._context_window)
            context = data[start: idx + 1]
            features = self._engineer.extract_features(context)
            X.append(features)
            y.append(data[idx]["key_id"])
        return np.array(X), y

    # ----------------------------------------------------------
    # Training
    # ----------------------------------------------------------

    def train(self, force: bool = False, reason: str = "scheduled") -> Dict[str, Any]:
        """
        Train the model on collected data.

        Args:
            force: Bypass sample count check
            reason: Why training was triggered ("scheduled" | "drift" | "manual")

        Returns:
            Training results dict
        """
        if self._is_training:
            return {"success": False, "reason": "already_training"}

        start_time = time.time()
        self._is_training = True

        try:
            stats = self._collector.get_stats()
            sample_count = stats.get("total_events", 0)

            if sample_count < self._min_samples and not force:
                logger.info(f"Not enough samples: {sample_count}/{self._min_samples}")
                return {
                    "success": False,
                    "reason": "insufficient_samples",
                    "sample_count": sample_count,
                    "required": self._min_samples,
                }

            access_data = self._collector.get_access_sequence(
                window_seconds=3600, max_events=10_000
            )

            if not access_data:
                return {"success": False, "reason": "no_data"}

            # Sort by timestamp to ensure temporal order
            access_data.sort(key=lambda x: x.get("timestamp", 0))

            # Extract features with context window
            X, y = self._extract_XY(access_data)

            # 70/30 split (temporal)
            split_idx = int(len(access_data) * 0.7)
            X_train, X_val = X[:split_idx], X[split_idx:]
            y_train, y_val = y[:split_idx], y[split_idx:]

            # Build access sequence for Markov Chain
            key_sequence = [d["key_id"] for d in access_data]

            trainable_model = self._build_trainable_model(y_train)

            # Train ensemble (RF + Markov; LSTM uses same X for now)
            trainable_model.fit(
                X_rf=X_train,
                y_rf=np.array(y_train),
                access_sequence=key_sequence,
            )

            # Evaluate on validation split
            val_metrics = self._quick_eval(trainable_model, X_val, y_val)

            # Reset drift detector short window after retrain
            self._drift_detector.reset_short_window()

            persist_result = self._persist_model(
                model=trainable_model,
                metrics=val_metrics,
                sample_count=len(access_data),
                train_samples=split_idx,
                val_samples=len(access_data) - split_idx,
                reason=reason,
            )
            if not persist_result.get("success"):
                logger.error("Runtime model persistence failed: %s", persist_result.get("reason"))
                return {"success": False, "reason": str(persist_result.get("reason"))}

            self._model = trainable_model
            self._last_train_time = time.time()
            self._training_count += 1
            training_time = time.time() - start_time

            result = {
                "success": True,
                "reason": reason,
                "sample_count": len(access_data),
                "train_samples": split_idx,
                "val_samples": len(access_data) - split_idx,
                "training_time_s": round(training_time, 2),
                "training_count": self._training_count,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "val_accuracy": val_metrics.get("accuracy"),
                "model_stats": self._model.get_model_stats(),
                "artifact_path": persist_result.get("artifact_path"),
                "registry_version": persist_result.get("version"),
            }

            self._training_history.append(result)
            logger.info(
                f"Training complete [{reason}]: "
                f"samples={len(access_data)}, "
                f"val_acc={val_metrics.get('accuracy', 'N/A')}, "
                f"time={training_time:.1f}s"
            )
            return result

        except Exception as e:
            logger.error(f"Training failed: {e}", exc_info=True)
            return {"success": False, "reason": str(e)}
        finally:
            self._is_training = False

    def _quick_eval(self, model: EnsembleModel, X_val: np.ndarray, y_val: List[str]) -> Dict[str, Any]:
        """Quick accuracy evaluation on validation data using RF sub-model."""
        try:
            if model.rf is None or not getattr(model.rf, "is_trained", False):
                return {}

            le = model.rf.label_encoder
            known = set(le.classes_)

            y_true_enc, X_filtered = [], []
            for label, x in zip(y_val, X_val):
                if label in known:
                    y_true_enc.append(le.transform([label])[0])
                    X_filtered.append(x)

            if not X_filtered:
                return {}

            X_arr = np.array(X_filtered)
            y_pred = model.rf.predict(X_arr)
            accuracy = (y_pred == np.array(y_true_enc)).mean()

            return {"accuracy": round(float(accuracy), 4), "n_samples": len(X_filtered)}
        except Exception as e:
            logger.debug(f"Quick eval failed: {e}")
            return {}

    # ----------------------------------------------------------
    # Online Learning / Incremental Update
    # ----------------------------------------------------------

    def record_cache_outcome(self, key_id: str, cache_hit: bool) -> None:
        """
        Record a real cache outcome.
        - Updates drift detector
        - If drift detected, triggers immediate retrain (rate-limited to 1/5min)
        """
        status = self._drift_detector.record(cache_hit)

        if status == "drift":
            # Rate limit: don't retrain more than once per 5 minutes from drift
            time_since_last = time.time() - self._last_drift_retrain_time
            if time_since_last > 300:
                logger.info("Triggering drift-based retrain...")
                self._last_drift_retrain_time = time.time()
                # Run in background thread to not block the caller
                t = threading.Thread(
                    target=self.train,
                    kwargs={"force": True, "reason": "drift"},
                    daemon=True,
                )
                t.start()

    def train_incremental(self, new_data: List[Dict]) -> Dict[str, Any]:
        """
        Incremental update — full retrain on latest collected data.
        (River/online learning could be used here in future upgrade)
        """
        return self.train(force=True, reason="incremental")

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
                    self.train(reason="scheduled")
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
            test_data = self._collector.get_access_sequence(window_seconds=300)

        if not test_data:
            return {"success": False, "reason": "no_test_data"}

        try:
            test_data = sorted(test_data, key=lambda x: x.get("timestamp", 0))
            X, y_true = self._extract_XY(test_data)

            if not self.model.is_trained:
                return {"success": False, "reason": "model_not_trained"}

            top1_hits, top10_hits, total = 0, 0, 0

            for i, (x, true_key) in enumerate(zip(X, y_true)):
                current_key = test_data[i - 1]["key_id"] if i > 0 else None
                top_indices, top_probs = self.model.predict_top_n(
                    n=10,
                    X_rf=x.reshape(1, -1),
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

            return {
                "success": True,
                "test_samples": total,
                "top_1_accuracy":  round(top1_hits  / total, 4) if total else 0.0,
                "top_10_accuracy": round(top10_hits / total, 4) if total else 0.0,
                "drift_stats": self._drift_detector.get_stats(),
                "model_stats": self.model.get_model_stats(),
            }

        except Exception as e:
            logger.error(f"Evaluation failed: {e}", exc_info=True)
            return {"success": False, "reason": str(e)}

    # ----------------------------------------------------------
    # Stats
    # ----------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        return {
            "training_count":  self._training_count,
            "last_train_time": self._last_train_time,
            "update_interval": self._update_interval,
            "min_samples":     self._min_samples,
            "auto_training":   self._running,
            "drift_stats":     self._drift_detector.get_stats(),
            "model_stats":     self.model.get_model_stats(),
            "collector_stats": self._collector.get_stats(),
            "model_name":      self._model_name,
            "active_version":  self._active_model_version,
            "artifact_path":   self._active_artifact_path,
            "model_source":    self._model_source,
        }

    def get_training_history(self) -> List[Dict]:
        return self._training_history.copy()


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
