# Drift detection module extracted from trainer.py
import time
import math
from collections import deque
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

class DriftDetector:
    """
    Advanced Concept Drift Detection combining multiple methods:
    
    1. EWMA (Exponential Weighted Moving Average) - untuk smooth detection
    2. ADWIN-like adaptive windowing - untuk variasi perubahan
    3. EDDM (Early Drift Detection Method) - untuk deteksi dini
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
        if not self._ewma_initialized:
            self._ewma_short = value
            self._ewma_long = value
            self._ewma_initialized = True
            return self._ewma_short, self._ewma_long
        self._ewma_short = self.ewma_alpha * value + (1 - self.ewma_alpha) * self._ewma_short
        self._ewma_long = (self.ewma_alpha / 2) * value + (1 - self.ewma_alpha / 2) * self._ewma_long
        return self._ewma_short, self._ewma_long

    def _update_eddm(self, correct: bool, position: int, total: int) -> Dict[str, float]:
        if position < 2 or total < 10:
            return {"drift_indicator": 0.0, "p": 0.0, "s": 0.0, "threshold": 0.0}
        distance = 1.0 if correct else 0.0
        if self._eddm_p == 0:
            self._eddm_p = distance
            self._eddm_s = 0.0
        else:
            delta = distance - self._eddm_p
            self._eddm_p += delta / self._total_records
            delta2 = distance - self._eddm_p
            self._eddm_s += (delta * delta2 - self._eddm_s) / self._total_records
        self._eddm_s = math.sqrt(self._eddm_s) if self._eddm_s > 0 else 0.001
        p_plus_2s = self._eddm_p + 2 * self._eddm_s
        max_p_2s = 1.0
        indicator = p_plus_2s / max_p_2s if max_p_2s > 0 else 1.0
        return {"drift_indicator": indicator, "p": self._eddm_p, "s": self._eddm_s, "threshold": self.eddm_threshold}

    def _detect_adwin_change(self) -> bool:
        if len(self._adaptive_window) < self.long_window:
            return False
        mid = len(self._adaptive_window) // 2
        older = list(self._adaptive_window)[:mid]
        newer = list(self._adaptive_window)[mid:]
        if not older or not newer:
            return False
        older_mean = sum(older) / len(older)
        newer_mean = sum(newer) / len(newer)
        older_var = sum((x - older_mean) ** 2 for x in older) / len(older)
        newer_var = sum((x - newer_mean) ** 2 for x in newer) / len(newer)
        if older_var == 0:
            older_var = 0.001
        if newer_var == 0:
            newer_var = 0.001
        n1, n2 = len(older), len(newer)
        se = math.sqrt(older_var / n1 + newer_var / n2)
        if se == 0:
            return False
        t_stat = abs(newer_mean - older_mean) / se
        return t_stat > 2.0

    def record(self, cache_hit: bool) -> str:
        val = 1 if cache_hit else 0
        self._total_records += 1
        short_ewma, long_ewma = self._update_ewma(val)
        self._adaptive_window.append(val)
        self._short_hits.append(val)
        self._long_hits.append(val)
        if self._total_records < self.min_confidence:
            return "ok"
        ewma_drop = long_ewma - short_ewma
        adwin_drift = self._detect_adwin_change()
        if len(self._short_hits) >= self.short_window // 2 and len(self._long_hits) >= self.long_window // 2:
            short_acc = sum(self._short_hits) / len(self._short_hits)
            long_acc = sum(self._long_hits) / len(self._long_hits)
            basic_drop = long_acc - short_acc
        else:
            basic_drop = 0
        drift_score = 0
        warning_score = 0
        if ewma_drop > self.drift_threshold:
            drift_score += 2
        elif ewma_drop > self.warning_threshold:
            warning_score += 1
        if adwin_drift:
            drift_score += 2
        if basic_drop > self.drift_threshold:
            drift_score += 1
        elif basic_drop > self.warning_threshold:
            warning_score += 1
        if drift_score >= 2:
            self._drift_count += 1
            self._last_drift_time = time.time()
            self._drift_history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "drift",
                "ewma_drop": ewma_drop,
                "adwin_drift": adwin_drift,
                "basic_drop": basic_drop,
                "ewma_short": short_ewma,
                "ewma_long": long_ewma,
            })
            if len(self._drift_history) > 100:
                self._drift_history = self._drift_history[-100:]
            logger.warning(
                f"Concept drift detected! ewma_drop={ewma_drop:.2%}, adwin={adwin_drift}, ewma_short={short_ewma:.2%}, ewma_long={long_ewma:.2%}"
            )
            return "drift"
        if warning_score >= 1 or ewma_drop > self.warning_threshold:
            self._warning_count += 1
            logger.info(
                f"Drift warning: ewma_drop={ewma_drop:.2%}, short_ewma={short_ewma:.2%}, long_ewma={long_ewma:.2%}"
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
            "ewma_short": round(self._ewma_short, 4) if self._ewma_initialized else None,
            "ewma_long": round(self._ewma_long, 4) if self._ewma_initialized else None,
            "ewma_drop": round(self._ewma_long - self._ewma_short, 4) if self._ewma_initialized else None,
            "short_window_accuracy": round(short_acc, 4) if short_acc is not None else None,
            "long_window_accuracy": round(long_acc, 4) if long_acc is not None else None,
            "drift_count": self._drift_count,
            "warning_count": self._warning_count,
            "total_records": self._total_records,
            "last_drift_ago": round(time.time() - self._last_drift_time, 1)
                              if self._last_drift_time else None,
            "drift_threshold": self.drift_threshold,
            "warning_threshold": self.warning_threshold,
            "ewma_alpha": self.ewma_alpha,
            "recent_drifts": self._drift_history[-5:] if self._drift_history else [],
        }

    def reset_short_window(self) -> None:
        self._short_hits.clear()
        self._adaptive_window.clear()
        self._ewma_short = self._ewma_long if self._ewma_initialized else 0.0

    def get_drift_analysis(self) -> Dict[str, Any]:
        if not self._drift_history:
            return {
                "total_drifts": 0,
                "avg_interval_seconds": None,
                "trend": "stable",
            }
        intervals = []
        for i in range(1, len(self._drift_history)):
            try:
                t1 = datetime.fromisoformat(self._drift_history[i-1]["timestamp"])
                t2 = datetime.fromisoformat(self._drift_history[i]["timestamp"])
                intervals.append((t2 - t1).total_seconds())
            except:
                pass
        avg_interval = sum(intervals) / len(intervals) if intervals else None
        if len(self._drift_history) >= 3:
            recent = self._drift_history[-3:]
            earlier = self._drift_history[:3]
            avg_recent = sum(d.get("ewma_drop", 0) for d in recent) / len(recent)
            avg_earlier = sum(d.get("ewma_drop", 0) for d in earlier) / len(earlier)
            if avg_recent > avg_earlier * 1.5:
                trend = "increasing"
            elif avg_recent < avg_earlier * 0.5:
                trend = "decreasing"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"
        return {
            "total_drifts": len(self._drift_history),
            "avg_interval_seconds": round(avg_interval, 1) if avg_interval else None,
            "trend": trend,
            "drift_history": self._drift_history[-10:],
        }
