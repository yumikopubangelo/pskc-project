import json
import os
import time
from types import SimpleNamespace

import numpy as np
import pytest

from src.api import ml_service
from src.ml.data_collector import DataCollector
from src.ml.incremental_model import IncrementalModelPersistence
from src.ml.model import EnsembleModel, SKLEARN_AVAILABLE
from src.ml.predictor import KeyPredictor
from src.ml.model_registry import ModelRegistry, SecurityError
from src.ml.trainer import ModelTrainer


class _FakeCollector:
    def __init__(self, events):
        self._events = list(events)

    def get_stats(self):
        return {"total_events": len(self._events)}

    def get_access_sequence(self, window_seconds=3600, max_events=10_000):
        return self._events[-max_events:]


def _build_trained_ensemble_model() -> EnsembleModel:
    if not SKLEARN_AVAILABLE:
        pytest.skip("scikit-learn not available")

    model = EnsembleModel(num_classes=3)
    if model.rf is None:
        pytest.skip("RandomForest sub-model not available")

    X = np.array(
        [
            [0.0, 0.0, 0.0],
            [0.1, 0.2, 0.1],
            [1.0, 1.0, 1.0],
            [1.1, 0.9, 1.2],
            [2.0, 2.0, 2.0],
            [2.2, 1.9, 2.1],
        ],
        dtype=np.float64,
    )
    y = np.array(["key_a", "key_a", "key_b", "key_b", "key_c", "key_c"], dtype=object)

    model.rf.fit(X, y)
    for key_id in ["key_a", "key_b", "key_c", "key_a", "key_b"]:
        model.markov.update(key_id)
    model.is_trained = True
    return model


def _build_access_events(total_events: int = 60) -> list[dict]:
    base_timestamp = time.time()
    keys = ["key_a", "key_b", "key_c"]
    events = []
    for index in range(total_events):
        ts = base_timestamp + index
        events.append(
            {
                "key_id": keys[index % len(keys)],
                "service_id": "svc-a",
                "timestamp": ts,
                "hour": time.localtime(ts).tm_hour,
                "day_of_week": time.localtime(ts).tm_wday,
                "cache_hit": 1 if index % 4 != 0 else 0,
                "latency_ms": 5.0 if index % 4 != 0 else 180.0,
            }
        )
    return events


def test_model_registry_saves_and_loads_secure_ensemble_checkpoint(tmp_path):
    registry = ModelRegistry(model_dir=str(tmp_path))
    model = _build_trained_ensemble_model()

    saved = registry.save_model(
        model_name="pskc_model",
        model=model,
        version="v1",
        metrics={"test_accuracy": 0.91},
        description="test checkpoint",
    )

    assert saved is True

    active_version = registry.get_active_version("pskc_model")
    assert active_version is not None
    assert active_version.file_path.endswith(".pskc.json")
    assert active_version.signature
    assert active_version.stage == "development"
    assert active_version.provenance["source"] == "registry.save_model"

    checksum_manifest = json.loads((tmp_path / "checksums.json").read_text(encoding="utf-8"))
    assert os.path.basename(active_version.file_path) in checksum_manifest

    loaded_model = registry.load_model("pskc_model")

    assert loaded_model is not None
    assert loaded_model.is_trained is True
    assert loaded_model.markov.n_transitions > 0
    assert loaded_model.rf is not None

    probabilities = loaded_model.rf.predict_proba(np.array([[0.05, 0.1, 0.05]], dtype=np.float64))
    assert probabilities.shape == (1, len(loaded_model.rf.label_encoder.classes_))
    assert np.isclose(probabilities.sum(), 1.0)


def test_model_registry_still_rejects_pickle_artifacts(tmp_path):
    registry = ModelRegistry(model_dir=str(tmp_path))
    pickle_path = tmp_path / "unsafe_v1.pkl"
    pickle_path.write_bytes(b"not-a-safe-pickle")

    registry.register_model(
        model_name="unsafe_model",
        version="v1",
        file_path=str(pickle_path),
        metrics={"test_accuracy": 0.0},
        description="unsafe artifact",
    )
    registry.set_active_version("unsafe_model", "v1")

    with pytest.raises(SecurityError):
        registry.load_model("unsafe_model")


def test_train_script_produces_registry_compatible_artifact(tmp_path, monkeypatch):
    from scripts import train_model as train_script

    model_dir = tmp_path / "models"
    registry = ModelRegistry(model_dir=str(model_dir))

    training_data = train_script.generate_synthetic_data(
        n_samples=180,
        num_keys=12,
        num_services=3,
        seed=7,
    )

    monkeypatch.setattr(train_script, "get_model_registry", lambda: registry)
    monkeypatch.setattr(train_script, "load_training_data", lambda data_path=None: training_data)

    success = train_script.train_model(
        data_path=None,
        model_name="pskc_model",
        version="integration_v1",
        n_estimators=16,
        max_depth=6,
    )

    assert success is True

    active_version = registry.get_active_version("pskc_model")
    assert active_version is not None
    assert active_version.file_path.endswith(".pskc.json")
    assert os.path.exists(active_version.file_path)
    assert active_version.stage == "development"
    assert active_version.provenance["source"] == "scripts.train_model"
    assert active_version.provenance["hyperparameters"]["n_estimators"] == 16

    loaded_model = registry.load_model("pskc_model")
    assert loaded_model is not None
    assert loaded_model.is_trained is True


def test_model_registry_rejects_tampered_artifact_contents(tmp_path):
    registry = ModelRegistry(model_dir=str(tmp_path))
    model = _build_trained_ensemble_model()
    assert registry.save_model(model_name="pskc_model", model=model, version="v1") is True

    active_version = registry.get_active_version("pskc_model")
    assert active_version is not None
    with open(active_version.file_path, "a", encoding="utf-8") as handle:
        handle.write("\n")

    with pytest.raises(SecurityError):
        registry.load_model("pskc_model")


def test_model_registry_rejects_tampered_signed_metadata(tmp_path):
    registry = ModelRegistry(model_dir=str(tmp_path))
    model = _build_trained_ensemble_model()
    assert registry.save_model(model_name="pskc_model", model=model, version="v1") is True

    registry_metadata_path = tmp_path / "registry.json"
    payload = json.loads(registry_metadata_path.read_text(encoding="utf-8"))
    payload["pskc_model"][0]["description"] = "tampered description"
    registry_metadata_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    reloaded_registry = ModelRegistry(model_dir=str(tmp_path))
    with pytest.raises(SecurityError):
        reloaded_registry.load_model("pskc_model")


def test_model_registry_loads_artifact_with_windows_style_relative_path(tmp_path):
    registry = ModelRegistry(model_dir=str(tmp_path))
    model = _build_trained_ensemble_model()
    assert registry.save_model(model_name="pskc_model", model=model, version="v1") is True

    registry_metadata_path = tmp_path / "registry.json"
    payload = json.loads(registry_metadata_path.read_text(encoding="utf-8"))
    payload["pskc_model"][0]["file_path"] = f"data\\\\models\\\\{os.path.basename(payload['pskc_model'][0]['file_path'])}"
    registry_metadata_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    reloaded_registry = ModelRegistry(model_dir=str(tmp_path))
    loaded_model = reloaded_registry.load_model("pskc_model")

    assert loaded_model is not None
    assert loaded_model.is_trained is True
    assert reloaded_registry.get_active_version("pskc_model").file_path.endswith(".pskc.json")


def test_model_registry_promote_and_rollback_update_active_version_and_lifecycle(tmp_path):
    registry = ModelRegistry(model_dir=str(tmp_path))
    model = _build_trained_ensemble_model()

    assert registry.save_model(
        model_name="pskc_model",
        model=model,
        version="v1",
        stage="staging",
        provenance={"source": "test"},
    ) is True
    assert registry.save_model(
        model_name="pskc_model",
        model=model,
        version="v2",
        stage="staging",
        provenance={"source": "test"},
    ) is True

    promote_result = registry.promote_version(
        model_name="pskc_model",
        version="v1",
        target_stage="production",
        actor="tester",
        notes="promote for rollout",
        make_active=True,
    )

    assert promote_result["success"] is True
    assert registry.get_active_version("pskc_model").version == "v1"
    assert registry.get_active_version("pskc_model").stage == "production"

    rollback_result = registry.rollback_model(
        model_name="pskc_model",
        actor="tester",
        notes="rollback after validation",
    )

    assert rollback_result["success"] is True
    assert rollback_result["version"] == "v2"
    assert registry.get_active_version("pskc_model").version == "v2"
    assert registry.get_active_version("pskc_model").stage == "production"

    lifecycle_stats = registry.get_lifecycle_stats(model_name="pskc_model")
    assert lifecycle_stats["events_by_type"]["promote"] >= 1
    assert lifecycle_stats["events_by_type"]["rollback"] >= 1
    assert (
        lifecycle_stats["events_by_type"].get("activate", 0) >= 1
        or lifecycle_stats["events_by_type"].get("rollback_activate", 0) >= 1
    )


def test_portable_runtime_predictions_do_not_depend_on_sklearn_flag(tmp_path, monkeypatch):
    import src.ml.model as model_module

    registry = ModelRegistry(model_dir=str(tmp_path))
    model = _build_trained_ensemble_model()
    registry.save_model(model_name="pskc_model", model=model, version="portable_v1")

    loaded_model = registry.load_model("pskc_model")
    assert loaded_model is not None

    monkeypatch.setattr(model_module, "SKLEARN_AVAILABLE", False)

    top_indices, probabilities = loaded_model.predict_top_n(
        n=2,
        X_rf=np.array([[0.05, 0.1, 0.05]], dtype=np.float64),
        current_key=None,
    )

    assert len(top_indices) == 2
    assert len(probabilities) == 2


def test_trainer_loads_active_secure_model_from_registry(tmp_path):
    registry = ModelRegistry(model_dir=str(tmp_path))
    model = _build_trained_ensemble_model()
    registry.save_model(model_name="pskc_model", model=model, version="bootstrap_v1")

    trainer = ModelTrainer(model_name="pskc_model", registry=registry)
    load_result = trainer.load_active_model()

    assert load_result["success"] is True
    assert trainer.model.is_trained is True
    assert trainer.get_active_model_metadata()["version"] == "bootstrap_v1"
    assert trainer.get_active_model_metadata()["artifact_path"].endswith(".pskc.json")


def test_trainer_retraining_persists_new_active_secure_artifact(tmp_path):
    registry = ModelRegistry(model_dir=str(tmp_path))
    bootstrap_model = _build_trained_ensemble_model()
    registry.save_model(model_name="pskc_model", model=bootstrap_model, version="bootstrap_v1")

    trainer = ModelTrainer(model_name="pskc_model", registry=registry, min_samples=10)
    load_result = trainer.load_active_model()
    assert load_result["success"] is True

    trainer._collector = _FakeCollector(_build_access_events())

    result = trainer.train(force=True, reason="manual")

    assert result["success"] is True
    assert result["registry_version"] != "bootstrap_v1"
    assert result["artifact_path"].endswith(".pskc.json")
    assert result["active_version"] == result["registry_version"]

    active_version = registry.get_active_version("pskc_model")
    assert active_version is not None
    assert active_version.version == "bootstrap_v1"

    reloaded_model = trainer.load_active_model()
    assert reloaded_model["success"] is True
    assert reloaded_model["version"] == result["registry_version"]

    loaded_model = trainer.model
    assert loaded_model is not None
    assert loaded_model.is_trained is True

    persisted_info = trainer.get_stats()["incremental_info"]
    assert persisted_info["current_version"] == result["registry_version"]
    assert persisted_info["has_model_data"] is True

    reloaded_registry_model = registry.load_model("pskc_model")
    assert reloaded_registry_model is not None
    assert reloaded_registry_model.is_trained is True


def test_predictor_bootstraps_from_registry_active_model(tmp_path, monkeypatch):
    from src.ml import predictor as predictor_module

    registry = ModelRegistry(model_dir=str(tmp_path))
    model = _build_trained_ensemble_model()
    registry.save_model(model_name="pskc_model", model=model, version="predictor_v1")

    collector = DataCollector(max_events=256)
    for event in _build_access_events(total_events=20):
        collector.record_access(
            key_id=event["key_id"],
            service_id=event["service_id"],
            cache_hit=bool(event["cache_hit"]),
            latency_ms=event["latency_ms"],
            timestamp=event["timestamp"],
        )

    monkeypatch.setattr(predictor_module, "get_model_registry", lambda: registry)

    predictor = KeyPredictor(model=None, top_n=3, threshold=0.0)
    predictor._collector = collector

    predictions = predictor.predict(service_id="svc-a", n=3, min_confidence=0.0)
    stats = predictor.get_prediction_stats()

    assert predictions
    assert stats["model_loaded"] is True
    assert stats["model_source"] == "registry"
    assert stats["model_version"] == "predictor_v1"
    assert stats["artifact_path"].endswith(".pskc.json")


def test_incremental_persistence_rejects_version_bump_without_meaningful_improvement(tmp_path):
    incremental = IncrementalModelPersistence(model_dir=str(tmp_path), model_name="pskc_model")

    first = incremental.update(
        model_data={"checkpoint": 1},
        reason="manual",
        metrics={"accuracy": 0.62, "top_10_accuracy": 0.91},
        training_info={"sample_count": 240, "train_samples": 168, "val_samples": 72},
    )
    second = incremental.update(
        model_data={"checkpoint": 2},
        reason="scheduled",
        metrics={"accuracy": 0.625, "top_10_accuracy": 0.915},
        training_info={"sample_count": 260, "train_samples": 182, "val_samples": 78},
    )

    assert first["accepted"] is True
    assert first["version"] == "v1"
    assert second["accepted"] is False
    assert second["version"] == "v1"

    info = incremental.get_info()
    assert info["current_version"] == "v1"
    assert info["attempt_count"] == 2

    history = incremental.get_history(limit=5)
    assert history[-1]["accepted"] is False
    assert history[-1]["decision_reason"] == "no_meaningful_improvement"


def test_incremental_persistence_quarantines_oversized_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr("config.settings.settings.ml_incremental_model_max_mb", 1)
    oversized_path = tmp_path / IncrementalModelPersistence.DEFAULT_INCREMENTAL_FILE
    oversized_path.write_text("x" * (2 * 1024 * 1024), encoding="utf-8")

    incremental = IncrementalModelPersistence(model_dir=str(tmp_path), model_name="pskc_model")

    assert incremental.exists() is False
    assert not oversized_path.exists()
    backups = list(tmp_path.glob("incremental_model.pskc.json.oversized_*.bak"))
    assert backups


def test_incremental_persistence_switches_to_recovery_file_when_oversized_artifact_is_locked(tmp_path, monkeypatch):
    monkeypatch.setattr("config.settings.settings.ml_incremental_model_max_mb", 1)
    oversized_path = tmp_path / IncrementalModelPersistence.DEFAULT_INCREMENTAL_FILE
    oversized_path.write_text("x" * (2 * 1024 * 1024), encoding="utf-8")

    original_replace = os.replace

    def _locked_replace(src, dst):
        if str(src) == str(oversized_path):
            raise PermissionError("file is locked")
        return original_replace(src, dst)

    monkeypatch.setattr("src.ml.incremental_model.os.replace", _locked_replace)

    incremental = IncrementalModelPersistence(model_dir=str(tmp_path), model_name="pskc_model")
    info = incremental.get_info()

    assert info["file_path"].endswith(IncrementalModelPersistence.RECOVERY_INCREMENTAL_FILE)
    assert incremental.exists() is False


def test_trainer_retains_active_version_when_retrain_does_not_improve(tmp_path, monkeypatch):
    registry = ModelRegistry(model_dir=str(tmp_path / "registry"))
    incremental = IncrementalModelPersistence(model_dir=str(tmp_path / "incremental"), model_name="pskc_model")
    bootstrap_model = _build_trained_ensemble_model()

    incremental.update(
        model_data=registry.serialize_model_checkpoint(bootstrap_model),
        reason="manual",
        metrics={"accuracy": 0.63, "top_10_accuracy": 0.94},
        training_info={"sample_count": 300, "train_samples": 210, "val_samples": 90},
    )

    trainer = ModelTrainer(
        model_name="pskc_model",
        registry=registry,
        incremental_persistence=incremental,
        min_samples=10,
    )
    load_result = trainer.load_active_model()
    assert load_result["success"] is True
    assert trainer.get_active_model_metadata()["version"] == "v1"

    trainer._collector = _FakeCollector(_build_access_events())
    monkeypatch.setattr(
        trainer,
        "_quick_eval",
        lambda model, X_val, y_val, access_data, validation_offset: {
            "accuracy": 0.631,
            "top_10_accuracy": 0.941,
            "n_samples": len(y_val),
        },
    )

    result = trainer.train(force=True, reason="scheduled")

    assert result["success"] is True
    assert result["model_accepted"] is False
    assert result["version_bumped"] is False
    assert result["active_version"] == "v1"
    assert result["registry_version"] == "v1"


def test_ml_status_payload_uses_persisted_incremental_accuracy_when_runtime_history_is_empty(tmp_path, monkeypatch):
    registry = ModelRegistry(model_dir=str(tmp_path / "registry"))
    incremental = IncrementalModelPersistence(model_dir=str(tmp_path / "incremental"), model_name="pskc_model")
    model = _build_trained_ensemble_model()

    incremental.update(
        model_data=registry.serialize_model_checkpoint(model),
        reason="manual",
        metrics={"accuracy": 0.67, "top_10_accuracy": 0.96},
        training_info={"sample_count": 320, "train_samples": 224, "val_samples": 96},
    )

    trainer = ModelTrainer(
        model_name="pskc_model",
        registry=registry,
        incremental_persistence=incremental,
        min_samples=10,
    )
    trainer.load_active_model()
    trainer._training_history = []

    fake_collector = SimpleNamespace(get_stats=lambda: {"total_events": 320})
    fake_predictor = SimpleNamespace(model=trainer.model, attach_model=lambda *args, **kwargs: None)

    monkeypatch.setattr(
        ml_service,
        "_bind_runtime_components",
        lambda: {
            "collector": fake_collector,
            "trainer": trainer,
            "predictor": fake_predictor,
        },
    )
    monkeypatch.setattr(
        ml_service,
        "get_model_registry",
        lambda: SimpleNamespace(
            get_model_summary=lambda model_name: {"active_stage": "production"},
        ),
    )

    payload = ml_service.get_ml_status_payload()

    assert payload["model_version"] == "v1"
    assert payload["model_accuracy"] == pytest.approx(0.67)
    assert payload["model_top_10_accuracy"] == pytest.approx(0.96)
    assert payload["best_accuracy"] == pytest.approx(0.67)
    assert payload["model_loaded"] is True
    assert payload["last_attempt_accuracy"] == pytest.approx(0.67)
    assert payload["last_attempt_top_10_accuracy"] == pytest.approx(0.96)
    assert payload["accuracy_confidence"] == "medium"


def test_ml_status_payload_marks_small_validation_sets_as_low_confidence(tmp_path, monkeypatch):
    registry = ModelRegistry(model_dir=str(tmp_path / "registry"))
    incremental = IncrementalModelPersistence(model_dir=str(tmp_path / "incremental"), model_name="pskc_model")
    model = _build_trained_ensemble_model()

    incremental.update(
        model_data=registry.serialize_model_checkpoint(model),
        reason="manual",
        metrics={"accuracy": 1.0, "top_10_accuracy": 1.0},
        training_info={"sample_count": 60, "train_samples": 42, "val_samples": 18},
    )

    trainer = ModelTrainer(
        model_name="pskc_model",
        registry=registry,
        incremental_persistence=incremental,
        min_samples=10,
    )
    trainer.load_active_model()
    trainer._training_history = []

    fake_collector = SimpleNamespace(get_stats=lambda: {"total_events": 60})
    fake_predictor = SimpleNamespace(model=trainer.model, attach_model=lambda *args, **kwargs: None)

    monkeypatch.setattr(
        ml_service,
        "_bind_runtime_components",
        lambda: {
            "collector": fake_collector,
            "trainer": trainer,
            "predictor": fake_predictor,
        },
    )
    monkeypatch.setattr(
        ml_service,
        "get_model_registry",
        lambda: SimpleNamespace(
            get_model_summary=lambda model_name: {"active_stage": "development"},
        ),
    )

    payload = ml_service.get_ml_status_payload()

    assert payload["model_accuracy"] == pytest.approx(1.0)
    assert payload["accepted_validation_samples"] == 18
    assert payload["accuracy_confidence"] == "low"
    assert "Validation sample count is still small" in payload["accuracy_warning"]
