# ============================================================
# PSKC — Training Progress Service
# Real-time training progress tracking and WebSocket support
# ============================================================
import asyncio
import logging
import json
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, asdict
from enum import Enum
import threading
from queue import Queue, Empty

logger = logging.getLogger(__name__)


class TrainingPhase(str, Enum):
    """Training phases for progress tracking."""
    IDLE = "idle"
    LOADING_DATA = "loading_data"
    PREPROCESSING = "preprocessing"
    FEATURE_ENGINEERING = "feature_engineering"
    DATA_BALANCING = "data_balancing"
    DATA_AUGMENTATION = "data_augmentation"
    SPLITTING = "splitting"
    TRAINING_LSTM = "training_lstm"
    TRAINING_RF = "training_rf"
    UPDATING_MARKOV = "updating_markov"
    EVALUATION = "evaluation"
    SAVING_MODEL = "saving_model"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TrainingProgressUpdate:
    """Single progress update event."""
    phase: TrainingPhase
    progress_percent: float  # 0-100
    current_step: int
    total_steps: int
    message: str
    timestamp: str
    details: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        data['phase'] = self.phase.value
        return data


@dataclass
class TrainingMetrics:
    """Training metrics for current phase."""
    train_accuracy: Optional[float] = None
    val_accuracy: Optional[float] = None
    train_loss: Optional[float] = None
    val_loss: Optional[float] = None
    samples_processed: int = 0
    total_samples: int = 0
    epoch: int = 0
    total_epochs: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


REDIS_PROGRESS_KEY = "pskc:ml:training_progress"


def _get_redis():
    """Try to get a Redis client; return None if unavailable."""
    try:
        import os
        import redis as _redis
        r = _redis.Redis(
            host=os.environ.get("REDIS_HOST", "redis"),
            port=int(os.environ.get("REDIS_PORT", "6379")),
            db=int(os.environ.get("REDIS_DB", "0")),
            password=os.environ.get("REDIS_PASSWORD", "pskc_redis_secret"),
            decode_responses=True,
            socket_connect_timeout=2,
        )
        r.ping()
        return r
    except Exception:
        return None


class TrainingProgressTracker:
    """
    Track training progress with support for real-time updates.
    Designed for use with WebSocket and async streaming.
    State is also persisted to Redis so clients can resume after page reload.
    """

    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self.updates: List[TrainingProgressUpdate] = []
        self.current_phase = TrainingPhase.IDLE
        self.current_metrics = TrainingMetrics()
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

        # For progress callbacks
        self._callbacks: List[Callable[[TrainingProgressUpdate], None]] = []

        # Thread-safe queue for async streaming
        self._update_queue: Queue = Queue()

    def _persist_to_redis(self, update: "TrainingProgressUpdate") -> None:
        """Save latest progress state to Redis for cross-session recovery."""
        try:
            r = _get_redis()
            if not r:
                return
            payload = {
                **update.to_dict(),
                "elapsed_seconds": max(
                    0.0,
                    (self.end_time or datetime.utcnow().timestamp())
                    - (self.start_time or datetime.utcnow().timestamp()),
                ),
                "start_time": self.start_time,
            }
            r.setex(REDIS_PROGRESS_KEY, 3600, json.dumps(payload))  # TTL 1 hour
        except Exception as e:
            logger.debug(f"Could not persist progress to Redis: {e}")

    @staticmethod
    def load_from_redis() -> Optional[Dict[str, Any]]:
        """Load last known progress state from Redis (for page-reload resume)."""
        try:
            r = _get_redis()
            if not r:
                return None
            raw = r.get(REDIS_PROGRESS_KEY)
            if raw:
                return json.loads(raw)
            return None
        except Exception:
            return None
    
    def add_callback(self, callback: Callable[[TrainingProgressUpdate], None]) -> None:
        """Register callback for progress updates."""
        self._callbacks.append(callback)
    
    def remove_callback(self, callback: Callable) -> None:
        """Unregister callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)
    
    def _notify_callbacks(self, update: TrainingProgressUpdate) -> None:
        """Call all registered callbacks."""
        for callback in self._callbacks:
            try:
                callback(update)
            except Exception as e:
                logger.error(f"Callback error: {e}")
    
    def update_progress(
        self,
        phase: TrainingPhase,
        progress_percent: float,
        current_step: int,
        total_steps: int,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> TrainingProgressUpdate:
        """
        Record a progress update.
        
        Args:
            phase: Current training phase
            progress_percent: Progress as percentage (0-100)
            current_step: Current step number
            total_steps: Total steps
            message: Human-readable message
            details: Optional additional details
            
        Returns:
            Created update object
        """
        update = TrainingProgressUpdate(
            phase=phase,
            progress_percent=min(100.0, max(0.0, progress_percent)),
            current_step=current_step,
            total_steps=total_steps,
            message=message,
            timestamp=datetime.utcnow().isoformat() + "Z",
            details=details,
        )
        
        self.updates.append(update)
        if len(self.updates) > self.max_history:
            self.updates = self.updates[-self.max_history:]
        
        self.current_phase = phase
        
        # Queue for async streaming
        self._update_queue.put(update)
        
        # Persist to Redis immediately (for page-reload recovery)
        self._persist_to_redis(update)
        
        # Notify callbacks
        self._notify_callbacks(update)
        
        logger.debug(f"{phase.value}: {message} ({progress_percent:.1f}%)")
        
        return update
    
    def update_metrics(self, **kwargs) -> None:
        """
        Update training metrics.
        
        Accepted kwargs:
            train_accuracy, val_accuracy, train_loss, val_loss,
            samples_processed, total_samples, epoch, total_epochs
        """
        for key, value in kwargs.items():
            if hasattr(self.current_metrics, key):
                setattr(self.current_metrics, key, value)
    
    def get_latest_update(self) -> Optional[TrainingProgressUpdate]:
        """Get most recent progress update."""
        return self.updates[-1] if self.updates else None
    
    def get_progress_summary(self) -> Dict[str, Any]:
        """Get complete progress summary."""
        latest = self.get_latest_update()
        
        return {
            "current_phase": self.current_phase.value,
            "latest_update": latest.to_dict() if latest else None,
            "metrics": self.current_metrics.to_dict(),
            "total_updates": len(self.updates),
            "start_time": datetime.fromtimestamp(self.start_time).isoformat() if self.start_time else None,
            "elapsed_seconds": (self.end_time or datetime.utcnow().timestamp()) - (self.start_time or 0),
        }
    
    def get_last_saved_state(self) -> Optional[Dict[str, Any]]:
        """
        Get the last saved progress state from Redis.
        Used by WebSocket clients to resume on connect.
        """
        return self.load_from_redis()
    
    async def stream_progress_updates(self):
        """
        Async generator for streaming progress updates.
        Yields JSON-formatted updates for WebSocket or SSE.
        """
        while True:
            try:
                update = self._update_queue.get(timeout=0.1)
                yield json.dumps(update.to_dict())
            except Empty:
                # Check if training is complete
                if self.current_phase in (TrainingPhase.COMPLETED, TrainingPhase.FAILED):
                    break
                await asyncio.sleep(0.1)
    
    def start_training(self) -> None:
        """Mark training start."""
        self.start_time = datetime.utcnow().timestamp()
        self.end_time = None
        self.updates = []
    
    def finish_training(self, success: bool = True) -> None:
        """Mark training completion."""
        self.end_time = datetime.utcnow().timestamp()
        phase = TrainingPhase.COMPLETED if success else TrainingPhase.FAILED
        self.update_progress(
            phase=phase,
            progress_percent=100.0,
            current_step=1,
            total_steps=1,
            message="Training completed" if success else "Training failed",
        )


class DataGenerationProgressTracker:
    """
    Track data generation progress with ETA calculation.
    """
    
    def __init__(self):
        self.total_events: int = 0
        self.processed_events: int = 0
        self.start_time: Optional[float] = None
        self.updates: List[Dict[str, Any]] = []
        self._callbacks: List[Callable[[Dict[str, Any]], None]] = []
    
    def add_callback(self, callback: Callable) -> None:
        """Register callback for progress updates."""
        self._callbacks.append(callback)
    
    def start_generation(self, total_events: int) -> None:
        """Initialize generation tracking."""
        self.total_events = total_events
        self.processed_events = 0
        self.start_time = datetime.utcnow().timestamp()
    
    def update(self, processed_count: int) -> Dict[str, Any]:
        """
        Update progress.
        
        Args:
            processed_count: Number of events processed so far
            
        Returns:
            Progress update dict with percentage and ETA
        """
        self.processed_events = processed_count
        
        if self.start_time is None:
            return {}
        
        elapsed = datetime.utcnow().timestamp() - self.start_time
        progress_percent = (processed_count / self.total_events * 100) if self.total_events > 0 else 0
        
        if processed_count > 0:
            events_per_second = processed_count / elapsed
            remaining_events = self.total_events - processed_count
            eta_seconds = remaining_events / events_per_second if events_per_second > 0 else 0
        else:
            eta_seconds = 0
        
        update = {
            "processed": processed_count,
            "total": self.total_events,
            "percent": min(100.0, progress_percent),
            "elapsed_seconds": elapsed,
            "eta_seconds": max(0, eta_seconds),
            "events_per_second": events_per_second if processed_count > 0 else 0,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        
        self.updates.append(update)
        
        # Notify callbacks
        for callback in self._callbacks:
            try:
                callback(update)
            except Exception as e:
                logger.error(f"Callback error: {e}")
        
        return update
    
    def get_summary(self) -> Dict[str, Any]:
        """Get generation summary."""
        if not self.start_time:
            return {}
        
        total_time = datetime.utcnow().timestamp() - self.start_time
        
        return {
            "processed": self.processed_events,
            "total": self.total_events,
            "percent": (self.processed_events / self.total_events * 100) if self.total_events > 0 else 0,
            "total_time_seconds": total_time,
            "events_per_second": self.processed_events / total_time if total_time > 0 else 0,
        }


# Global instances
_training_progress_tracker = TrainingProgressTracker()
_data_generation_tracker = DataGenerationProgressTracker()


def get_training_progress_tracker() -> TrainingProgressTracker:
    """Get global training progress tracker."""
    return _training_progress_tracker


def get_data_generation_tracker() -> DataGenerationProgressTracker:
    """Get global data generation tracker."""
    return _data_generation_tracker


def reset_training_progress() -> None:
    """Reset progress tracker (useful for new training session)."""
    global _training_progress_tracker
    _training_progress_tracker = TrainingProgressTracker()


def reset_data_generation_progress() -> None:
    """Reset data generation tracker."""
    global _data_generation_tracker
    _data_generation_tracker = DataGenerationProgressTracker()
