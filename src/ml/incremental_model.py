# ============================================================
# PSKC — Incremental Model Persistence
# Supports single-file model that evolves over time
# Instead of creating new files per version, we update one file
# ============================================================
import json
import os
import time
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
            temp_path = self._file_path + ".tmp"
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(self._cache, f, indent=2, sort_keys=True)
            
            # Atomic rename
            os.replace(temp_path, self._file_path)
            
            self._dirty = False
            logger.debug(f"Saved incremental model to {self._file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to persist incremental model: {e}")
            return False

    def exists(self) -> bool:
        """Check if incremental model exists"""
        return self._cache is not None

    def get_model_data(self) -> Optional[Dict[str, Any]]:
        """Get the actual model data"""
        if self._cache is None:
            return None
        return self._cache.get("model_data")

    def set_model_data(self, model_data: Dict[str, Any]) -> bool:
        """Set/update the model data"""
        if self._cache is None:
            # Create new model structure
            self._cache = {
                "model_name": self._model_name,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "update_count": 0,
                "current_version": "v0",
                "metadata": {
                    "total_training_samples": 0,
                    "total_retrains": 0,
                },
                "model_data": model_data,
                "history": []
            }
        else:
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
        current_count = self._cache.get("update_count", 0) if self._cache else 0
        new_count = current_count + 1
        
        # Create history entry
        history_entry = {
            "version": f"v{new_count}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "metrics": metrics or {},
            "training_info": training_info or {},
        }
        
        if self._cache is None:
            # First time - create new model
            self._cache = {
                "model_name": self._model_name,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "update_count": new_count,
                "current_version": f"v{new_count}",
                "metadata": {
                    "total_training_samples": training_info.get("sample_count", 0) if training_info else 0,
                    "total_retrains": 1,
                    "last_retrain_reason": reason,
                },
                "model_data": model_data,
                "history": [history_entry]
            }
        else:
            # Update existing
            self._cache["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._cache["update_count"] = new_count
            self._cache["current_version"] = f"v{new_count}"
            self._cache["model_data"] = model_data
            
            # Update metadata
            self._cache["metadata"]["total_training_samples"] = (
                self._cache["metadata"].get("total_training_samples", 0) + 
                (training_info.get("sample_count", 0) if training_info else 0)
            )
            self._cache["metadata"]["total_retrains"] = (
                self._cache["metadata"].get("total_retrains", 0) + 1
            )
            self._cache["metadata"]["last_retrain_reason"] = reason
            
            # Add to history (keep last 100 entries to prevent file bloat)
            history = self._cache.get("history", [])
            history.append(history_entry)
            if len(history) > 100:
                history = history[-100:]
            self._cache["history"] = history
        
        # Persist to file
        if not self._persist():
            return {"success": False, "reason": "persist_failed"}
        
        logger.info(
            f"Incremental model updated: version={self._cache['current_version']}, "
            f"reason={reason}, total_updates={new_count}"
        )
        
        return {
            "success": True,
            "version": self._cache["current_version"],
            "update_count": new_count,
            "total_retrains": self._cache["metadata"]["total_retrains"],
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
            "exists": True,
            "model_name": self._cache.get("model_name"),
            "file_path": self._file_path,
            "current_version": self._cache.get("current_version"),
            "update_count": self._cache.get("update_count", 0),
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
