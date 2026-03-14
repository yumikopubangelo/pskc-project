import os
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config.settings import settings
from src.auth.key_fetcher import get_key_fetcher
from src.ml.data_collector import get_data_collector
from src.ml.model_registry import SecurityError, get_model_registry
from src.ml.predictor import get_key_predictor
from src.ml.trainer import get_model_trainer
from src.prefetch.queue import get_prefetch_queue

logger = logging.getLogger(__name__)


def _isoformat_timestamp(timestamp: float) -> Optional[str]:
    if not timestamp:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _bind_runtime_components() -> Dict[str, Any]:
    collector = get_data_collector()
    trainer = get_model_trainer()
    predictor = get_key_predictor()

    runtime_model_status = trainer.ensure_runtime_model_loaded()

    if predictor.model is not trainer.model:
        predictor.attach_model(
            trainer.model,
            source=runtime_model_status.get("source", trainer.get_active_model_metadata().get("source", "runtime")),
            version=runtime_model_status.get("version", trainer.get_active_model_metadata().get("version")),
            artifact_path=runtime_model_status.get("artifact_path", trainer.get_active_model_metadata().get("artifact_path")),
        )

    return {
        "collector": collector,
        "trainer": trainer,
        "predictor": predictor,
    }


def _sync_predictor_from_trainer(trainer: Any, predictor: Any, runtime_model_status: Optional[Dict[str, Any]] = None) -> None:
    runtime_model_status = runtime_model_status or trainer.get_active_model_metadata()
    predictor.attach_model(
        trainer.model,
        source=runtime_model_status.get("source", trainer.get_active_model_metadata().get("source", "runtime")),
        version=runtime_model_status.get("version", trainer.get_active_model_metadata().get("version")),
        artifact_path=runtime_model_status.get("artifact_path", trainer.get_active_model_metadata().get("artifact_path")),
    )
    predictor.clear_cache()


def _reload_active_runtime_model(model_name: Optional[str] = None) -> Dict[str, Any]:
    trainer = get_model_trainer()
    predictor = get_key_predictor()
    if model_name and model_name != trainer.model_name:
        return {"success": False, "reason": "model_name_mismatch"}

    try:
        load_result = trainer.load_active_model()
    except SecurityError as exc:
        return {"success": False, "reason": "integrity_verification_failed", "detail": str(exc)}

    if not load_result.get("success"):
        return load_result

    _sync_predictor_from_trainer(trainer, predictor, runtime_model_status=load_result)
    return load_result


def initialize_ml_runtime() -> Dict[str, Any]:
    runtime = _bind_runtime_components()
    trainer = runtime["trainer"]

    if not trainer.get_stats().get("auto_training"):
        trainer.start_auto_training()

    return runtime


def shutdown_ml_runtime() -> None:
    trainer = get_model_trainer()
    if trainer.get_stats().get("auto_training"):
        trainer.stop_auto_training()


def record_runtime_access(
    key_id: str,
    service_id: str,
    latency_ms: float,
    cache_hit: bool,
    **metadata: Any,
) -> None:
    runtime = _bind_runtime_components()
    collector = runtime["collector"]
    trainer = runtime["trainer"]

    collector.record_access(
        key_id=key_id,
        service_id=service_id,
        latency_ms=latency_ms,
        cache_hit=cache_hit,
        **metadata,
    )
    trainer.record_cache_outcome(key_id, cache_hit)


def get_ml_status_payload() -> Dict[str, Any]:
    runtime = _bind_runtime_components()
    collector = runtime["collector"]
    trainer = runtime["trainer"]
    predictor = runtime["predictor"]
    registry = get_model_registry()
    queue_stats = get_prefetch_queue().get_stats()

    collector_stats = collector.get_stats()
    trainer_stats = trainer.get_stats()
    model_stats = trainer_stats.get("model_stats", {})
    sample_count = int(collector_stats.get("total_events", 0))
    min_samples = int(trainer_stats.get("min_samples", 0))
    model_loaded = bool(getattr(trainer.model, "is_trained", False))
    artifact_path = trainer_stats.get("artifact_path")
    artifact_exists = bool(artifact_path and os.path.exists(artifact_path))
    model_name = trainer_stats.get("model_name")
    model_summary = registry.get_model_summary(model_name) if model_name else {}
    lifecycle_stats = registry.get_lifecycle_stats(model_name=model_name) if model_name else {}
    last_training = _isoformat_timestamp(float(trainer_stats.get("last_train_time") or 0))

    if not last_training and artifact_exists:
        last_training = datetime.fromtimestamp(os.path.getmtime(artifact_path), tz=timezone.utc).isoformat()

    if model_loaded:
        status = "trained"
    elif artifact_exists:
        status = "artifact_present"
    elif sample_count == 0:
        status = "not_trained"
    elif sample_count < min_samples:
        status = "collecting_data"
    else:
        status = "ready_for_training"

    return {
        "status": status,
        "model_loaded": model_loaded,
        "last_training": last_training,
        "sample_count": sample_count,
        "required_samples": min_samples,
        "auto_training": bool(trainer_stats.get("auto_training")),
        "prediction_cache_size": predictor.get_prediction_stats().get("cache_size", 0),
        "prefetch_queue": queue_stats,
        "collector_stats": collector_stats,
        "model_stats": model_stats,
        "drift_stats": trainer_stats.get("drift_stats", {}),
        "model_name": model_name,
        "active_version": trainer_stats.get("active_version"),
        "active_stage": model_summary.get("active_stage"),
        "artifact_path": artifact_path,
        "model_source": trainer_stats.get("model_source"),
        "model_registry": model_summary,
        "registry": registry.get_registry_stats(),
        "lifecycle": lifecycle_stats,
    }


def _resolve_model_name(model_name: Optional[str] = None) -> str:
    trainer = get_model_trainer()
    return model_name or trainer.model_name or settings.ml_model_name


def get_model_registry_payload(model_name: Optional[str] = None) -> Dict[str, Any]:
    effective_model_name = _resolve_model_name(model_name)
    registry = get_model_registry()
    return {
        "model_name": effective_model_name,
        "summary": registry.get_model_summary(effective_model_name),
        "stats": registry.get_registry_stats(),
    }


def get_model_lifecycle_payload(
    limit: int = 100,
    model_name: Optional[str] = None,
    event_type: Optional[str] = None,
) -> Dict[str, Any]:
    effective_model_name = _resolve_model_name(model_name)
    registry = get_model_registry()
    return {
        "model_name": effective_model_name,
        "events": registry.get_lifecycle_events(
            limit=limit,
            model_name=effective_model_name,
            event_type=event_type,
        ),
        "stats": registry.get_lifecycle_stats(model_name=effective_model_name),
    }


def get_prediction_payload(service_id: str = "default", n: int = 10) -> Dict[str, Any]:
    runtime = _bind_runtime_components()
    predictor = runtime["predictor"]
    trainer = runtime["trainer"]

    predictions = predictor.predict(service_id=service_id, n=n)
    source = "model" if getattr(trainer.model, "is_trained", False) else "hot_keys"

    return {
        "predictions": [
            {
                "key_id": key_id,
                "confidence": round(float(confidence), 4),
                "source": source,
            }
            for key_id, confidence in predictions
        ]
    }


def trigger_runtime_retraining(force: bool = True) -> Dict[str, Any]:
    runtime = _bind_runtime_components()
    trainer = runtime["trainer"]
    predictor = runtime["predictor"]

    result = trainer.train(force=force, reason="manual")
    predictor.attach_model(
        trainer.model,
        source=trainer.get_active_model_metadata().get("source", "registry"),
        version=trainer.get_active_model_metadata().get("version"),
        artifact_path=trainer.get_active_model_metadata().get("artifact_path"),
    )
    predictor.clear_cache()

    success = bool(result.get("success"))
    sample_count = int(result.get("sample_count") or trainer.get_stats().get("collector_stats", {}).get("total_events", 0))
    training_time = result.get("training_time_s")

    if success:
        evaluation = trainer.evaluate()
        message = "Runtime retraining completed"
    else:
        evaluation = {}
        reason = str(result.get("reason") or "unknown")
        message = f"Runtime retraining failed: {reason}"

    payload = {
        "success": success,
        "message": message,
        "sample_count": sample_count,
        "training_time": training_time,
        "last_training": _isoformat_timestamp(float(trainer.get_stats().get("last_train_time") or 0)),
        "active_version": trainer.get_stats().get("active_version"),
        "artifact_path": trainer.get_stats().get("artifact_path"),
    }

    if evaluation:
        payload["evaluation"] = evaluation

    return payload


def promote_runtime_model_version(
    model_name: str,
    version: str,
    target_stage: str,
    actor: str = "api",
    notes: str = "",
    make_active: bool = True,
) -> Dict[str, Any]:
    registry = get_model_registry()
    try:
        result = registry.promote_version(
            model_name=model_name,
            version=version,
            target_stage=target_stage,
            actor=actor,
            notes=notes,
            make_active=make_active,
        )
    except SecurityError as exc:
        return {"success": False, "reason": "integrity_verification_failed", "detail": str(exc)}

    if not result.get("success"):
        return result

    if make_active:
        runtime_reload = _reload_active_runtime_model(model_name=model_name)
        result["runtime_reload"] = runtime_reload
        if not runtime_reload.get("success"):
            result["success"] = False
            result["reason"] = "runtime_reload_failed"
            return result

    result["registry"] = get_model_registry_payload(model_name=model_name)
    return result


def rollback_runtime_model_version(
    model_name: str,
    version: Optional[str] = None,
    actor: str = "api",
    notes: str = "",
) -> Dict[str, Any]:
    registry = get_model_registry()
    try:
        result = registry.rollback_model(
            model_name=model_name,
            target_version=version,
            actor=actor,
            notes=notes,
        )
    except SecurityError as exc:
        return {"success": False, "reason": "integrity_verification_failed", "detail": str(exc)}

    if not result.get("success"):
        return result

    runtime_reload = _reload_active_runtime_model(model_name=model_name)
    result["runtime_reload"] = runtime_reload
    if not runtime_reload.get("success"):
        result["success"] = False
        result["reason"] = "runtime_reload_failed"
        return result

    result["registry"] = get_model_registry_payload(model_name=model_name)
    return result


async def run_request_path_prefetch(
    secure_manager: Any,
    service_id: str,
    source_key_id: str,
    candidates: List[Dict[str, Any]],
    ip_address: str = "",
) -> Dict[str, Any]:
    if not candidates:
        return {
            "prefetched_count": 0,
            "predictions_considered": 0,
            "attempted_count": 0,
            "already_cached_count": 0,
            "missing_keys": [],
            "failed_store_keys": [],
            "prefetched_keys": [],
        }

    fetcher = get_key_fetcher()
    fetched_keys = await fetcher.fetch_keys_batch(
        [item["key_id"] for item in candidates],
        service_id,
    )

    prefetched_count = 0
    already_cached_count = 0
    missing_keys: List[str] = []
    failed_store_keys: List[str] = []
    prefetched_keys: List[str] = []
    for candidate in candidates:
        key_id = candidate["key_id"]
        priority = float(candidate.get("priority", 0.0))
        key_data = fetched_keys.get(key_id)
        if secure_manager.secure_exists(key_id, service_id):
            already_cached_count += 1
            continue
        if not key_data:
            missing_keys.append(key_id)
            continue
        if secure_manager.secure_set(
            key_id,
            key_data,
            service_id,
            ip_address=ip_address,
            predicted=True,
            priority=priority,
        ):
            prefetched_count += 1
            prefetched_keys.append(key_id)
        else:
            failed_store_keys.append(key_id)

    if prefetched_count:
        logger.info(
            "Prefetch completed for service=%s source_key=%s prefetched=%s",
            service_id,
            source_key_id,
            prefetched_count,
        )

    return {
        "prefetched_count": prefetched_count,
        "predictions_considered": len(candidates),
        "attempted_count": len(candidates),
        "already_cached_count": already_cached_count,
        "missing_keys": missing_keys,
        "failed_store_keys": failed_store_keys,
        "prefetched_keys": prefetched_keys,
    }


def _build_prefetch_candidates(
    secure_manager: Any,
    service_id: str,
    source_key_id: str,
) -> List[Dict[str, Any]]:
    runtime = _bind_runtime_components()
    predictor = runtime["predictor"]
    predictions = predictor.predict(
        service_id=service_id,
        n=max(settings.ml_top_n_predictions, 5),
        min_confidence=0.0,
    )

    if not predictions:
        return []

    prioritized_candidates: List[Dict[str, Any]] = []
    for key_id, priority in predictions:
        if key_id == source_key_id:
            continue
        if secure_manager.secure_exists(key_id, service_id):
            continue
        prioritized_candidates.append(
            {
                "key_id": key_id,
                "priority": round(float(priority), 4),
            }
        )

    return prioritized_candidates


def schedule_request_path_prefetch(
    secure_manager: Any,
    service_id: str,
    source_key_id: str,
    ip_address: str = "",
) -> Dict[str, Any]:
    candidates = _build_prefetch_candidates(secure_manager, service_id, source_key_id)

    if not candidates:
        return {"mode": "noop", "prefetched_count": 0, "predictions_considered": 0}

    queue_payload = {
        "job_id": str(uuid.uuid4()),
        "service_id": service_id,
        "source_key_id": source_key_id,
        "ip_address": ip_address,
        "candidates": candidates,
        "enqueued_at": datetime.now(timezone.utc).isoformat(),
    }

    queue = get_prefetch_queue()
    if queue.enqueue(queue_payload):
        logger.info(
            "Scheduled prefetch job via Redis for service=%s source_key=%s candidates=%s",
            service_id,
            source_key_id,
            len(candidates),
        )
        return {
            "mode": "redis_queue",
            "prefetched_count": 0,
            "predictions_considered": len(candidates),
        }

    import asyncio

    result = asyncio.run(
        run_request_path_prefetch(
            secure_manager=secure_manager,
            service_id=service_id,
            source_key_id=source_key_id,
            candidates=candidates,
            ip_address=ip_address,
        )
    )
    result["mode"] = "direct_fallback"
    return result


def get_prefetch_metrics_payload() -> Dict[str, Any]:
    return get_prefetch_queue().get_stats()


def get_prefetch_dlq_payload(limit: int = 20) -> Dict[str, Any]:
    queue = get_prefetch_queue()
    stats = queue.get_stats()
    return {
        "items": queue.get_dlq(limit=limit),
        "count": stats.get("dlq_length", 0),
    }


def get_accuracy_history_payload(limit: int = 12) -> Dict[str, List[Dict[str, Any]]]:
    trainer = get_model_trainer()
    history = trainer.get_training_history()[-limit:]
    data: List[Dict[str, Any]] = []

    for index, item in enumerate(history, start=1):
        accuracy = item.get("val_accuracy")
        if accuracy is None:
            continue

        completed_at = item.get("completed_at")
        if completed_at:
            try:
                label = datetime.fromisoformat(completed_at).astimezone(timezone.utc).strftime("%H:%M:%S")
            except ValueError:
                label = f"Train {index}"
        else:
            label = f"Train {index}"

        data.append(
            {
                "time": label,
                "accuracy": round(float(accuracy) * 100, 1),
            }
        )

    return {"data": data}
