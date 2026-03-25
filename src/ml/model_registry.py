import hashlib
import hashlib
import hmac
import json
import logging
import os
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

from config.settings import settings
from src.ml.model import EnsembleModel, MarkovChainPredictor
from src.ml.model_improvements import RFPreprocessor
from src.security.fips_module import FipsCryptographicModule

logger = logging.getLogger(__name__)


class SecurityError(Exception):
    """Custom exception for model registry security violations."""


@dataclass
class ModelVersion:
    """Model version metadata."""

    version: str
    created_at: float = field(default_factory=time.time)
    metrics: Dict[str, float] = field(default_factory=dict)
    file_path: str = ""
    description: str = ""
    is_active: bool = False
    checksum: str = ""
    signature: str = ""
    artifact_type: str = ""
    stage: str = "development"
    provenance: Dict[str, Any] = field(default_factory=dict)


class PortableLabelEncoder:
    """
    Minimal label-encoder compatible object for safe checkpoint restores.
    
    Improvements (Issue #20):
    - Handles unseen labels gracefully with a special OOV (out-of-vocabulary) index
    - Supports encoding/decoding without crashing on new keys
    """

    def __init__(self, classes: List[str], oov_index: int = -1):
        self.classes_ = np.array(classes, dtype=object)
        self._index = {label: idx for idx, label in enumerate(classes)}
        self.oov_index = oov_index  # Out-of-vocabulary index for unseen keys

    def transform(self, labels: List[str]) -> np.ndarray:
        """
        Transform labels to indices, using oov_index for unseen entries.
        """
        return np.array(
            [self._index.get(label, self.oov_index) for label in labels],
            dtype=np.int64
        )

    def inverse_transform(self, indices: List[int]) -> np.ndarray:
        """
        Transform indices back to labels, handling oov_index gracefully.
        """
        result = []
        for idx in indices:
            if 0 <= idx < len(self.classes_):
                result.append(self.classes_[idx])
            else:
                # Return special marker for OOV
                result.append("<OOV>")
        return np.array(result, dtype=object)
    
    def get_classes(self) -> np.ndarray:
        """Return the list of known classes."""
        return self.classes_.copy()
    
    def get_num_classes(self) -> int:
        """Return the number of known classes."""
        return len(self.classes_)


class PortableRandomForestModel:
    """
    Safe, JSON-backed inference wrapper for a trained sklearn RandomForest.
    Stores only primitive arrays and exposes the small surface used by the runtime.
    """

    def __init__(
        self,
        trees: List[Dict[str, Any]],
        label_encoder_classes: List[str],
        n_estimators: int,
        max_depth: Optional[int],
    ):
        self._trees = trees
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.label_encoder = PortableLabelEncoder(label_encoder_classes)
        self.is_trained = True

    @classmethod
    def from_sklearn_wrapper(cls, rf_wrapper: Any) -> "PortableRandomForestModel":
        if rf_wrapper is None or not getattr(rf_wrapper, "is_trained", False):
            raise ValueError("RandomForest wrapper is not trained")

        estimators = getattr(getattr(rf_wrapper, "model", None), "estimators_", None)
        if estimators is None:
            raise ValueError("RandomForest wrapper does not expose estimators_")

        trees: List[Dict[str, Any]] = []
        for estimator in estimators:
            tree = estimator.tree_
            trees.append(
                {
                    "children_left": tree.children_left.tolist(),
                    "children_right": tree.children_right.tolist(),
                    "feature": tree.feature.tolist(),
                    "threshold": tree.threshold.tolist(),
                    "value": tree.value.squeeze(axis=1).tolist(),
                }
            )

        label_encoder = getattr(rf_wrapper, "label_encoder", None)
        classes = getattr(label_encoder, "classes_", None)
        if classes is None:
            raise ValueError("RandomForest wrapper does not expose label encoder classes")

        return cls(
            trees=trees,
            label_encoder_classes=[str(item) for item in classes.tolist()],
            n_estimators=int(getattr(rf_wrapper, "n_estimators", len(trees))),
            max_depth=getattr(rf_wrapper, "max_depth", None),
        )

    @classmethod
    def from_checkpoint(cls, payload: Dict[str, Any]) -> "PortableRandomForestModel":
        return cls(
            trees=list(payload.get("trees", [])),
            label_encoder_classes=list(payload.get("label_encoder_classes", [])),
            n_estimators=int(payload.get("n_estimators", 0)),
            max_depth=payload.get("max_depth"),
        )

    def to_checkpoint(self) -> Dict[str, Any]:
        return {
            "artifact_type": "portable_random_forest_v1",
            "n_estimators": self.n_estimators,
            "max_depth": self.max_depth,
            "label_encoder_classes": self.label_encoder.classes_.tolist(),
            "trees": self._trees,
        }

    def _predict_tree_proba(self, tree: Dict[str, Any], row: np.ndarray) -> np.ndarray:
        children_left = tree["children_left"]
        children_right = tree["children_right"]
        feature = tree["feature"]
        threshold = tree["threshold"]
        value = tree["value"]

        node = 0
        while children_left[node] != -1 and children_right[node] != -1:
            split_feature = feature[node]
            node = (
                children_left[node]
                if float(row[split_feature]) <= float(threshold[node])
                else children_right[node]
            )

        leaf_counts = np.array(value[node], dtype=np.float64)
        total = float(leaf_counts.sum())
        if total <= 0:
            return np.full_like(leaf_counts, fill_value=1.0 / max(len(leaf_counts), 1), dtype=np.float64)
        return leaf_counts / total

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        X_arr = np.atleast_2d(np.asarray(X, dtype=np.float64))
        if not self._trees:
            return np.zeros((len(X_arr), len(self.label_encoder.classes_)), dtype=np.float64)

        rows: List[np.ndarray] = []
        for row in X_arr:
            votes = np.zeros(len(self.label_encoder.classes_), dtype=np.float64)
            for tree in self._trees:
                votes += self._predict_tree_proba(tree, row)
            rows.append(votes / len(self._trees))
        return np.vstack(rows)

    def predict(self, X: np.ndarray) -> np.ndarray:
        probabilities = self.predict_proba(X)
        return probabilities.argmax(axis=1)


def _serialize_markov(markov: MarkovChainPredictor) -> Dict[str, Any]:
    return {
        "num_classes": markov.num_classes,
        "smoothing": markov.smoothing,
        "max_history": markov.max_history,
        "transition_counts": {
            source_key: dict(destinations)
            for source_key, destinations in markov._transition_counts.items()
        },
        "key_index": dict(markov._key_index),
        "history": list(markov._history),
        "last_key": markov._last_key,
    }


def _restore_markov(payload: Dict[str, Any]) -> MarkovChainPredictor:
    markov = MarkovChainPredictor(
        num_classes=int(payload.get("num_classes", 100)),
        smoothing=float(payload.get("smoothing", 0.1)),
        max_history=int(payload.get("max_history", 10_000)),
    )
    transition_counts = payload.get("transition_counts", {})
    markov._transition_counts.clear()
    for source_key, destinations in transition_counts.items():
        markov._transition_counts[source_key].update(
            {dest_key: int(count) for dest_key, count in destinations.items()}
        )
    markov._key_index = {str(key): int(idx) for key, idx in payload.get("key_index", {}).items()}
    markov._index_key = {idx: key for key, idx in markov._key_index.items()}
    markov._history.clear()
    for item in payload.get("history", []):
        markov._history.append(str(item))
    markov._last_key = payload.get("last_key")
    return markov


class ModelRegistry:
    """
    Model storage and versioning with integrity checks, artifact signatures,
    immutable provenance, and lifecycle history.

    Supported secure formats:
    - `.pskc.json`: JSON checkpoint for EnsembleModel with portable RF + Markov state
    - `.pt`: torch checkpoint loaded with `weights_only=True`
    """

    MODEL_SIGNING_KEY_LABEL = "model-registry-signing-key-v1"
    DEFAULT_SIGNING_SEED = "pskc-dev-model-registry-signing-seed"

    def __init__(self, model_dir: str = "/app/data/models"):
        self._model_dir = model_dir
        self._versions: Dict[str, List[ModelVersion]] = {}
        self._active_models: Dict[str, ModelVersion] = {}
        self._checksums: Dict[str, str] = {}
        self._fips_module = self._build_signing_module()

        os.makedirs(model_dir, exist_ok=True)

        self._load_checksums()
        self._load_versions()
        
        # Clean up any old temp files on startup (Issue #17)
        self._cleanup_temp_files()

        logger.info("ModelRegistry initialized: dir=%s", model_dir)

    @property
    def model_dir(self) -> str:
        return self._model_dir
    
    def _cleanup_temp_files(self) -> None:
        """
        Clean up temporary files older than 1 hour (Issue #17).
        Called on registry initialization to prevent disk space leaks.
        """
        try:
            import glob
            now = time.time()
            max_age_seconds = 3600  # 1 hour
            
            # Find all .tmp files
            tmp_files = glob.glob(os.path.join(self._model_dir, "*.tmp"))
            removed = 0
            
            for tmp_path in tmp_files:
                try:
                    # Check file age
                    file_age = now - os.path.getmtime(tmp_path)
                    if file_age > max_age_seconds:
                        os.remove(tmp_path)
                        removed += 1
                        logger.debug(f"Removed orphaned temp file: {tmp_path}")
                except OSError as e:
                    logger.warning(f"Failed to clean up temp file {tmp_path}: {e}")
            
            if removed > 0:
                logger.info(f"Cleaned up {removed} orphaned temp files from {self._model_dir}")
        
        except Exception as e:
            logger.warning(f"Temp file cleanup failed: {e}")

    @property
    def model_dir(self) -> str:
        return self._model_dir

    def _checksum_manifest_path(self) -> str:
        return os.path.join(self._model_dir, "checksums.json")

    def _registry_metadata_path(self) -> str:
        return os.path.join(self._model_dir, "registry.json")

    def _lifecycle_log_path(self) -> str:
        return os.path.join(self._model_dir, "lifecycle.jsonl")

    def _build_signing_module(self) -> FipsCryptographicModule:
        signing_seed = (
            settings.ml_model_signing_key
            or settings.cache_encryption_key
            or self.DEFAULT_SIGNING_SEED
        )
        if not settings.ml_model_signing_key and not settings.cache_encryption_key:
            logger.warning(
                "ML model signing is using a development fallback seed. "
                "Set ML_MODEL_SIGNING_KEY or CACHE_ENCRYPTION_KEY for stable signatures."
            )
        master_key = FipsCryptographicModule.derive_key_hkdf(
            signing_seed.encode("utf-8"),
            "pskc-model-registry-master-key-v1",
        )
        return FipsCryptographicModule(master_key)

    def _default_stage(self) -> str:
        return settings.ml_model_stage or settings.app_env or "development"

    def _normalize_metrics(self, metrics: Optional[Dict[str, Any]]) -> Dict[str, float]:
        normalized: Dict[str, float] = {}
        for key, value in (metrics or {}).items():
            try:
                normalized[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
        return normalized

    def _normalize_provenance(self, provenance: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if provenance is None:
            return {}
        return json.loads(json.dumps(provenance, sort_keys=True, default=str))

    def _infer_artifact_type(self, file_path: str, payload: Optional[Dict[str, Any]] = None) -> str:
        if payload and payload.get("artifact_type"):
            return str(payload["artifact_type"])
        if file_path.endswith(".pskc.json"):
            return "pskc_ensemble_v1"
        if file_path.endswith(".pt"):
            return "torch_state_dict_v1"
        if file_path.endswith(".pkl"):
            return "unsafe_pickle"
        return "unknown"

    def _serialize_version_entry(self, version: ModelVersion) -> Dict[str, Any]:
        return {
            "version": version.version,
            "created_at": version.created_at,
            "metrics": version.metrics,
            "file_path": version.file_path,
            "description": version.description,
            "is_active": version.is_active,
            "checksum": version.checksum,
            "signature": version.signature,
            "artifact_type": version.artifact_type,
            "stage": version.stage,
            "provenance": version.provenance,
        }

    def _signature_payload_bytes(self, model_name: str, version: ModelVersion) -> bytes:
        payload = {
            "model_name": model_name,
            "version": version.version,
            "created_at": round(float(version.created_at), 6),
            "artifact_type": version.artifact_type,
            "checksum": version.checksum,
            "metrics": self._normalize_metrics(version.metrics),
            "description": version.description,
            "provenance": self._normalize_provenance(version.provenance),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")

    def _sign_version(self, model_name: str, version: ModelVersion) -> str:
        signature = self._fips_module.sign_data(
            self._signature_payload_bytes(model_name, version),
            self.MODEL_SIGNING_KEY_LABEL,
        )
        return signature.hex()

    def _verify_version_signature(self, model_name: str, version: ModelVersion) -> bool:
        if not version.signature:
            return False
        try:
            signature = bytes.fromhex(version.signature)
        except ValueError:
            return False
        return self._fips_module.verify_signature(
            signature,
            self._signature_payload_bytes(model_name, version),
            self.MODEL_SIGNING_KEY_LABEL,
        )

    def _append_lifecycle_event(
        self,
        event_type: str,
        model_name: str,
        version: Optional[str] = None,
        actor: str = "system",
        stage: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            "model_name": model_name,
            "version": version,
            "actor": actor,
            "stage": stage,
            "details": self._normalize_provenance(details),
        }
        with open(self._lifecycle_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(event, sort_keys=True) + "\n")

    def _compute_checksum(self, file_path: str) -> str:
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()

    def _persist_checksums(self) -> None:
        with open(self._checksum_manifest_path(), "w", encoding="utf-8") as f:
            json.dump(self._checksums, f, indent=2, sort_keys=True)

    def _upsert_checksum(self, file_path: str) -> str:
        filename = os.path.basename(file_path)
        checksum = self._compute_checksum(file_path)
        self._checksums[filename] = checksum
        self._persist_checksums()
        return checksum

    def _remove_checksum(self, file_path: str) -> None:
        filename = os.path.basename(file_path)
        if filename in self._checksums:
            del self._checksums[filename]
            self._persist_checksums()

    def _load_checksums(self) -> None:
        checksum_file = self._checksum_manifest_path()
        if not os.path.exists(checksum_file):
            self._checksums = {}
            return

        try:
            with open(checksum_file, "r", encoding="utf-8") as f:
                self._checksums = json.load(f)
            logger.info("Loaded %s model checksums.", len(self._checksums))
        except Exception as exc:
            logger.error("Failed to load or parse checksums.json: %s", exc)
            self._checksums = {}

    def _load_versions(self) -> None:
        metadata_file = self._registry_metadata_path()
        if not os.path.exists(metadata_file):
            return

        try:
            with open(metadata_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for model_name, versions in data.items():
                self._versions[model_name] = [ModelVersion(**entry) for entry in versions]
                for version in self._versions[model_name]:
                    if version.is_active:
                        self._active_models[model_name] = version
            logger.info("Loaded %s models from registry", len(self._versions))
        except Exception as exc:
            logger.error("Failed to load registry: %s", exc)

    def _save_registry(self) -> None:
        data = {
            model_name: [self._serialize_version_entry(version) for version in versions]
            for model_name, versions in self._versions.items()
        }

        with open(self._registry_metadata_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)

    def _resolve_version(self, model_name: str, version: Optional[str] = None) -> Optional[ModelVersion]:
        if version is None:
            return self.get_active_version(model_name)

        return next(
            (item for item in self._versions.get(model_name, []) if item.version == version),
            None,
        )

    def _ensure_version_security_metadata(self, model_name: str, version: ModelVersion) -> None:
        if not os.path.exists(version.file_path):
            return

        actual_checksum = self._compute_checksum(version.file_path)
        filename = os.path.basename(version.file_path)
        manifest_checksum = self._checksums.get(filename)
        changed = False
        security_backfilled = False

        if manifest_checksum and not hmac.compare_digest(manifest_checksum, actual_checksum):
            raise SecurityError(f"Checksum manifest mismatch for {version.file_path}")
        if version.checksum and not hmac.compare_digest(version.checksum, actual_checksum):
            raise SecurityError(f"Version metadata checksum mismatch for {version.file_path}")

        if not manifest_checksum:
            self._checksums[filename] = actual_checksum
            changed = True
        if not version.checksum:
            version.checksum = actual_checksum
            changed = True
            security_backfilled = True
        if not version.artifact_type:
            version.artifact_type = self._infer_artifact_type(version.file_path)
            changed = True
            security_backfilled = True
        if not version.stage:
            version.stage = self._default_stage()
            changed = True
        if not isinstance(version.provenance, dict):
            version.provenance = {}
            changed = True
            security_backfilled = True
        if not version.signature:
            version.signature = self._sign_version(model_name, version)
            changed = True
            security_backfilled = True

        if changed:
            self._persist_checksums()
            self._save_registry()
        if security_backfilled:
            self._append_lifecycle_event(
                "backfill_security_metadata",
                model_name=model_name,
                version=version.version,
                actor="registry",
                stage=version.stage,
                details={"file_path": version.file_path},
            )

    def _verify_artifact_integrity(self, model_name: str, version: ModelVersion) -> None:
        if not os.path.exists(version.file_path):
            raise SecurityError(f"Model file not found: {version.file_path}")

        actual_checksum = self._compute_checksum(version.file_path)
        filename = os.path.basename(version.file_path)
        manifest_checksum = self._checksums.get(filename)

        if not manifest_checksum:
            raise SecurityError(f"No checksum manifest entry for {version.file_path}")
        if not version.checksum:
            raise SecurityError(f"No version checksum metadata for {version.file_path}")
        if not hmac.compare_digest(actual_checksum, manifest_checksum):
            raise SecurityError(f"Checksum manifest verification failed for {version.file_path}")
        if not hmac.compare_digest(actual_checksum, version.checksum):
            raise SecurityError(f"Version checksum verification failed for {version.file_path}")
        if not self._verify_version_signature(model_name, version):
            raise SecurityError(f"Signature verification failed for {version.file_path}")

    def register_model(
        self,
        model_name: str,
        version: str,
        file_path: str,
        metrics: Optional[Dict[str, float]] = None,
        description: str = "",
        checksum: Optional[str] = None,
        signature: str = "",
        artifact_type: str = "",
        stage: Optional[str] = None,
        provenance: Optional[Dict[str, Any]] = None,
        actor: str = "system",
    ) -> ModelVersion:
        if model_name not in self._versions:
            self._versions[model_name] = []

        normalized_metrics = self._normalize_metrics(metrics)
        normalized_provenance = self._normalize_provenance(provenance)
        effective_stage = stage or self._default_stage()

        model_version = next(
            (item for item in self._versions[model_name] if item.version == version),
            None,
        )
        if model_version is None:
            model_version = ModelVersion(
                version=version,
                file_path=file_path,
                metrics=normalized_metrics,
                description=description,
                is_active=False,
                checksum=checksum or "",
                signature=signature,
                artifact_type=artifact_type or self._infer_artifact_type(file_path),
                stage=effective_stage,
                provenance=normalized_provenance,
            )
            self._versions[model_name].append(model_version)
        else:
            model_version.file_path = file_path
            model_version.metrics = normalized_metrics
            model_version.description = description
            model_version.created_at = time.time()
            model_version.checksum = checksum or model_version.checksum
            model_version.signature = signature or model_version.signature
            model_version.artifact_type = (
                artifact_type
                or model_version.artifact_type
                or self._infer_artifact_type(file_path)
            )
            model_version.stage = effective_stage
            model_version.provenance = normalized_provenance

        if os.path.exists(file_path):
            model_version.checksum = checksum or self._upsert_checksum(file_path)
        if not model_version.signature and model_version.checksum:
            model_version.signature = self._sign_version(model_name, model_version)
        self._save_registry()
        self._append_lifecycle_event(
            "register",
            model_name=model_name,
            version=model_version.version,
            actor=actor,
            stage=model_version.stage,
            details={
                "artifact_type": model_version.artifact_type,
                "checksum": model_version.checksum,
                "file_path": model_version.file_path,
            },
        )
        logger.info("Registered model %s:%s", model_name, version)
        return model_version

    def get_active_artifact_path(self, model_name: str) -> Optional[str]:
        version = self.get_active_version(model_name)
        if version is None:
            return None
        return version.file_path

    def set_active_version(
        self,
        model_name: str,
        version: str,
        actor: str = "system",
        reason: str = "activate",
        details: Optional[Dict[str, Any]] = None,
    ) -> bool:
        versions = self._versions.get(model_name)
        if not versions:
            logger.warning("Model not found: %s", model_name)
            return False

        previous_active = self.get_active_version(model_name)
        target_version: Optional[ModelVersion] = None
        for item in versions:
            item.is_active = False
            if item.version == version:
                item.is_active = True
                target_version = item

        if target_version is None:
            logger.warning("Version not found: %s:%s", model_name, version)
            return False

        self._active_models[model_name] = target_version
        self._save_registry()
        self._append_lifecycle_event(
            reason,
            model_name=model_name,
            version=version,
            actor=actor,
            stage=target_version.stage,
            details={
                "previous_active_version": previous_active.version if previous_active else None,
                **self._normalize_provenance(details),
            },
        )
        logger.info("Set active version: %s:%s", model_name, version)
        return True

    def get_active_version(self, model_name: str) -> Optional[ModelVersion]:
        if model_name in self._active_models:
            return self._active_models[model_name]

        versions = self._versions.get(model_name, [])
        for version in versions:
            if version.is_active:
                self._active_models[model_name] = version
                return version
        return None

    def get_versions(self, model_name: str) -> List[ModelVersion]:
        return self._versions.get(model_name, [])

    def get_latest_version(self, model_name: str) -> Optional[ModelVersion]:
        versions = self._versions.get(model_name, [])
        if not versions:
            return None
        return max(versions, key=lambda item: item.created_at)

    def list_versions(self, model_name: str) -> List[Dict[str, Any]]:
        versions = sorted(
            self._versions.get(model_name, []),
            key=lambda item: item.created_at,
            reverse=True,
        )
        return [self._serialize_version_entry(version) for version in versions]

    def get_model_summary(self, model_name: str) -> Dict[str, Any]:
        active_version = self.get_active_version(model_name)
        return {
            "model_name": model_name,
            "active_version": active_version.version if active_version else None,
            "active_stage": active_version.stage if active_version else None,
            "active_artifact_path": active_version.file_path if active_version else None,
            "versions": self.list_versions(model_name),
            "lifecycle": self.get_lifecycle_stats(model_name=model_name),
        }

    def serialize_model_checkpoint(self, model: Any) -> Dict[str, Any]:
        if isinstance(model, EnsembleModel):
            portable_rf = None
            if getattr(model, "rf", None) is not None and getattr(model.rf, "is_trained", False):
                portable_rf = PortableRandomForestModel.from_sklearn_wrapper(model.rf).to_checkpoint()

            rf_preproc = None
            if getattr(model, "rf_preprocessor", None) is not None:
                rf_preproc = model.rf_preprocessor.to_dict()

            return {
                "artifact_type": "pskc_ensemble_v1",
                "num_classes": int(model.num_classes),
                "dynamic_weights": bool(model.dynamic_weights),
                "static_weights": dict(getattr(model, "_static_weights", {})),
                "is_trained": bool(getattr(model, "is_trained", False)),
                "rf": portable_rf,
                "rf_preprocessor": rf_preproc,
                "markov": _serialize_markov(model.markov),
            }

        raise SecurityError(f"Unsupported secure model type: {type(model).__name__}")

    def _deserialize_model_checkpoint(self, payload: Dict[str, Any]) -> Any:
        artifact_type = payload.get("artifact_type")
        if artifact_type != "pskc_ensemble_v1":
            logger.warning("Unknown secure model artifact type: %s", artifact_type)
            return None

        static_weights = payload.get("static_weights", {})
        model = EnsembleModel(
            lstm_weight=float(static_weights.get("lstm", 0.5)),
            rf_weight=float(static_weights.get("rf", 0.35)),
            markov_weight=float(static_weights.get("markov", 0.15)),
            num_classes=int(payload.get("num_classes", 100)),
            dynamic_weights=bool(payload.get("dynamic_weights", True)),
        )

        rf_payload = payload.get("rf")
        model.rf = PortableRandomForestModel.from_checkpoint(rf_payload) if rf_payload else None
        model.markov = _restore_markov(payload.get("markov", {}))

        rf_preproc_payload = payload.get("rf_preprocessor")
        model.rf_preprocessor = RFPreprocessor.from_dict(rf_preproc_payload) if rf_preproc_payload else None

        model.is_trained = bool(payload.get("is_trained", False))
        return model

    def load_model(
        self,
        model_name: str,
        version: Optional[str] = None,
        actor: str = "runtime",
    ) -> Any:
        resolved_version = self._resolve_version(model_name, version=version)
        if resolved_version is None:
            logger.warning("No version available for %s", model_name)
            return None

        # Cross-environment path resolution (Docker absolute path vs Windows local)
        if not os.path.exists(resolved_version.file_path):
            basename = os.path.basename(resolved_version.file_path)
            local_path = os.path.join(self._model_dir, basename)
            if os.path.exists(local_path):
                resolved_version.file_path = local_path
                self._save_registry()

        self._ensure_version_security_metadata(model_name, resolved_version)
        self._verify_artifact_integrity(model_name, resolved_version)

        try:
            if resolved_version.file_path.endswith(".pt"):
                import torch

                loaded_model = torch.load(resolved_version.file_path, weights_only=True)

            elif resolved_version.file_path.endswith(".pskc.json") or resolved_version.file_path.endswith(".json"):
                with open(resolved_version.file_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                loaded_model = self._deserialize_model_checkpoint(payload)

            elif resolved_version.file_path.endswith(".pkl"):
                logger.error(
                    "Attempted to load a '.pkl' file (%s), which is disallowed for security reasons.",
                    resolved_version.file_path,
                )
                raise SecurityError("Loading of .pkl files is not permitted due to security risks.")
            else:
                logger.warning("Unknown model format: %s", resolved_version.file_path)
                return None
        except SecurityError:
            raise
        except Exception as exc:
            logger.error(
                f"Failed to load model '{model_name}' version '{resolved_version.version}': {exc}",
                exc_info=True,
                extra={
                    "model_file": resolved_version.file_path,
                    "artifact_type": resolved_version.artifact_type,
                    "error_type": type(exc).__name__
                }
            )
            return None

        self._append_lifecycle_event(
            "load",
            model_name=model_name,
            version=resolved_version.version,
            actor=actor,
            stage=resolved_version.stage,
            details={"artifact_path": resolved_version.file_path},
        )
        return loaded_model

    def save_model(
        self,
        model_name: str,
        model: Any,
        version: str,
        metrics: Optional[Dict[str, float]] = None,
        description: str = "",
        provenance: Optional[Dict[str, Any]] = None,
        stage: Optional[str] = None,
        actor: str = "system",
        activate: bool = True,
    ) -> bool:
        try:
            checkpoint_payload: Optional[Dict[str, Any]] = None
            if isinstance(model, EnsembleModel):
                checkpoint_payload = self.serialize_model_checkpoint(model)
                file_path = os.path.join(self._model_dir, f"{model_name}_{version}.pskc.json")
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(checkpoint_payload, f, indent=2, sort_keys=True)
            else:
                try:
                    import torch
                except ImportError as exc:
                    raise SecurityError("Torch checkpoint save requested but torch is not available.") from exc

                if not hasattr(model, "state_dict"):
                    raise SecurityError(
                        f"Unsupported model type for secure save: {type(model).__name__}"
                    )

                file_path = os.path.join(self._model_dir, f"{model_name}_{version}.pt")
                torch.save(model.state_dict(), file_path)

            checksum = self._upsert_checksum(file_path)
            artifact_type = self._infer_artifact_type(file_path, checkpoint_payload)
            normalized_provenance = {
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "actor": actor,
                "source": "registry.save_model",
                "app_env": settings.app_env,
                **self._normalize_provenance(provenance),
            }

            registered_version = self.register_model(
                model_name=model_name,
                version=version,
                file_path=file_path,
                metrics=metrics,
                description=description,
                checksum=checksum,
                artifact_type=artifact_type,
                stage=stage or self._default_stage(),
                provenance=normalized_provenance,
                actor=actor,
            )
            registered_version.signature = self._sign_version(model_name, registered_version)
            self._save_registry()
            self._append_lifecycle_event(
                "sign",
                model_name=model_name,
                version=version,
                actor=actor,
                stage=registered_version.stage,
                details={"artifact_type": artifact_type, "checksum": checksum},
            )
            if activate:
                self.set_active_version(
                    model_name,
                    version,
                    actor=actor,
                    reason="activate",
                    details={"source": "save_model"},
                )

            logger.info("Saved model to %s with checksum and signature metadata updated.", file_path)
            return True
        except SecurityError as exc:
            logger.error("Failed to save model securely: %s", exc)
            return False
        except Exception as exc:
            logger.error("Failed to save model: %s", exc)
            return False

    def promote_version(
        self,
        model_name: str,
        version: str,
        target_stage: str,
        actor: str = "system",
        notes: str = "",
        make_active: bool = True,
    ) -> Dict[str, Any]:
        target_version = self._resolve_version(model_name, version=version)
        if target_version is None:
            return {"success": False, "reason": "version_not_found"}

        self._ensure_version_security_metadata(model_name, target_version)
        self._verify_artifact_integrity(model_name, target_version)

        previous_stage = target_version.stage
        target_version.stage = target_stage
        self._save_registry()
        self._append_lifecycle_event(
            "promote",
            model_name=model_name,
            version=version,
            actor=actor,
            stage=target_stage,
            details={
                "previous_stage": previous_stage,
                "notes": notes,
                "make_active": make_active,
            },
        )
        if make_active:
            self.set_active_version(
                model_name,
                version,
                actor=actor,
                reason="activate",
                details={"source": "promote_version", "notes": notes},
            )

        return {
            "success": True,
            "model_name": model_name,
            "version": version,
            "stage": target_stage,
            "active": bool(make_active),
        }

    def rollback_model(
        self,
        model_name: str,
        target_version: Optional[str] = None,
        actor: str = "system",
        notes: str = "",
    ) -> Dict[str, Any]:
        versions = sorted(self._versions.get(model_name, []), key=lambda item: item.created_at)
        if not versions:
            return {"success": False, "reason": "model_not_found"}

        current_active = self.get_active_version(model_name)
        target: Optional[ModelVersion] = None

        if target_version:
            target = self._resolve_version(model_name, version=target_version)
        else:
            candidates = [item for item in versions if current_active is None or item.version != current_active.version]
            if current_active is not None:
                older_candidates = [item for item in candidates if item.created_at <= current_active.created_at]
                target = older_candidates[-1] if older_candidates else (candidates[-1] if candidates else None)
            elif candidates:
                target = candidates[-1]

        if target is None:
            return {"success": False, "reason": "rollback_target_not_found"}

        self._ensure_version_security_metadata(model_name, target)
        self._verify_artifact_integrity(model_name, target)

        if current_active is not None and current_active.stage and target.stage != current_active.stage:
            target.stage = current_active.stage
            self._save_registry()

        activated = self.set_active_version(
            model_name,
            target.version,
            actor=actor,
            reason="rollback_activate",
            details={
                "from_version": current_active.version if current_active else None,
                "notes": notes,
            },
        )
        if not activated:
            return {"success": False, "reason": "rollback_activation_failed"}

        self._append_lifecycle_event(
            "rollback",
            model_name=model_name,
            version=target.version,
            actor=actor,
            stage=target.stage,
            details={
                "from_version": current_active.version if current_active else None,
                "notes": notes,
            },
        )
        return {
            "success": True,
            "model_name": model_name,
            "version": target.version,
            "stage": target.stage,
            "rolled_back_from": current_active.version if current_active else None,
        }

    def get_lifecycle_events(
        self,
        limit: int = 100,
        model_name: Optional[str] = None,
        event_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if limit < 1 or not os.path.exists(self._lifecycle_log_path()):
            return []

        events: List[Dict[str, Any]] = []
        with open(self._lifecycle_log_path(), "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if model_name and event.get("model_name") != model_name:
                    continue
                if event_type and event.get("event") != event_type:
                    continue
                events.append(event)
        return events[-limit:]

    def get_lifecycle_stats(self, model_name: Optional[str] = None) -> Dict[str, Any]:
        events = self.get_lifecycle_events(limit=10_000, model_name=model_name)
        counter = Counter(event.get("event", "unknown") for event in events)
        latest_event = events[-1] if events else None
        return {
            "events_total": len(events),
            "events_by_type": dict(counter),
            "last_event_at": latest_event.get("timestamp") if latest_event else None,
        }

    def delete_version(self, model_name: str, version: str, actor: str = "system") -> bool:
        versions = self._versions.get(model_name)
        if not versions:
            return False

        target_version = next((item for item in versions if item.version == version), None)
        if target_version is None:
            return False

        if os.path.exists(target_version.file_path):
            try:
                os.remove(target_version.file_path)
            except Exception as exc:
                logger.error("Failed to delete model file: %s", exc)
            else:
                self._remove_checksum(target_version.file_path)

        self._versions[model_name] = [item for item in versions if item.version != version]
        if model_name in self._active_models and self._active_models[model_name].version == version:
            del self._active_models[model_name]

        self._save_registry()
        self._append_lifecycle_event(
            "delete",
            model_name=model_name,
            version=version,
            actor=actor,
            stage=target_version.stage,
            details={"file_path": target_version.file_path},
        )
        logger.info("Deleted model %s:%s", model_name, version)
        return True

    def get_registry_stats(self) -> Dict[str, Any]:
        return {
            "total_models": len(self._versions),
            "active_models": len(self._active_models),
            "signed_versions": sum(1 for versions in self._versions.values() for version in versions if version.signature),
            "unsigned_versions": sum(1 for versions in self._versions.values() for version in versions if not version.signature),
            "lifecycle": self.get_lifecycle_stats(),
            "models": {
                name: {
                    "versions": len(versions),
                    "active": self._active_models.get(name).version if name in self._active_models else None,
                    "active_stage": self._active_models.get(name).stage if name in self._active_models else None,
                    "stages": dict(Counter((version.stage or "unknown") for version in versions)),
                    "signed_versions": sum(1 for version in versions if version.signature),
                    "unsigned_versions": sum(1 for version in versions if not version.signature),
                }
                for name, versions in self._versions.items()
            },
        }

    def __del__(self):
        try:
            self._fips_module.destroy()
        except Exception:
            pass


_registry_instance: Optional[ModelRegistry] = None
_registry_lock = threading.Lock()


def get_model_registry() -> ModelRegistry:
    global _registry_instance
    if _registry_instance is None:
        with _registry_lock:
            if _registry_instance is None:
                _registry_instance = ModelRegistry(model_dir=settings.effective_ml_model_registry_dir)
    return _registry_instance
