import os
import logging
import uuid
import threading
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
_ml_warmup_lock = threading.Lock()
_ml_warmup_started = False


def _isoformat_timestamp(timestamp: float) -> Optional[str]:
    if not timestamp or timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _extract_accuracy_from_history_item(item: Dict[str, Any]) -> Optional[float]:
    for key in ("val_accuracy", "accuracy", "top_1_accuracy"):
        value = item.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

    metrics = item.get("metrics", {})
    for key in ("accuracy", "top_1_accuracy", "val_accuracy"):
        value = metrics.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


def _extract_top10_from_history_item(item: Dict[str, Any]) -> Optional[float]:
    for key in ("val_top_10_accuracy", "top_10_accuracy"):
        value = item.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

    metrics = item.get("metrics", {})
    value = metrics.get("top_10_accuracy")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_attempt_accuracy(last_training_attempt: Dict[str, Any]) -> Optional[float]:
    if not last_training_attempt:
        return None
    return _extract_accuracy_from_history_item({"metrics": last_training_attempt.get("metrics", {})})


def _extract_attempt_top10(last_training_attempt: Dict[str, Any]) -> Optional[float]:
    if not last_training_attempt:
        return None
    return _extract_top10_from_history_item({"metrics": last_training_attempt.get("metrics", {})})


def _accuracy_confidence(val_samples: Optional[int]) -> str:
    try:
        sample_count = int(val_samples or 0)
    except (TypeError, ValueError):
        sample_count = 0

    if sample_count >= 500:
        return "high"
    if sample_count >= 75:
        return "medium"
    return "low"


def _accuracy_warning(val_samples: Optional[int]) -> Optional[str]:
    confidence = _accuracy_confidence(val_samples)
    if confidence == "low":
        return "Validation sample count is still small (<75). Generate more training data to get a reliable accuracy estimate."
    if confidence == "medium":
        return "Validation coverage is moderate (75-499 samples). Treat the metric as directional, not final."
    return None


def _bind_runtime_components(*, load_runtime_model: bool = True) -> Dict[str, Any]:
    collector = get_data_collector()
    trainer = get_model_trainer()
    predictor = get_key_predictor()

    runtime_model_status = trainer.get_active_model_metadata()
    if load_runtime_model:
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


def _warm_ml_runtime_in_background() -> None:
    global _ml_warmup_started

    with _ml_warmup_lock:
        if _ml_warmup_started:
            return
        _ml_warmup_started = True

    def _worker() -> None:
        try:
            logger.info("Starting lazy ML runtime warmup in background")
            _bind_runtime_components(load_runtime_model=False)
            try:
                trainer = get_model_trainer()
                trainer.ensure_runtime_model_loaded()
            except Exception:
                logger.warning("Background ML model warmup failed", exc_info=True)
            logger.info("Background ML runtime warmup finished")
        except Exception:
            logger.warning("Background ML runtime component warmup failed", exc_info=True)

    threading.Thread(
        target=_worker,
        name="pskc-ml-warmup",
        daemon=True,
    ).start()


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
    # Keep API startup fast. Collector hydration and secure model loading can
    # take tens of seconds on larger datasets, so we warm them asynchronously
    # after the HTTP server becomes available instead of blocking readiness.
    _warm_ml_runtime_in_background()

    logger.info(
        "ML runtime initialized in lazy mode — "
        "background warmup started and ML Worker handles scheduled/drift training"
    )

    return {
        "lazy": True,
        "warmup_started": True,
    }


def shutdown_ml_runtime() -> None:
    from src.ml import trainer as trainer_module

    trainer = getattr(trainer_module, "_trainer_instance", None)
    if trainer is not None and trainer.get_stats().get("auto_training"):
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
    try:
        runtime = _bind_runtime_components(load_runtime_model=False)
    except TypeError:
        # Backward compatibility for tests or older monkeypatches that still
        # provide the previous zero-argument helper signature.
        runtime = _bind_runtime_components()
    collector = runtime["collector"]
    trainer = runtime["trainer"]

    collector_stats = collector.get_stats()
    current_model = getattr(trainer, "_model", None)
    model_stats = current_model.get_model_stats() if current_model is not None else {}
    sample_count = int(collector_stats.get("total_events", 0))
    min_samples = int(getattr(trainer, "_min_samples", 0) or 0)
    model_loaded = bool(getattr(current_model, "is_trained", False))
    artifact_path = getattr(trainer, "_active_artifact_path", None)
    artifact_exists = bool(artifact_path and os.path.exists(artifact_path))
    model_name = getattr(trainer, "_model_name", None)
    model_summary = {}
    if model_name and getattr(trainer, "_registry", None) is not None:
        try:
            model_summary = trainer._registry.get_model_summary(model_name)
        except Exception:
            logger.debug("Model summary unavailable during status call", exc_info=True)
    if not model_summary:
        model_summary = {"active_stage": settings.ml_model_stage}
    last_training_ts = float(getattr(trainer, "_last_train_time", 0.0) or 0.0)
    incremental_info = trainer._get_incremental_info() if hasattr(trainer, "_get_incremental_info") else {}
    incremental_metadata = incremental_info.get("metadata", {}) if isinstance(incremental_info, dict) else {}

    last_trained_at = _isoformat_timestamp(last_training_ts)
    if not last_trained_at and incremental_metadata.get("last_accepted_at"):
        last_trained_at = incremental_metadata.get("last_accepted_at")
    if not last_trained_at and artifact_exists:
        last_trained_at = datetime.fromtimestamp(os.path.getmtime(artifact_path), tz=timezone.utc).isoformat()

    status = "not_trained"
    if model_loaded:
        status = "trained"
    elif artifact_exists:
        status = "artifact_present"
    elif sample_count < min_samples:
        status = "collecting_data"
    else:
        status = "ready_for_training"

    # Get accuracy from recent training history (validation accuracy from last training)
    accuracy = None
    top_10_accuracy = None
    accepted_validation_samples = None
    last_accepted_training_info = incremental_metadata.get("last_accepted_training_info", {})
    training_history = trainer.get_training_history()
    accepted_history = [item for item in training_history if item.get("accepted", True)]
    if accepted_history:
        latest_training = accepted_history[-1]
        accuracy = _extract_accuracy_from_history_item(latest_training)
        top_10_accuracy = _extract_top10_from_history_item(latest_training)
        accepted_validation_samples = latest_training.get("val_samples")
        logger.info(f"Latest accepted training accuracy from history: {accuracy}")

    if accuracy is None:
        accuracy = _extract_accuracy_from_history_item({
            "metrics": incremental_metadata.get("last_accepted_metrics", {})
        })
    if top_10_accuracy is None:
        top_10_accuracy = _extract_top10_from_history_item({
            "metrics": incremental_metadata.get("last_accepted_metrics", {})
        })
    if accepted_validation_samples is None:
        accepted_validation_samples = (last_accepted_training_info.get("val_samples"))

    registry_active_version = None
    registry_active_metrics: Dict[str, Any] = {}
    registry_active_provenance: Dict[str, Any] = {}
    if model_name:
        try:
            registry = get_model_registry()
            registry_active_version = registry.get_active_version(model_name)
            if registry_active_version is not None:
                registry_active_metrics = dict(registry_active_version.metrics or {})
                registry_active_provenance = dict(registry_active_version.provenance or {})
        except Exception:
            logger.debug("Registry active version unavailable during status call", exc_info=True)

    if accuracy is None and registry_active_metrics:
        for key in ("val_accuracy", "accuracy", "top_1_accuracy", "test_accuracy", "train_accuracy"):
            value = registry_active_metrics.get(key)
            if value is None:
                continue
            try:
                accuracy = float(value)
                break
            except (TypeError, ValueError):
                continue
    if top_10_accuracy is None and registry_active_metrics:
        for key in ("top_10_accuracy", "val_top_10_accuracy", "test_top_10_accuracy"):
            value = registry_active_metrics.get(key)
            if value is None:
                continue
            try:
                top_10_accuracy = float(value)
                break
            except (TypeError, ValueError):
                continue
    if accepted_validation_samples is None and registry_active_provenance:
        splits = registry_active_provenance.get("splits", {})
        feature_shape = registry_active_provenance.get("feature_shape", {})
        accepted_validation_samples = (
            splits.get("validation")
            or (feature_shape.get("validation", [None])[0] if isinstance(feature_shape.get("validation"), list) else None)
        )
    
    # If still None, try to get from model stats (e.g., if we have evaluation metrics stored there)
    if accuracy is None:
        # Try to get from model stats per-model accuracy (this is from weight tracker, not ideal)
        per_model_acc = model_stats.get("per_model_accuracy", {})
        accuracies = [v for v in per_model_acc.values() if v is not None]
        if accuracies:
            accuracy = max(accuracies)
            logger.info(f"Accuracy from model stats: {accuracy}")
    
    # If still None, use 0.0 (model not trained yet)
    if accuracy is None:
        accuracy = 0.0
        logger.info("Accuracy is None, setting to 0.0")
    best_accuracy = incremental_metadata.get("best_accuracy")
    try:
        best_accuracy = float(best_accuracy) if best_accuracy is not None else float(accuracy)
    except (TypeError, ValueError):
        best_accuracy = float(accuracy)

    last_training_attempt = incremental_metadata.get("last_training_attempt", {})
    last_attempt_training_info = last_training_attempt.get("training_info", {}) if last_training_attempt else {}
    last_attempt_accuracy = _extract_attempt_accuracy(last_training_attempt)
    last_attempt_top_10_accuracy = _extract_attempt_top10(last_training_attempt)
    last_attempt_accepted = last_training_attempt.get("accepted")
    status_detail = "active_model"
    if last_attempt_accepted is False:
        status_detail = "active_model_retained_after_rejected_attempt"
    elif last_attempt_accepted is True:
        status_detail = "active_model_updated"

    accuracy_confidence = _accuracy_confidence(accepted_validation_samples)
    accuracy_warning = _accuracy_warning(accepted_validation_samples)

    # Determine learning status - show Learning if actively training, collecting data, not trained, or ready for training
    # Show Trained/Mature when model is actually trained and ready
    is_learning = (
        status in ["collecting_data", "ready_for_training", "not_trained"] or 
        bool(getattr(trainer, "_is_training_scheduled", False) or getattr(trainer, "_is_training_automatic", False))
    )

    # This payload now matches the frontend component's expectations
    return {
        "model_name": model_name,
        "model_version": registry_active_version.version if registry_active_version is not None else getattr(trainer, "_active_model_version", None),
        "model_stage": (
            registry_active_version.stage
            if registry_active_version is not None
            else model_summary.get("active_stage", "production")
        ),
        "model_accuracy": float(accuracy),
        "model_top_10_accuracy": float(top_10_accuracy) if top_10_accuracy is not None else None,
        "best_accuracy": best_accuracy,
        "is_learning": is_learning,
        "model_loaded": model_loaded,
        "last_trained_at": last_trained_at,
        "status_code": status,
        "status_detail": status_detail,
        "sample_count": sample_count,
        "accepted_sample_count": last_accepted_training_info.get("sample_count"),
        "accepted_train_samples": last_accepted_training_info.get("train_samples"),
        "accepted_validation_samples": accepted_validation_samples,
        "accuracy_confidence": accuracy_confidence,
        "accuracy_warning": accuracy_warning,
        "last_training_attempt": last_training_attempt,
        "last_attempt_accuracy": last_attempt_accuracy,
        "last_attempt_top_10_accuracy": last_attempt_top_10_accuracy,
        "last_attempt_accepted": last_attempt_accepted,
        "last_attempt_sample_count": last_attempt_training_info.get("sample_count"),
        "last_attempt_train_samples": last_attempt_training_info.get("train_samples"),
        "last_attempt_validation_samples": last_attempt_training_info.get("val_samples"),
        "last_attempt_accuracy_confidence": _accuracy_confidence(last_attempt_training_info.get("val_samples")),
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


def get_model_evaluation_payload() -> Dict[str, Any]:
    trainer = get_model_trainer()
    evaluation = trainer.evaluate()
    evaluation["active_version"] = trainer.get_stats().get("active_version")
    evaluation["artifact_path"] = trainer.get_stats().get("artifact_path")
    return evaluation


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
    model_accepted = bool(result.get("model_accepted", success))
    decision_reason = result.get("decision_reason")

    if success:
        evaluation = trainer.evaluate()
        if model_accepted:
            message = "Runtime retraining completed and active model updated"
        else:
            message = "Runtime retraining completed, but active model version was retained"
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
        "model_accepted": model_accepted,
        "version_bumped": bool(result.get("version_bumped", model_accepted)),
        "decision_reason": decision_reason,
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
    predictor_override: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    runtime = _bind_runtime_components()
    predictor = predictor_override or runtime["predictor"]
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
    predictor_override: Optional[Any] = None,
) -> Dict[str, Any]:
    candidates = _build_prefetch_candidates(
        secure_manager,
        service_id,
        source_key_id,
        predictor_override=predictor_override,
    )

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

    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop and running_loop.is_running():
        running_loop.create_task(
            run_request_path_prefetch(
                secure_manager=secure_manager,
                service_id=service_id,
                source_key_id=source_key_id,
                candidates=candidates,
                ip_address=ip_address,
            )
        )
        return {
            "mode": "direct_async_task",
            "prefetched_count": 0,
            "predictions_considered": len(candidates),
        }

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
        accuracy = _extract_accuracy_from_history_item(item)
        if accuracy is None:
            continue

        completed_at = item.get("completed_at") or item.get("timestamp")
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
                "accepted": bool(item.get("accepted", item.get("model_accepted", True))),
                "top_10_accuracy": round(float(_extract_top10_from_history_item(item) or 0.0) * 100, 1),
            }
        )

    return {"data": data}


def generate_training_data(
    num_events: int = 1000,
    num_keys: int = 100,
    num_services: int = 5,
    scenario: str = "dynamic",
    pattern_type: str = "realistic",
    traffic_profile: str = "normal",
    duration_hours: int = 24,
    include_drift: bool = True,
) -> Dict[str, Any]:
    """
    Generate synthetic training data based on scenario, pattern_type, and traffic profile.
    This simulates organic traffic patterns for ML training.
    """
    import random
    from datetime import datetime, timedelta
    
    collector = get_data_collector()
    
    # Progress tracker was already reset and initialised in the endpoint
    from src.api.training_progress import get_data_generation_tracker
    gen_tracker = get_data_generation_tracker()

    events = []
    now = datetime.now(timezone.utc)
    
    MAX_TRAINING_WINDOW_SECONDS = 1_209_600  # 14 days
    requested_window = duration_hours * 3600
    if requested_window > MAX_TRAINING_WINDOW_SECONDS:
        logger.warning(
            "duration_hours exceeds max training window.",
        )
        window_seconds = MAX_TRAINING_WINDOW_SECONDS
    else:
        window_seconds = requested_window
    base_time = now - timedelta(seconds=window_seconds)

    _progress_step = max(1, num_events // 20)  # report every 5%

    if pattern_type == "realistic":
        # Realistic Generation (Markov Chains / User Flows)
        if scenario == "siakad":
            flows = [
                [("auth", "login"), ("akademik", "dashboard"), ("akademik", "krs/view"), ("akademik", "khs/nilai"), ("auth", "logout")],
                [("auth", "login"), ("akademik", "dashboard"), ("akademik", "krs/view"), ("auth", "logout")],
                [("auth", "login"), ("dosen", "dashboard"), ("akademik", "kelas/list"), ("akademik", "kelas/input_nilai"), ("auth", "logout")],
                [("auth", "login"), ("keuangan", "dashboard"), ("keuangan", "tagihan/view"), ("auth", "logout")]
            ]
        elif scenario == "sevima":
            flows = [
                [("auth", "login"), ("elearning", "course/list"), ("elearning", "course/material")],
                [("auth", "login"), ("elearning", "course/list"), ("elearning", "quiz/start"), ("elearning", "quiz/submit"), ("auth", "logout")],
            ]
        elif scenario == "pddikti":
            flows = [
                [("pddikti", "sync/start"), ("pt", "pt/update"), ("mahasiswa", "mhs/update_batch"), ("pddikti", "sync/finish")]
            ]
        else:
            flows = [
                [("auth", "login"), ("default", "dashboard"), ("default", "item/view"), ("payment", "checkout")]
            ]

        i = 0
        while i < num_events:
            flow = random.choice(flows)
            # Pick a unique user identifier to scale unique keys
            user_id = random.randint(1, max(1, num_keys)) 
            # Spread session in time
            time_offset = random.uniform(0, window_seconds)
            session_base_time = base_time + timedelta(seconds=time_offset)
            
            for step_idx, (svc, key_base) in enumerate(flow):
                if i >= num_events:
                    break
                # Each step takes 0.5 to 5 seconds
                session_base_time += timedelta(seconds=random.uniform(0.5, 5.0))
                # High cache hit probability for steps deeper in the flow to simulate caching
                cache_hit = step_idx > 0 or random.random() < 0.3
                latency_ms = random.uniform(1, 10) if cache_hit else random.uniform(50, 200)
                
                events.append({
                    "key_id": f"{key_base}-user_{user_id}",
                    "service_id": svc,
                    "timestamp": session_base_time.timestamp(),
                    "latency_ms": latency_ms,
                    "cache_hit": cache_hit,
                    "scenario": scenario,
                    "traffic_profile": traffic_profile,
                    "pattern_type": pattern_type,
                    "generated_kind": "realistic_flow",
                    "realism_score_hint": 0.95,
                })
                i += 1
                
                if i % _progress_step == 0 or i == num_events:
                    gen_tracker.update(min(i, num_events - 1))
                    
    else:
        # Standard Randomized Testing Generation (Stress Test)
        scenario_patterns = {
            "siakad": {"services": ["siakad", "akademik", "keuangan"], "keys": ["mahasiswa-", "dosen-", "nilai-"]},
            "sevima": {"services": ["sevima", "elearning", "conference"], "keys": ["user-", "meeting-", "course-"]},
            "pddikti": {"services": ["pddikti", "pt", "mahasiswa"], "keys": ["pt-", "mhs-", "prodi-"]},
            "dynamic": {"services": ["default", "auth-service", "payment-service"], "keys": ["api-key-", "token-", "secret-"]},
        }
        config = scenario_patterns.get(scenario, scenario_patterns["dynamic"])
        services = config["services"]
        key_patterns = config["keys"]
        
        traffic_configs = {
            "normal": {"hot_key_ratio": 0.2, "burst_probability": 0.05, "sequential_probability": 0.3},
            "heavy": {"hot_key_ratio": 0.3, "burst_probability": 0.15, "sequential_probability": 0.4},
            "prime_time": {"hot_key_ratio": 0.25, "burst_probability": 0.1, "sequential_probability": 0.35},
            "overload": {"hot_key_ratio": 0.4, "burst_probability": 0.25, "sequential_probability": 0.5},
        }
        traffic_config = traffic_configs.get(traffic_profile, traffic_configs["normal"])
        
        hot_keys = [f"{random.choice(key_patterns)}{random.randint(1, max(1, num_keys // 5))}" for _ in range(max(1, int(num_keys * traffic_config["hot_key_ratio"])))]
        last_key = None

        for i in range(num_events):
            time_offset = random.uniform(0, window_seconds)
            timestamp = (base_time + timedelta(seconds=time_offset)).timestamp()
            
            if last_key and random.random() < traffic_config["sequential_probability"]:
                key_base = last_key.split("-")[0] if "-" in last_key else last_key
                key_id = f"{key_base}-{random.randint(1, max(1, num_keys))}"
            elif random.random() < traffic_config["hot_key_ratio"]:
                key_id = random.choice(hot_keys)
            else:
                key_id = f"{random.choice(key_patterns)}{random.randint(1, max(1, num_keys))}"
            
            service_id = random.choice(services)
            is_hot = key_id in hot_keys
            cache_hit = is_hot or random.random() < 0.7
            latency_ms = random.uniform(1, 10) if cache_hit else random.uniform(50, 200)
            
            if random.random() < traffic_config["burst_probability"]:
                burst_count = random.randint(3, 10)
                for _ in range(burst_count):
                    time_offset += random.uniform(0.1, 2)
                    events.append({
                        "key_id": random.choice(hot_keys),
                        "service_id": service_id,
                        "timestamp": (base_time + timedelta(seconds=time_offset)).timestamp(),
                        "latency_ms": random.uniform(1, 10),
                        "cache_hit": True,
                        "scenario": scenario,
                        "traffic_profile": traffic_profile,
                        "pattern_type": pattern_type,
                        "generated_kind": "random_burst_hot_key",
                        "realism_score_hint": 0.35,
                    })
            
            events.append({
                "key_id": key_id,
                "service_id": service_id,
                "timestamp": timestamp,
                "latency_ms": latency_ms,
                "cache_hit": cache_hit,
                "scenario": scenario,
                "traffic_profile": traffic_profile,
                "pattern_type": pattern_type,
                "generated_kind": "random_stress",
                "realism_score_hint": 0.2 if not is_hot else 0.4,
            })
            
            last_key = key_id
            if (i + 1) % _progress_step == 0 or (i + 1) == num_events:
                gen_tracker.update(min(i + 1, num_events - 1))

    # Sort by timestamp
    events.sort(key=lambda x: x["timestamp"])
    
    # Import events into collector with data_source marked as "simulation"
    # (bulk import mode skips periodic Redis saves for O(n) performance)
    imported = collector.import_events(events, data_source="simulation")
    
    # CRITICAL: Flush all events to Redis immediately so ML Worker can detect them
    collector.flush_to_redis()

    # NOW signal completion — import is done and data is in Redis.
    gen_tracker.update(num_events)
    
    stats = collector.get_stats()
    
    return {
        "success": True,
        "scenario": scenario,
        "traffic_profile": traffic_profile,
        "events_generated": len(events),
        "events_imported": imported,
        "num_keys": num_keys,
        "num_services": num_services,
        "duration_hours": duration_hours,
        "include_drift": include_drift,
        "collector_stats": stats,
    }


def train_model(
    force: bool = True,
    reason: str = "manual",
    quality_profile: Optional[str] = None,
    time_budget_minutes: Optional[int] = None,
    sample_strategy: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Train the model using collected data.
    Returns training results with model version.
    """
    trainer = get_model_trainer()
    predictor = get_key_predictor()
    
    # Get current stats before training
    stats_before = trainer.get_stats()
    sample_count = stats_before.get("collector_stats", {}).get("total_events", 0)
    
    if sample_count < stats_before.get("min_samples", 100):
        return {
            "success": False,
            "reason": "insufficient_samples",
            "sample_count": sample_count,
            "required": stats_before.get("min_samples", 100),
            "message": f"Need at least {stats_before.get('min_samples', 100)} samples to train. Currently have {sample_count}."
        }
    
    # Run training
    result = trainer.train(
        force=force,
        reason=reason,
        quality_profile=quality_profile,
        time_budget_minutes=time_budget_minutes,
        sample_strategy=sample_strategy,
    )
    
    if result.get("success"):
        # Update predictor with new model
        predictor.attach_model(
            trainer.model,
            source=trainer.get_active_model_metadata().get("source", "runtime"),
            version=trainer.get_active_model_metadata().get("version"),
            artifact_path=trainer.get_active_model_metadata().get("artifact_path"),
        )
        predictor.clear_cache()
        
        # Get updated stats
        stats_after = trainer.get_stats()
        model_accepted = bool(result.get("model_accepted", True))
        
        return {
            "success": True,
            "message": "Training completed successfully" if model_accepted else "Training evaluated successfully, active model version retained",
            "model_version": result.get("version") or result.get("registry_version"),
            "sample_count": result.get("sample_count"),
            "val_accuracy": result.get("val_accuracy"),
            "val_top_10_accuracy": result.get("val_top_10_accuracy"),
            "training_time_s": result.get("training_time_s"),
            "completed_at": result.get("completed_at"),
            "active_version": stats_after.get("active_version"),
            "model_source": stats_after.get("model_source"),
            "model_accepted": model_accepted,
            "version_bumped": bool(result.get("version_bumped", model_accepted)),
            "decision_reason": result.get("decision_reason"),
            "quality_profile": result.get("quality_profile"),
            "sample_strategy": result.get("sample_strategy"),
            "time_budget_minutes": result.get("time_budget_minutes"),
            "estimated_training_minutes": result.get("estimated_training_minutes"),
            "hyperparameters": result.get("hyperparameters"),
            "sample_selection": result.get("sample_selection"),
        }
    else:
        return {
            "success": False,
            "reason": result.get("reason", "unknown"),
            "message": f"Training failed: {result.get('reason', 'Unknown error')}",
        }


def get_training_plan(
    quality_profile: Optional[str] = None,
    time_budget_minutes: Optional[int] = None,
    sample_strategy: Optional[str] = None,
) -> Dict[str, Any]:
    trainer = get_model_trainer()
    plan = trainer.get_training_plan(
        quality_profile=quality_profile,
        time_budget_minutes=time_budget_minutes,
        sample_strategy=sample_strategy,
    )
    plan["model_name"] = trainer.model_name
    return plan
