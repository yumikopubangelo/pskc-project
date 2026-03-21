# ============================================================
# PSKC — Incremental Model Persistence
# Supports single-file model that evolves over time
# Instead of creating new files per version, we update one file
# ============================================================
import json
import os
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config.settings import settings

logger = logging.getLogger(__name__)


class IncrementalModelPersistence:
    """
    Manages a single evolving model file instead of creating new files per training.
    
    BENEFITS:
    - Single file that grows/evolves over time
    - No version explosion in models/ folder
    - Keeps history of updates in metadata
    
    FILE STRUCTURE (single file: incremental_model.pskc.json):
    {
        "model_name": "cache_predictor",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-02T12:00:00Z",
        "update_count": 42,
        "current_version": "v42",
        "metadata": {
            "total_training_samples": 100000,
            "total_retrains": 42,
            "last_retrain_reason": "scheduled",
            ...
        },
        "model_data": { ... },  # The actual model checkpoint
        "history": [            # Track all updates
            {
                "version": "v1",
                "timestamp": "...",
                "reason": "initial",
                "metrics": {...}
            },
            ...
        ]
    }
    """

    # Default filename for incremental model
    DEFAULT_INCREMENTAL_FILE = "incremental_model.pskc.json"

    def __init__(self, model_dir: str = None, model_name: str = None):
        self._model_dir = model_dir or settings.effective_ml_model_registry_dir
        self._model_name = model_name or settings.ml_model_name
        self._file_path = os.path.join(self._model_dir, self.DEFAULT_INCREMENTAL_FILE)
        
        # In-memory cache
        self._cache: Optional[Dict[str, Any]] = None
        self._dirty = False
        
        os.makedirs(self._model_dir, exist_ok=True)
        
        # Load existing model if present
        self._load()
        
        logger.info(f"IncrementalModelPersistence initialized: {self._file_path}")

    def _load(self) -> None:
        """Load model from file into memory"""
        if not os.path.exists(self._file_path):
            self._cache = None
            logger.info("No existing incremental model found, will create new one")
            return
            
        try:
            with open(self._file_path, 'r', encoding='utf-8') as f:
                self._cache = json.load(f)
            self._ensure_cache_defaults()
            logger.info(
                f"Loaded incremental model: update_count={self._cache.get('update_count', 0)}, "
                f"current_version={self._cache.get('current_version', 'N/A')}"
            )
        except Exception as e:
            logger.error(f"Failed to load incremental model: {e}")
            self._cache = None

    def _persist(self) -> bool:
        """Save current state to file"""
        if self._cache is None:
            return False
            
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self._file_path), exist_ok=True)
            
            # Write to temp file first, then rename (atomic operation)
            # Use process ID and timestamp to make temp file name unique
            import tempfile
            import uuid
            temp_fd, temp_path = tempfile.mkstemp(
                suffix=".tmp", 
                prefix=f"{os.path.basename(self._file_path)}.",
                dir=os.path.dirname(self._file_path)
            )
            try:
                with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                    json.dump(self._cache, f, indent=2, sort_keys=True)
                
                # Atomic rename
                os.replace(temp_path, self._file_path)
                
                self._dirty = False
                logger.debug(f"Saved incremental model to {self._file_path}")
                return True
            except Exception:
                # Clean up temp file on error
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
                raise
        except Exception as e:
            logger.error(f"Failed to persist incremental model: {e}")
            return False

    def exists(self) -> bool:
        """Check if incremental model exists"""
        return self._cache is not None and self._cache.get("model_data") is not None

    def _ensure_cache_defaults(self) -> None:
        """Backfill defaults for legacy incremental artifacts."""
        if self._cache is None:
            return

        history = self._cache.setdefault("history", [])
        update_count = int(self._cache.get("update_count", 0) or 0)
        self._cache.setdefault("attempt_count", update_count)
        self._cache.setdefault("current_version", f"v{update_count}")
        self._cache.setdefault("model_name", self._model_name)
        self._cache.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        self._cache.setdefault("updated_at", self._cache.get("created_at"))

        metadata = self._cache.setdefault("metadata", {})
        metadata.setdefault("total_training_samples", 0)
        metadata.setdefault("total_retrains", update_count)
        metadata.setdefault("last_retrain_reason", None)
        metadata.setdefault("last_training_attempt", {})

        last_accepted = None
        for entry in reversed(history):
            if entry.get("accepted", True):
                last_accepted = entry
                break

        if last_accepted is not None:
            metadata.setdefault("last_accepted_metrics", last_accepted.get("metrics", {}))
            metadata.setdefault("last_accepted_training_info", last_accepted.get("training_info", {}))
            metadata.setdefault("last_accepted_reason", last_accepted.get("reason"))
            metadata.setdefault("last_accepted_at", last_accepted.get("completed_at") or last_accepted.get("timestamp"))
            last_accuracy = self._extract_accuracy(last_accepted.get("metrics"))
            if last_accuracy is not None:
                metadata.setdefault("best_accuracy", last_accuracy)
        else:
            metadata.setdefault("last_accepted_metrics", {})
            metadata.setdefault("last_accepted_training_info", {})
            metadata.setdefault("last_accepted_reason", None)
            metadata.setdefault("last_accepted_at", None)
            metadata.setdefault("best_accuracy", None)

    def _extract_accuracy(self, metrics: Optional[Dict[str, Any]]) -> Optional[float]:
        if not metrics:
            return None

        for key in ("accuracy", "top_1_accuracy", "val_accuracy"):
            value = metrics.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
        return None

    def _build_empty_cache(self) -> Dict[str, Any]:
        return {
            "model_name": self._model_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "attempt_count": 0,
            "update_count": 0,
            "current_version": "v0",
            "metadata": {
                "total_training_samples": 0,
                "total_retrains": 0,
                "last_retrain_reason": None,
                "last_training_attempt": {},
                "last_accepted_metrics": {},
                "last_accepted_training_info": {},
                "last_accepted_reason": None,
                "last_accepted_at": None,
                "best_accuracy": None,
            },
            "model_data": None,
            "history": [],
        }

    def _evaluate_acceptance(
        self,
        metrics: Optional[Dict[str, Any]],
        training_info: Optional[Dict[str, Any]],
        reason: str,
    ) -> Dict[str, Any]:
        if self._cache is None or self._cache.get("model_data") is None:
            return {"accepted": True, "reason": "initial_model"}

        metadata = self._cache.get("metadata", {})
        current_accuracy = self._extract_accuracy(metrics)
        previous_accuracy = self._extract_accuracy(metadata.get("last_accepted_metrics"))
        if current_accuracy is None:
            return {"accepted": False, "reason": "missing_accuracy"}
        if previous_accuracy is None:
            return {"accepted": True, "reason": "no_previous_accuracy"}

        sample_count = int((training_info or {}).get("sample_count", 0) or 0)
        previous_sample_count = int((metadata.get("last_accepted_training_info") or {}).get("sample_count", 0) or 0)
        sample_delta = max(0, sample_count - previous_sample_count)

        min_improvement = float(getattr(settings, "ml_min_accuracy_for_version_bump", 0.01) or 0.01)
        min_sample_delta = int(getattr(settings, "ml_min_sample_delta_for_version_bump", 250) or 250)

        if current_accuracy >= previous_accuracy + min_improvement:
            return {
                "accepted": True,
                "reason": "meaningful_accuracy_improvement",
                "previous_accuracy": previous_accuracy,
                "current_accuracy": current_accuracy,
                "sample_delta": sample_delta,
            }

        if (
            reason in {"manual", "drift", "incremental"}
            and sample_delta >= min_sample_delta
            and current_accuracy > previous_accuracy
        ):
            return {
                "accepted": True,
                "reason": "manual_improvement_with_new_data",
                "previous_accuracy": previous_accuracy,
                "current_accuracy": current_accuracy,
                "sample_delta": sample_delta,
            }

        return {
            "accepted": False,
            "reason": "no_meaningful_improvement",
            "previous_accuracy": previous_accuracy,
            "current_accuracy": current_accuracy,
            "sample_delta": sample_delta,
            "required_improvement": min_improvement,
            "required_sample_delta": min_sample_delta,
        }

    def record_training_attempt(
        self,
        reason: str = "manual",
        metrics: Optional[Dict[str, float]] = None,
        training_info: Optional[Dict[str, Any]] = None,
        status: str = "rejected",
        detail: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Persist a training attempt without replacing the active model."""
        if self._cache is None:
            self._cache = self._build_empty_cache()
        else:
            self._ensure_cache_defaults()

        metadata = self._cache["metadata"]
        attempt_count = int(self._cache.get("attempt_count", 0) or 0) + 1
        self._cache["attempt_count"] = attempt_count
        now_iso = datetime.now(timezone.utc).isoformat()
        self._cache["updated_at"] = now_iso

        attempt_entry = {
            "attempt": attempt_count,
            "timestamp": now_iso,
            "completed_at": now_iso,
            "version": self._cache.get("current_version", "v0"),
            "resulting_version": self._cache.get("current_version", "v0"),
            "accepted": False,
            "status": status,
            "decision_reason": detail or status,
            "reason": reason,
            "metrics": metrics or {},
            "training_info": training_info or {},
        }

        metadata["last_training_attempt"] = {
            "attempt": attempt_count,
            "accepted": False,
            "status": status,
            "reason": reason,
            "detail": detail,
            "metrics": metrics or {},
            "training_info": training_info or {},
            "timestamp": now_iso,
            "resulting_version": self._cache.get("current_version", "v0"),
        }
        metadata["last_rejected_reason"] = detail or status
        metadata["last_rejected_at"] = now_iso

        history = self._cache.get("history", [])
        history.append(attempt_entry)
        if len(history) > 100:
            history = history[-100:]
        self._cache["history"] = history

        if not self._persist():
            return {"success": False, "reason": "persist_failed"}

        return {
            "success": True,
            "accepted": False,
            "version": self._cache.get("current_version", "v0"),
            "attempt_count": attempt_count,
            "decision_reason": detail or status,
            "status": status,
        }

    def get_model_data(self) -> Optional[Dict[str, Any]]:
        """Get the actual model data"""
        if self._cache is None:
            return None
        return self._cache.get("model_data")

    def set_model_data(self, model_data: Dict[str, Any]) -> bool:
        """Set/update the model data"""
        if self._cache is None:
            self._cache = self._build_empty_cache()
        else:
            self._ensure_cache_defaults()
            self._cache["model_data"] = model_data
            
        self._dirty = True
        return self._persist()

    def update(
        self,
        model_data: Dict[str, Any],
        reason: str = "manual",
        metrics: Optional[Dict[str, float]] = None,
        training_info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Update the incremental model with new data.
        
        Args:
            model_data: The new model checkpoint data
            reason: Reason for update (scheduled, drift, manual, etc.)
            metrics: Optional metrics from training
            training_info: Optional training info (samples, etc.)
            
        Returns:
            Update result dict
        """
        if self._cache is None:
            self._cache = self._build_empty_cache()
        else:
            self._ensure_cache_defaults()

        metadata = self._cache["metadata"]
        current_count = int(self._cache.get("update_count", 0) or 0)
        attempt_count = int(self._cache.get("attempt_count", current_count) or current_count) + 1
        decision = self._evaluate_acceptance(metrics=metrics, training_info=training_info, reason=reason)
        accepted = bool(decision.get("accepted"))
        new_count = current_count + 1 if accepted else current_count
        new_version = f"v{new_count}"
        now_iso = datetime.now(timezone.utc).isoformat()

        history_entry = {
            "attempt": attempt_count,
            "version": new_version if accepted else self._cache.get("current_version", "v0"),
            "resulting_version": new_version if accepted else self._cache.get("current_version", "v0"),
            "timestamp": now_iso,
            "completed_at": now_iso,
            "accepted": accepted,
            "status": "accepted" if accepted else "rejected",
            "decision_reason": decision.get("reason"),
            "reason": reason,
            "metrics": metrics or {},
            "training_info": training_info or {},
        }

        self._cache["updated_at"] = now_iso
        self._cache["attempt_count"] = attempt_count
        metadata["last_training_attempt"] = {
            "attempt": attempt_count,
            "accepted": accepted,
            "status": history_entry["status"],
            "reason": reason,
            "detail": decision.get("reason"),
            "metrics": metrics or {},
            "training_info": training_info or {},
            "timestamp": now_iso,
            "resulting_version": history_entry["resulting_version"],
        }

        if accepted:
            self._cache["update_count"] = new_count
            self._cache["current_version"] = new_version
            self._cache["model_data"] = model_data
            metadata["total_training_samples"] = (
                int(metadata.get("total_training_samples", 0) or 0) +
                int((training_info or {}).get("sample_count", 0) or 0)
            )
            metadata["total_retrains"] = int(metadata.get("total_retrains", 0) or 0) + 1
            metadata["last_retrain_reason"] = reason
            metadata["last_accepted_metrics"] = metrics or {}
            metadata["last_accepted_training_info"] = training_info or {}
            metadata["last_accepted_reason"] = reason
            metadata["last_accepted_at"] = now_iso
            current_accuracy = self._extract_accuracy(metrics)
            best_accuracy = metadata.get("best_accuracy")
            if current_accuracy is not None and (best_accuracy is None or current_accuracy > float(best_accuracy)):
                metadata["best_accuracy"] = current_accuracy
        else:
            metadata["last_rejected_reason"] = decision.get("reason")
            metadata["last_rejected_at"] = now_iso

        history = self._cache.get("history", [])
        history.append(history_entry)
        if len(history) > 100:
            history = history[-100:]
        self._cache["history"] = history
        
        # Persist to file
        if not self._persist():
            return {"success": False, "reason": "persist_failed"}
        
        if accepted:
            logger.info(
                "Incremental model updated: version=%s reason=%s total_updates=%s",
                self._cache["current_version"],
                reason,
                new_count,
            )
        else:
            logger.info(
                "Incremental model kept current version=%s after %s attempt (%s)",
                self._cache.get("current_version", "v0"),
                reason,
                decision.get("reason"),
            )
        
        return {
            "success": True,
            "accepted": accepted,
            "version": self._cache["current_version"],
            "update_count": self._cache["update_count"],
            "attempt_count": attempt_count,
            "total_retrains": self._cache["metadata"]["total_retrains"],
            "decision_reason": decision.get("reason"),
        }

    def get_info(self) -> Dict[str, Any]:
        """Get information about the incremental model"""
        if self._cache is None:
            return {
                "exists": False,
                "model_name": self._model_name,
                "file_path": self._file_path,
            }
        
        return {
            "exists": self.exists(),
            "has_model_data": self._cache.get("model_data") is not None,
            "model_name": self._cache.get("model_name"),
            "file_path": self._file_path,
            "current_version": self._cache.get("current_version"),
            "update_count": self._cache.get("update_count", 0),
            "attempt_count": self._cache.get("attempt_count", self._cache.get("update_count", 0)),
            "created_at": self._cache.get("created_at"),
            "updated_at": self._cache.get("updated_at"),
            "metadata": self._cache.get("metadata", {}),
            "history_count": len(self._cache.get("history", [])),
        }

    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent update history"""
        if self._cache is None:
            return []
        
        history = self._cache.get("history", [])
        return history[-limit:] if limit > 0 else history

    def rollback(self, target_version: Optional[str] = None) -> Dict[str, Any]:
        """
        Rollback to a previous version.
        
        Args:
            target_version: Version to rollback to (e.g., "v5"). 
                           If None, rolls back to previous version.
        """
        if self._cache is None:
            return {"success": False, "reason": "no_model_exists"}
        
        history = self._cache.get("history", [])
        if not history:
            return {"success": False, "reason": "no_history"}
        
        if target_version is None:
            # Rollback to previous (second to last)
            if len(history) < 2:
                return {"success": False, "reason": "no_previous_version"}
            target_entry = history[-2]
        else:
            # Find specific version
            target_entry = next(
                (h for h in history if h.get("version") == target_version),
                None
            )
            if target_entry is None:
                return {"success": False, "reason": "version_not_found"}
        
        # For now, we can't easily rollback model_data since it's overwritten
        # This would require storing model_data per history entry
        # For implementation, we'd need to store full model per history or implement
        # a more sophisticated versioning strategy
        
        logger.warning(
            f"Rollback requested to {target_version} but full rollback requires "
            f"storing model_data per history entry. Current implementation "
            f"only tracks metadata."
        )
        
        return {
            "success": False,
            "reason": "full_rollback_not_implemented",
            "target_version": target_entry.get("version"),
            "suggestion": "Use registry versioning for full model rollback",
        }

    def delete(self) -> bool:
        """Delete the incremental model file"""
        if self._cache is None:
            return True
            
        try:
            if os.path.exists(self._file_path):
                os.remove(self._file_path)
            self._cache = None
            logger.info(f"Deleted incremental model: {self._file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete incremental model: {e}")
            return False


# Global instance
_incremental_instance: Optional[IncrementalModelPersistence] = None


def get_incremental_model() -> IncrementalModelPersistence:
    """Get global incremental model persistence instance"""
    global _incremental_instance
    if _incremental_instance is None:
        _incremental_instance = IncrementalModelPersistence()
    return _incremental_instance
