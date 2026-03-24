# ============================================================
# PSKC — Auto Retrainer Module
# Make smart decisions about when to retrain from simulations
# ============================================================
import logging
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RetrainingDecision:
    """Decision about whether to retrain based on drift analysis"""
    should_retrain: bool
    reason: str                             # Why or why not
    confidence: float                       # 0-1, confidence in decision
    recommended_data_size: Optional[int]    # How many events to use
    cooldown_remaining_seconds: Optional[float]  # If cooldown blocking
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses"""
        return {
            'should_retrain': self.should_retrain,
            'reason': self.reason,
            'confidence': round(self.confidence, 2),
            'recommended_data_size': self.recommended_data_size,
            'cooldown_remaining_seconds': (
                round(self.cooldown_remaining_seconds, 1) 
                if self.cooldown_remaining_seconds else None
            ),
        }


class AutoRetrainer:
    """
    Make intelligent decisions about when to retrain from simulation events.
    
    Prevents excessive retraining while still allowing model improvement
    from simulation-discovered patterns.
    """
    
    def __init__(self,
                 drift_threshold: float = 0.3,
                 min_sample_count: int = 1000,
                 cooldown_hours: int = 24,
                 min_accuracy_improvement: float = 0.02):
        """
        Initialize auto-retrainer.
        
        Args:
            drift_threshold: Drift score threshold (0-1) to trigger retraining
            min_sample_count: Minimum simulation events needed to retrain
            cooldown_hours: Hours to wait between simulation-based retrainings
            min_accuracy_improvement: Minimum accuracy gain (0-1) to consider success
        """
        self.drift_threshold = drift_threshold
        self.min_sample_count = min_sample_count
        self.cooldown_hours = cooldown_hours
        self.cooldown_seconds = cooldown_hours * 3600
        self.min_accuracy_improvement = min_accuracy_improvement
        
        self.last_simulation_retraining: Optional[float] = None
        self.last_retraining_drift_score: Optional[float] = None
        self.last_retraining_accuracy_before: Optional[float] = None
        self.last_retraining_accuracy_after: Optional[float] = None
        
        logger.info(
            f"AutoRetrainer: Initialized with threshold={drift_threshold}, "
            f"min_samples={min_sample_count}, cooldown={cooldown_hours}h"
        )
    
    def decide(self,
               drift_score: float,
               simulation_event_count: int,
               manual_override: bool = False,
               current_timestamp: Optional[float] = None) -> RetrainingDecision:
        """
        Decide whether to retrain based on drift and available data.
        
        Decision Logic:
        1. If manual_override: retrain immediately (confidence=1.0)
        2. If cooldown active: don't retrain unless manual
        3. If drift < threshold: don't retrain (confidence=high)
        4. If events < min_count: don't retrain, wait for more data
        5. Otherwise: retrain (confidence=high)
        
        Args:
            drift_score: Drift score from pattern analyzer (0-1)
            simulation_event_count: Number of simulation events available
            manual_override: Force retraining regardless of checks
            current_timestamp: Current time for cooldown calculation
        
        Returns:
            RetrainingDecision with detailed reasoning
        """
        if current_timestamp is None:
            current_timestamp = time.time()
        
        # Check 1: Manual override
        if manual_override:
            logger.info("AutoRetrainer: Manual override - retraining forced")
            return RetrainingDecision(
                should_retrain=True,
                reason="Manual override - user requested retraining",
                confidence=1.0,
                recommended_data_size=min(simulation_event_count, 50000),
                cooldown_remaining_seconds=None,
            )
        
        # Check 2: Cooldown enforcement
        if self.is_cooldown_active(current_timestamp):
            remaining = self.get_cooldown_remaining(current_timestamp)
            logger.info(f"AutoRetrainer: Cooldown active, {remaining:.1f}s remaining")
            return RetrainingDecision(
                should_retrain=False,
                reason=f"Cooldown period active ({remaining:.1f}s remaining). "
                       f"Last retraining was {(current_timestamp - self.last_simulation_retraining) / 3600:.1f} hours ago.",
                confidence=0.95,
                recommended_data_size=None,
                cooldown_remaining_seconds=remaining,
            )
        
        # Check 3: Drift threshold
        if drift_score < self.drift_threshold:
            logger.info(
                f"AutoRetrainer: Drift {drift_score:.3f} < threshold {self.drift_threshold} - "
                f"patterns still stable"
            )
            return RetrainingDecision(
                should_retrain=False,
                reason=f"Drift score {drift_score:.3f} below threshold {self.drift_threshold}. "
                       f"Patterns remain stable.",
                confidence=0.90,
                recommended_data_size=None,
                cooldown_remaining_seconds=None,
            )
        
        # Check 4: Minimum sample count
        if simulation_event_count < self.min_sample_count:
            logger.info(
                f"AutoRetrainer: Insufficient samples "
                f"({simulation_event_count}/{self.min_sample_count})"
            )
            return RetrainingDecision(
                should_retrain=False,
                reason=f"Insufficient simulation data. Have {simulation_event_count} events, "
                       f"need {self.min_sample_count}. "
                       f"Run more simulations to gather enough data.",
                confidence=0.85,
                recommended_data_size=self.min_sample_count,
                cooldown_remaining_seconds=None,
            )
        
        # All checks passed - should retrain
        logger.info(
            f"AutoRetrainer: All checks passed - recommending retraining. "
            f"Drift={drift_score:.3f}, Events={simulation_event_count}"
        )
        return RetrainingDecision(
            should_retrain=True,
            reason=f"Significant drift detected ({drift_score:.3f}). "
                   f"Sufficient data available ({simulation_event_count} events). "
                   f"Retraining recommended to adapt to new patterns.",
            confidence=0.95,
            recommended_data_size=min(simulation_event_count, 50000),
            cooldown_remaining_seconds=None,
        )
    
    def is_cooldown_active(self, current_timestamp: Optional[float] = None) -> bool:
        """Check if retraining cooldown is currently active"""
        if self.last_simulation_retraining is None:
            return False
        
        if current_timestamp is None:
            current_timestamp = time.time()
        
        elapsed = current_timestamp - self.last_simulation_retraining
        return elapsed < self.cooldown_seconds
    
    def get_cooldown_remaining(self, current_timestamp: Optional[float] = None) -> Optional[float]:
        """
        Get seconds remaining until cooldown expires.
        
        Returns:
            Seconds remaining, or None if no cooldown active
        """
        if self.last_simulation_retraining is None:
            return None
        
        if current_timestamp is None:
            current_timestamp = time.time()
        
        elapsed = current_timestamp - self.last_simulation_retraining
        remaining = self.cooldown_seconds - elapsed
        
        if remaining > 0:
            return remaining
        return None
    
    def mark_retraining_started(self, current_timestamp: Optional[float] = None,
                               drift_score: Optional[float] = None):
        """
        Record when simulation-based retraining was started.
        
        Updates cooldown timer and tracks drift score.
        
        Args:
            current_timestamp: Time when retraining started
            drift_score: The drift score that triggered this retraining
        """
        if current_timestamp is None:
            current_timestamp = time.time()
        
        self.last_simulation_retraining = current_timestamp
        self.last_retraining_drift_score = drift_score
        
        logger.info(
            f"AutoRetrainer: Marked retraining started at {current_timestamp}. "
            f"Next retraining available in {self.cooldown_hours}h. "
            f"Drift score: {drift_score}"
        )
    
    def mark_retraining_completed(self,
                                 accuracy_before: Optional[float] = None,
                                 accuracy_after: Optional[float] = None):
        """
        Record completion of simulation-based retraining.
        
        Tracks accuracy improvement for reporting.
        
        Args:
            accuracy_before: Model accuracy before retraining
            accuracy_after: Model accuracy after retraining
        """
        self.last_retraining_accuracy_before = accuracy_before
        self.last_retraining_accuracy_after = accuracy_after
        
        if accuracy_before is not None and accuracy_after is not None:
            improvement = accuracy_after - accuracy_before
            logger.info(
                f"AutoRetrainer: Retraining completed. "
                f"Accuracy: {accuracy_before:.4f} → {accuracy_after:.4f} "
                f"(+{improvement*100:.2f}%)"
            )
        else:
            logger.info("AutoRetrainer: Retraining completed")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about auto-retraining decisions and history"""
        stats = {
            'drift_threshold': self.drift_threshold,
            'min_sample_count': self.min_sample_count,
            'cooldown_hours': self.cooldown_hours,
            'min_accuracy_improvement': round(self.min_accuracy_improvement, 3),
        }
        
        if self.last_simulation_retraining is not None:
            current_time = time.time()
            hours_since = (current_time - self.last_simulation_retraining) / 3600
            stats['last_simulation_retraining_hours_ago'] = round(hours_since, 2)
            stats['last_simulation_retraining_drift_score'] = self.last_retraining_drift_score
            stats['cooldown_active'] = self.is_cooldown_active()
            
            if self.last_retraining_accuracy_before is not None:
                stats['last_retraining_accuracy_before'] = round(
                    self.last_retraining_accuracy_before, 4
                )
            if self.last_retraining_accuracy_after is not None:
                stats['last_retraining_accuracy_after'] = round(
                    self.last_retraining_accuracy_after, 4
                )
            
            if (self.last_retraining_accuracy_before is not None and 
                self.last_retraining_accuracy_after is not None):
                improvement = (self.last_retraining_accuracy_after - 
                              self.last_retraining_accuracy_before)
                stats['last_retraining_accuracy_improvement'] = round(improvement, 4)
                stats['improvement_meets_threshold'] = (
                    improvement >= self.min_accuracy_improvement
                )
        else:
            stats['last_simulation_retraining'] = None
            stats['cooldown_active'] = False
        
        return stats


# Global instance
_auto_retrainer: Optional[AutoRetrainer] = None


def get_auto_retrainer(
    drift_threshold: float = 0.3,
    min_sample_count: int = 1000,
    cooldown_hours: int = 24,
    min_accuracy_improvement: float = 0.02
) -> AutoRetrainer:
    """
    Get or create singleton AutoRetrainer instance.
    
    Args:
        drift_threshold: Drift threshold for retraining decision
        min_sample_count: Minimum simulation events needed
        cooldown_hours: Hours between simulation-based retrainings
        min_accuracy_improvement: Minimum accuracy gain needed (0-1)
    
    Returns:
        AutoRetrainer instance
    """
    global _auto_retrainer
    
    if _auto_retrainer is None:
        _auto_retrainer = AutoRetrainer(
            drift_threshold=drift_threshold,
            min_sample_count=min_sample_count,
            cooldown_hours=cooldown_hours,
            min_accuracy_improvement=min_accuracy_improvement,
        )
    
    return _auto_retrainer
