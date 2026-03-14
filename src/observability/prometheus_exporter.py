from collections import Counter
from typing import Any, Dict

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, Histogram, generate_latest

from src.api.ml_service import (
    get_ml_status_payload,
    get_model_lifecycle_payload,
    get_model_registry_payload,
    get_prefetch_metrics_payload,
)


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _set_gauge(registry: CollectorRegistry, name: str, documentation: str, value: Any) -> None:
    Gauge(name, documentation, registry=registry).set(_coerce_float(value))


def build_prometheus_metrics_payload(
    metrics_storage: Dict[str, Any],
    secure_manager: Any,
) -> bytes:
    registry = CollectorRegistry()

    total_requests = _coerce_int(metrics_storage.get("total_requests"))
    cache_hits = _coerce_int(metrics_storage.get("cache_hits"))
    cache_misses = _coerce_int(metrics_storage.get("cache_misses"))
    latencies = metrics_storage.get("latencies") or []
    avg_latency_ms = (sum(latencies) / len(latencies)) if latencies else 0.0

    cache_stats = secure_manager.get_cache_stats()
    shared_cache_stats = cache_stats.get("shared_cache", {})
    ml_status = get_ml_status_payload()
    model_name = ml_status.get("model_name")
    registry_payload = get_model_registry_payload(model_name=model_name)
    lifecycle_payload = get_model_lifecycle_payload(limit=10_000, model_name=model_name)
    registry_summary = registry_payload.get("summary", {})
    registry_stats = registry_payload.get("stats", {})
    lifecycle_stats = lifecycle_payload.get("stats", {})
    prefetch_metrics = get_prefetch_metrics_payload()

    _set_gauge(registry, "pskc_requests_total", "Total request count observed by the API runtime.", total_requests)
    _set_gauge(registry, "pskc_cache_hits_total", "Total cache hits observed by the API runtime.", cache_hits)
    _set_gauge(registry, "pskc_cache_misses_total", "Total cache misses observed by the API runtime.", cache_misses)
    _set_gauge(
        registry,
        "pskc_cache_hit_rate_ratio",
        "Cache hit rate in the current process.",
        (cache_hits / total_requests) if total_requests else 0.0,
    )
    _set_gauge(registry, "pskc_avg_latency_ms", "Average request latency in milliseconds.", avg_latency_ms)
    _set_gauge(
        registry,
        "pskc_active_keys",
        "Number of active keys visible through the secure cache manager.",
        len(secure_manager.get_cache_keys()),
    )
    _set_gauge(
        registry,
        "pskc_cache_local_size",
        "Local in-process cache size.",
        cache_stats.get("cache", {}).get("size", 0),
    )
    _set_gauge(
        registry,
        "pskc_cache_shared_size",
        "Shared Redis cache size.",
        shared_cache_stats.get("size", 0),
    )
    _set_gauge(
        registry,
        "pskc_cache_shared_available",
        "Shared Redis cache availability as 1 or 0.",
        1 if shared_cache_stats.get("available") else 0,
    )

    _set_gauge(
        registry,
        "pskc_ml_model_loaded",
        "Whether the runtime ML model is loaded.",
        1 if ml_status.get("model_loaded") else 0,
    )
    _set_gauge(
        registry,
        "pskc_ml_samples_total",
        "Number of collected runtime access samples for ML training.",
        ml_status.get("sample_count", 0),
    )
    _set_gauge(
        registry,
        "pskc_ml_required_samples",
        "Minimum required samples before runtime training.",
        ml_status.get("required_samples", 0),
    )
    _set_gauge(
        registry,
        "pskc_ml_auto_training_enabled",
        "Whether ML auto-training is enabled.",
        1 if ml_status.get("auto_training") else 0,
    )
    _set_gauge(
        registry,
        "pskc_ml_prediction_cache_size",
        "Current predictor cache size.",
        ml_status.get("prediction_cache_size", 0),
    )
    _set_gauge(
        registry,
        "pskc_ml_registry_versions_total",
        "Number of registered versions for the active logical model.",
        len(registry_summary.get("versions", [])),
    )
    _set_gauge(
        registry,
        "pskc_ml_registry_signed_versions",
        "Number of signed model versions across the registry.",
        registry_stats.get("signed_versions", 0),
    )
    _set_gauge(
        registry,
        "pskc_ml_registry_unsigned_versions",
        "Number of unsigned model versions across the registry.",
        registry_stats.get("unsigned_versions", 0),
    )
    _set_gauge(
        registry,
        "pskc_ml_lifecycle_events_total",
        "Number of persisted lifecycle events for the active logical model.",
        lifecycle_stats.get("events_total", 0),
    )

    model_status_gauge = Gauge(
        "pskc_ml_model_status",
        "Current ML model status as a labeled gauge.",
        labelnames=("status",),
        registry=registry,
    )
    model_status_gauge.labels(status=str(ml_status.get("status", "unknown"))).set(1)

    active_stage = str(ml_status.get("active_stage") or registry_summary.get("active_stage") or "unknown")
    stage_gauge = Gauge(
        "pskc_ml_active_stage",
        "Current active registry stage as a labeled gauge.",
        labelnames=("stage",),
        registry=registry,
    )
    stage_gauge.labels(stage=active_stage).set(1)

    lifecycle_events_gauge = Gauge(
        "pskc_ml_lifecycle_events_by_type",
        "Persisted lifecycle event counts for the active logical model.",
        labelnames=("event",),
        registry=registry,
    )
    for event_name, metric_value in (lifecycle_stats.get("events_by_type") or {}).items():
        lifecycle_events_gauge.labels(event=event_name).set(_coerce_float(metric_value))

    stage_versions_gauge = Gauge(
        "pskc_ml_registry_versions_by_stage",
        "Registered model versions grouped by registry stage.",
        labelnames=("stage",),
        registry=registry,
    )
    for stage_name, count in Counter(
        str(version.get("stage") or "unknown") for version in registry_summary.get("versions", [])
    ).items():
        stage_versions_gauge.labels(stage=stage_name).set(_coerce_float(count))

    _set_gauge(
        registry,
        "pskc_prefetch_queue_available",
        "Whether the Redis prefetch queue is reachable.",
        1 if prefetch_metrics.get("available") else 0,
    )
    _set_gauge(
        registry,
        "pskc_prefetch_queue_length",
        "Current length of the main prefetch queue.",
        prefetch_metrics.get("queue_length", 0),
    )
    _set_gauge(
        registry,
        "pskc_prefetch_retry_length",
        "Current length of the prefetch retry backlog.",
        prefetch_metrics.get("retry_length", 0),
    )
    _set_gauge(
        registry,
        "pskc_prefetch_dlq_length",
        "Current length of the prefetch dead-letter queue.",
        prefetch_metrics.get("dlq_length", 0),
    )

    prefetch_stats_gauge = Gauge(
        "pskc_prefetch_jobs_total",
        "Prefetch queue lifecycle counters exported from Redis stats.",
        labelnames=("status",),
        registry=registry,
    )
    for status_name, metric_value in (prefetch_metrics.get("stats") or {}).items():
        prefetch_stats_gauge.labels(status=status_name).set(_coerce_float(metric_value))
    
    # ============================================================
    # Worker Activity Metrics
    # ============================================================
    
    _set_gauge(
        registry,
        "pskc_worker_up",
        "Whether the prefetch worker process is running.",
        1,  # This would be set by worker process
    )
    
    _set_gauge(
        registry,
        "pskc_worker_last_heartbeat_seconds",
        "Seconds since last worker heartbeat.",
        0,  # This would be set by worker process
    )
    
    # ============================================================
    # Audit Logger Availability
    # ============================================================
    
    _set_gauge(
        registry,
        "pskc_audit_logger_available",
        "Whether the audit logger is available (1 or 0).",
        1,  # Would be checked from runtime
    )
    
    return generate_latest(registry)


def get_prometheus_content_type() -> str:
    return CONTENT_TYPE_LATEST
