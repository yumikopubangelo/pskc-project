import asyncio
import random
import time
import uuid
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Dict, List, Optional, Tuple

from config.settings import settings
from src.cache.cache_policy import CachePolicyManager
from src.cache.encrypted_store import EncryptedCacheStore
from src.cache.local_cache import LocalCache
from src.api.live_validation_service import (
    TRAFFIC_PROFILES,
    _build_seed_events,
    _component_snapshot,
    _generate_sequence,
    _safe_rate,
)
from src.api.ml_service import get_ml_status_payload, record_runtime_access, schedule_request_path_prefetch
from src.auth.key_fetcher import get_key_fetcher
from src.ml.data_collector import get_data_collector
from src.ml.model_registry import SecurityError, get_model_registry
from src.ml.predictor import KeyPredictor
from src.ml.trainer import get_model_trainer
from src.prefetch.queue import get_prefetch_queue
from src.security.intrusion_detection import SecureCacheManager


_SESSION_LOCK = RLock()
_LIVE_SESSIONS: Dict[str, Dict[str, Any]] = {}
_TRACE_LIMIT = 80
_KEY_BREAKDOWN_LIMIT = 15
_DEFAULT_VIRTUAL_NODES = 3
_KMS_LATENCY_BOUNDS_MS: Dict[str, Tuple[float, float]] = {
    "normal": (28.0, 48.0),
    "heavy_load": (40.0, 85.0),
    "prime_time": (35.0, 70.0),
    "degraded": (75.0, 140.0),
    "overload": (95.0, 180.0),
}
_REQUEST_OVERHEAD_BOUNDS_MS: Dict[str, Tuple[float, float]] = {
    "normal": (4.0, 8.0),
    "heavy_load": (5.0, 10.0),
    "prime_time": (5.0, 10.0),
    "degraded": (8.0, 16.0),
    "overload": (10.0, 24.0),
}
_KMS_PRESSURE_WINDOW_SECONDS = 2.0
_KMS_NOMINAL_CAPACITY_RPS = 90.0
_KMS_HARD_CEILING_MS = 1800.0
_KEY_MODE_DEFAULT_BY_TRAFFIC = {
    "normal": "stable",
    "heavy_load": "mixed",
    "prime_time": "mixed",
    "degraded": "high_churn",
    "overload": "high_churn",
}
_KEY_MODE_PROFILES: Dict[str, Dict[str, float]] = {
    "stable": {"rotation_rate": 0.0, "ephemeral_rate": 0.0, "rotation_window": 9999, "variant_pool": 1},
    "mixed": {"rotation_rate": 0.22, "ephemeral_rate": 0.06, "rotation_window": 18, "variant_pool": 8},
    "high_churn": {"rotation_rate": 0.55, "ephemeral_rate": 0.18, "rotation_window": 6, "variant_pool": 18},
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _p95(values: List[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))
    return round(float(ordered[index]), 2)


def _stage_rank(stage: Optional[str]) -> int:
    normalized = str(stage or "").lower()
    if normalized == "production":
        return 3
    if normalized == "staging":
        return 2
    if normalized == "development":
        return 1
    return 0


def _version_metric_tuple(version_entry: Dict[str, Any]) -> Tuple[float, float, int, float]:
    metrics = version_entry.get("metrics", {}) or {}
    top10 = _float_or_zero(metrics.get("top_10_accuracy", metrics.get("val_top_10_accuracy")))
    top1 = _float_or_zero(
        metrics.get("accuracy", metrics.get("val_accuracy", metrics.get("top_1_accuracy")))
    )
    created_at = _float_or_zero(version_entry.get("created_at"))
    return (top10, top1, _stage_rank(version_entry.get("stage")), created_at)


def _metric_basis(top10: float, top1: float) -> Tuple[str, float]:
    if top10 > 0.0:
        return "top_10_accuracy", top10
    return "top_1_accuracy", top1


def _normalize_key_mode(key_mode: str, traffic_type: str) -> str:
    normalized = str(key_mode or "auto").lower()
    if normalized in _KEY_MODE_PROFILES:
        return normalized
    return _KEY_MODE_DEFAULT_BY_TRAFFIC.get(traffic_type, "mixed")


def _prune_time_window(window: deque[float], *, now: Optional[float] = None) -> None:
    current_time = time.time() if now is None else now
    cutoff = current_time - _KMS_PRESSURE_WINDOW_SECONDS
    while window and window[0] < cutoff:
        window.popleft()


def _record_kms_latency(state: Dict[str, Any], lane: str, latency_ms: float, *, timestamp: Optional[float] = None) -> None:
    current_time = time.time() if timestamp is None else timestamp
    window = state["kms_windows"].setdefault(lane, deque())
    window.append(current_time)
    _prune_time_window(window, now=current_time)

    latency_samples = state["kms_latency_samples"].setdefault(lane, [])
    latency_samples.append(round(float(latency_ms), 2))
    if len(latency_samples) > 500:
        del latency_samples[:-500]


def _session_learning_predictions(
    state: Dict[str, Any],
    *,
    service_id: str,
    current_key: str,
    n: int,
) -> List[Tuple[str, float]]:
    transitions = state["adaptive_transitions"].get(service_id, {})
    popularity = state["adaptive_popularity"].get(service_id, Counter())

    predictions: List[Tuple[str, float]] = []
    transition_counts = transitions.get(current_key)
    if transition_counts:
        total = sum(transition_counts.values()) or 1
        for next_key, count in transition_counts.most_common(n):
            confidence = min(0.99, 0.55 + (count / total) * 0.4)
            predictions.append((next_key, round(confidence, 4)))

    for next_key, count in popularity.most_common(n * 2):
        if next_key == current_key or any(existing_key == next_key for existing_key, _ in predictions):
            continue
        confidence = min(0.65, 0.25 + min(count / 25.0, 0.35))
        predictions.append((next_key, round(confidence, 4)))
        if len(predictions) >= n:
            break

    return predictions[:n]


def _merge_prediction_sources(
    model_predictions: List[Tuple[str, float]],
    adaptive_predictions: List[Tuple[str, float]],
    *,
    n: int,
) -> List[Tuple[str, float]]:
    merged: Dict[str, float] = {}

    for rank, (key_id, confidence) in enumerate(model_predictions[: n * 2], start=1):
        score = float(confidence) * (1.0 - min(0.35, rank * 0.03))
        merged[key_id] = max(merged.get(key_id, 0.0), score)

    for rank, (key_id, confidence) in enumerate(adaptive_predictions[: n * 2], start=1):
        score = float(confidence) * (1.08 - min(0.22, rank * 0.02))
        merged[key_id] = max(merged.get(key_id, 0.0), score)

    ranked = sorted(merged.items(), key=lambda item: item[1], reverse=True)
    return [(key_id, round(score, 4)) for key_id, score in ranked[:n]]


class _SessionOverlayPredictor:
    def __init__(self, predictions: List[Tuple[str, float]]):
        self._predictions = predictions
        self.model = object()

    def predict(
        self,
        service_id: str = "default",
        n: int = 10,
        min_confidence: Optional[float] = None,
    ) -> List[Tuple[str, float]]:
        threshold = 0.0 if min_confidence is None else float(min_confidence)
        return [
            (key_id, confidence)
            for key_id, confidence in self._predictions[:n]
            if confidence >= threshold
        ]


def _resolve_request_overhead_ms(session: Dict[str, Any], *, lane: str) -> float:
    bounds = _REQUEST_OVERHEAD_BOUNDS_MS.get(session["traffic_type"], _REQUEST_OVERHEAD_BOUNDS_MS["normal"])
    rng = session["_state"]["kms_rng"]
    overhead = rng.uniform(*bounds)
    if lane == "direct":
        overhead *= 1.25
    if session["traffic_type"] == "overload":
        overhead *= 1.2
    return round(overhead, 2)


def _resolve_kms_latency_target_ms(session: Dict[str, Any], *, lane: str = "pskc") -> float:
    bounds = _KMS_LATENCY_BOUNDS_MS.get(session["traffic_type"], _KMS_LATENCY_BOUNDS_MS["normal"])
    rng = session["_state"]["kms_rng"]
    current_time = time.time()
    pressure_windows = session["_state"]["kms_windows"]
    lane_window = pressure_windows.setdefault(lane, deque())
    _prune_time_window(lane_window, now=current_time)

    configured_rps = float(TRAFFIC_PROFILES.get(session["traffic_type"], TRAFFIC_PROFILES["normal"])["rps"])
    recent_lane_rps = len(lane_window) / _KMS_PRESSURE_WINDOW_SECONDS
    virtual_nodes = max(1, int(session.get("virtual_nodes", 1)))

    utilization = configured_rps / _KMS_NOMINAL_CAPACITY_RPS
    queue_pressure = recent_lane_rps / _KMS_NOMINAL_CAPACITY_RPS
    base_latency = rng.uniform(*bounds)

    load_multiplier = (
        1.0
        + max(0.0, utilization - 0.55) * 0.9
        + queue_pressure * 0.7
        + max(0, virtual_nodes - 1) * 0.05
    )
    if lane == "direct":
        load_multiplier += 0.18

    spike_chance = 0.03 + max(0.0, utilization - 0.6) * 0.22 + queue_pressure * 0.12
    if session["traffic_type"] in {"degraded", "overload"}:
        spike_chance += 0.08
    if lane == "direct":
        spike_chance += 0.04

    latency_ms = base_latency * load_multiplier
    if rng.random() < min(0.6, spike_chance):
        latency_ms *= rng.uniform(1.4, 3.4 if session["traffic_type"] == "overload" else 2.3)

    latency_ms += rng.uniform(0.0, 14.0 if session["traffic_type"] == "overload" else 6.0)
    return round(min(_KMS_HARD_CEILING_MS, latency_ms), 2)


async def _fetch_key_with_kms_latency(
    fetcher: Any,
    *,
    key_id: str,
    service_id: str,
    target_latency_ms: float,
) -> Tuple[Optional[bytes], float]:
    started_at = time.perf_counter()
    key_data = await fetcher.fetch_key(key_id, service_id)
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    if elapsed_ms < target_latency_ms:
        await asyncio.sleep((target_latency_ms - elapsed_ms) / 1000.0)
        elapsed_ms = target_latency_ms
    return key_data, round(elapsed_ms, 2)


def _build_virtual_nodes(app_state: Any, virtual_nodes: int) -> List[Dict[str, Any]]:
    runtime_services = app_state.runtime_services
    shared_cache = runtime_services.get("redis_cache")
    fips_module = runtime_services["fips_module"]
    audit_logger = runtime_services["audit_logger"]
    effective_nodes = max(1, int(virtual_nodes or _DEFAULT_VIRTUAL_NODES))
    local_cache_size = max(64, min(int(settings.cache_max_size), 256))
    nodes: List[Dict[str, Any]] = []

    for index in range(effective_nodes):
        local_cache = LocalCache(
            max_size=local_cache_size,
            default_ttl=settings.cache_ttl_seconds,
        )
        encrypted_store = EncryptedCacheStore(
            cache=local_cache,
            policy_manager=CachePolicyManager(),
            fips_module=fips_module,
            audit_logger=audit_logger,
            shared_cache=shared_cache,
        )
        nodes.append(
            {
                "node_id": f"api-node-{index + 1}",
                "local_cache": local_cache,
                "secure_manager": SecureCacheManager(
                    encrypted_store=encrypted_store,
                    audit_logger=audit_logger,
                ),
            }
        )

    return nodes


def _shutdown_virtual_nodes(nodes: List[Dict[str, Any]]) -> None:
    for node in nodes:
        local_cache = node.get("local_cache")
        if local_cache is not None:
            local_cache.shutdown()


def _generate_live_buffer(
    *,
    session: Dict[str, Any],
    rng: random.Random,
    request_count: int,
) -> List[Dict[str, Any]]:
    sequence_offset = int(session["_state"].get("generation_offset", 0))
    base_sequence = _generate_sequence(
        run_id=session["session_id"],
        scenario=session["scenario"],
        traffic_type=session["traffic_type"],
        request_count=request_count,
        rng=rng,
        namespace_keys=False,
        stable_services=True,
    )

    key_mode = session["key_mode"]
    profile = _KEY_MODE_PROFILES.get(key_mode, _KEY_MODE_PROFILES["mixed"])
    if key_mode == "stable":
        session["_state"]["generation_offset"] = sequence_offset + len(base_sequence)
        return base_sequence

    rotation_window = max(1, int(profile["rotation_window"]))
    variant_pool = max(2, int(profile["variant_pool"]))
    rotation_rate = float(profile["rotation_rate"])
    ephemeral_rate = float(profile["ephemeral_rate"])

    for index, request_item in enumerate(base_sequence):
        global_index = sequence_offset + index
        base_key = str(request_item["key_id"])

        if rng.random() < rotation_rate:
            rotation_bucket = (global_index // rotation_window) % variant_pool
            request_item["key_id"] = f"{base_key}:rot:{rotation_bucket}"

        if rng.random() < ephemeral_rate:
            ephemeral_bucket = (global_index % (variant_pool * 5)) + 1
            request_item["key_id"] = f"{request_item['key_id']}:session:{ephemeral_bucket}"

    session["_state"]["generation_offset"] = sequence_offset + len(base_sequence)
    return base_sequence


def _clone_runtime_predictor() -> Tuple[Optional[KeyPredictor], Dict[str, Any]]:
    trainer = get_model_trainer()
    runtime_load = trainer.ensure_runtime_model_loaded()
    runtime_status = get_ml_status_payload()

    if not runtime_status.get("model_loaded"):
        return None, {
            "loaded": False,
            "source": "runtime",
            "version": runtime_status.get("model_version"),
            "stage": runtime_status.get("model_stage"),
            "reason": runtime_load.get("reason") or "runtime_model_not_loaded",
        }

    shadow_predictor = KeyPredictor(
        model=trainer.model,
        top_n=settings.ml_top_n_predictions,
        threshold=settings.ml_prediction_threshold,
    )
    shadow_predictor.attach_model(
        trainer.model,
        source=str(trainer.get_stats().get("model_source") or "runtime"),
        version=runtime_status.get("model_version"),
        artifact_path=trainer.get_stats().get("artifact_path"),
    )
    top10 = _float_or_zero(runtime_status.get("model_top_10_accuracy"))
    top1 = _float_or_zero(runtime_status.get("model_accuracy"))
    metric_name, metric_value = _metric_basis(top10, top1)
    return shadow_predictor, {
        "loaded": True,
        "source": "runtime",
        "version": runtime_status.get("model_version"),
        "stage": runtime_status.get("model_stage"),
        "metric_name": metric_name,
        "metric_value": metric_value,
        "top_1_accuracy": top1,
        "top_10_accuracy": top10,
        "is_active_runtime": True,
    }


def _select_simulation_predictor(
    *,
    model_name: Optional[str] = None,
    preference: str = "best_available",
) -> Tuple[Optional[KeyPredictor], Dict[str, Any]]:
    runtime_predictor, runtime_meta = _clone_runtime_predictor()
    runtime_score = (
        _float_or_zero(runtime_meta.get("top_10_accuracy")),
        _float_or_zero(runtime_meta.get("top_1_accuracy")),
        4,
        time.time(),
    ) if runtime_meta.get("loaded") else (-1.0, -1.0, -1, -1.0)

    effective_model_name = model_name or settings.ml_model_name
    if preference == "active_runtime":
        return runtime_predictor, {
            **runtime_meta,
            "requested_preference": preference,
            "effective_preference": "active_runtime",
        }

    registry = get_model_registry()
    summary = registry.get_model_summary(effective_model_name)
    sorted_versions = sorted(
        summary.get("versions", []),
        key=_version_metric_tuple,
        reverse=True,
    )

    for version_entry in sorted_versions:
        version_score = _version_metric_tuple(version_entry)
        if runtime_predictor is not None and version_score <= runtime_score:
            break

        try:
            loaded_model = registry.load_model(
                effective_model_name,
                version=version_entry.get("version"),
                actor="simulation_shadow",
            )
        except SecurityError:
            continue

        if loaded_model is None:
            continue

        shadow_predictor = KeyPredictor(
            model=loaded_model,
            top_n=settings.ml_top_n_predictions,
            threshold=settings.ml_prediction_threshold,
        )
        shadow_predictor.attach_model(
            loaded_model,
            source="registry_shadow",
            version=version_entry.get("version"),
            artifact_path=version_entry.get("file_path"),
        )
        top10, top1, _, _ = version_score
        metric_name, metric_value = _metric_basis(top10, top1)
        return shadow_predictor, {
            "loaded": True,
            "source": "registry_shadow",
            "version": version_entry.get("version"),
            "stage": version_entry.get("stage"),
            "metric_name": metric_name,
            "metric_value": metric_value,
            "top_1_accuracy": top1,
            "top_10_accuracy": top10,
            "is_active_runtime": version_entry.get("version") == runtime_meta.get("version"),
            "requested_preference": preference,
            "effective_preference": "best_available",
        }

    if runtime_predictor is not None:
        runtime_meta = dict(runtime_meta)
        runtime_meta["requested_preference"] = preference
        runtime_meta["effective_preference"] = "active_runtime_fallback"
        return runtime_predictor, runtime_meta

    return None, {
        **runtime_meta,
        "requested_preference": preference,
        "effective_preference": "no_model_available",
    }


def _clear_live_cache_namespace(app_state: Any) -> int:
    secure_manager = app_state.secure_cache_manager
    removed = 0
    for cache_key in list(secure_manager.get_cache_keys()):
        if ":" not in cache_key:
            continue
        service_id, key_id = cache_key.split(":", 1)
        if not service_id.startswith("sim-live-"):
            continue
        if secure_manager.secure_delete(key_id, service_id, reason="live_simulation_reset"):
            removed += 1
    return removed


def _bootstrap_model_if_needed(
    *,
    session_id: str,
    scenario: str,
    traffic_type: str,
    seed_data: bool,
) -> Dict[str, Any]:
    trainer = get_model_trainer()
    collector = get_data_collector()
    if trainer.ensure_runtime_model_loaded().get("success"):
        return {
            "seeded": False,
            "trained": False,
            "events_imported": 0,
            "reason": "runtime_model_already_available",
        }

    if not seed_data:
        return {
            "seeded": False,
            "trained": False,
            "events_imported": 0,
            "reason": "seed_data_disabled",
        }

    rng = random.Random(f"{session_id}:bootstrap")
    seed_events = _build_seed_events(
        run_id=session_id,
        scenario=scenario,
        traffic_type=traffic_type,
        rng=rng,
        namespace_keys=False,
        stable_services=True,
    )
    imported = collector.import_events(seed_events)
    train_result = trainer.train(force=True, reason="live_simulation_bootstrap")
    return {
        "seeded": True,
        "trained": bool(train_result.get("success")),
        "events_imported": imported,
        "reason": train_result.get("reason") or "live_simulation_bootstrap",
        "train_result": {
            "success": bool(train_result.get("success")),
            "model_accepted": bool(train_result.get("model_accepted", False)),
            "active_version": train_result.get("active_version"),
            "val_accuracy": train_result.get("val_accuracy"),
            "val_top_10_accuracy": train_result.get("val_top_10_accuracy"),
        },
    }


def _make_session_snapshot(session: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in session.items()
        if not key.startswith("_")
    }


def _session_key_breakdown(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    breakdown = []
    for key_id, counters in state["key_breakdown"].items():
        breakdown.append(
            {
                "key_id": key_id,
                "total": counters.get("total", 0),
                "l1_hits": counters.get("l1_hit", 0),
                "l2_hits": counters.get("l2_hit", 0),
                "late_cache_hits": counters.get("late_cache_hit", 0),
                "kms_fetches": counters.get("kms_fetch", 0),
                "kms_misses": counters.get("kms_miss", 0),
                "blocked": counters.get("blocked", 0),
            }
        )
    breakdown.sort(key=lambda item: (item["total"], item["l1_hits"] + item["l2_hits"]), reverse=True)
    return breakdown[:_KEY_BREAKDOWN_LIMIT]


def _refresh_session_view(session: Dict[str, Any], app_state: Any, queue_stats: Dict[str, Any]) -> None:
    state = session["_state"]
    path_counts = state["path_counts"]
    pskc_kms_latencies = state["kms_latency_samples"].get("pskc", [])
    baseline_kms_latencies = state["kms_latency_samples"].get("direct", [])
    live_accuracy = {
        "top_1_accuracy": _safe_rate(state["top1_hits"], state["prediction_samples"]),
        "top_10_accuracy": _safe_rate(state["top10_hits"], state["prediction_samples"]),
        "prediction_samples": state["prediction_samples"],
        "top_1_hits": state["top1_hits"],
        "top_10_hits": state["top10_hits"],
    }
    prefetch = {
        "prefetch_opportunities": state["prefetch_opportunities"],
        "verified_prefetch_hits": state["verified_prefetch_hits"],
        "verified_prefetch_hit_rate": _safe_rate(
            state["verified_prefetch_hits"],
            state["prefetch_opportunities"],
        ),
        "worker_prefetched_hits": state["worker_prefetched_hits"],
        "request_cached_hits": state["request_cached_hits"],
        "cache_hits_without_origin": state["cache_hits_without_origin"],
        "cache_origin_breakdown": [
            {"name": "Worker-prefetched", "value": state["worker_prefetched_hits"], "color": "#14b8a6"},
            {"name": "Request-cached", "value": state["request_cached_hits"], "color": "#0ea5e9"},
            {"name": "Unknown origin", "value": state["cache_hits_without_origin"], "color": "#94a3b8"},
        ],
        "worker_completed_delta": max(
            0,
            int(queue_stats.get("stats", {}).get("completed_total", 0)) - state["queue_completed_before"],
        ),
        "queue_length": int(queue_stats.get("queue_length", 0)),
        "active_workers": [worker for worker in queue_stats.get("workers", []) if worker.get("active")],
    }
    pskc_request_count = len(state["pskc_latencies"])
    pskc_hits = path_counts["l1_hit"] + path_counts["l2_hit"] + path_counts["late_cache_hit"]
    pskc_metrics = {
        "request_count": pskc_request_count,
        "avg_latency_ms": round(sum(state["pskc_latencies"]) / pskc_request_count, 2) if pskc_request_count else 0.0,
        "p95_latency_ms": _p95(state["pskc_latencies"]),
        "cache_hit_rate": _safe_rate(pskc_hits, pskc_request_count - path_counts["blocked"]),
        "l1_hits": path_counts["l1_hit"],
        "l2_hits": path_counts["l2_hit"],
        "late_cache_hits": path_counts["late_cache_hit"],
        "kms_fetches": path_counts["kms_fetch"],
        "kms_misses": path_counts["kms_miss"],
        "kms_avg_latency_ms": round(sum(pskc_kms_latencies) / len(pskc_kms_latencies), 2) if pskc_kms_latencies else 0.0,
        "kms_p95_latency_ms": _p95(pskc_kms_latencies),
        "blocked": path_counts["blocked"],
        "path_breakdown": [
            {"name": "L1 Hit", "value": path_counts["l1_hit"], "color": "#14b8a6"},
            {"name": "L2 Hit", "value": path_counts["l2_hit"], "color": "#0ea5e9"},
            {"name": "Late Cache Hit", "value": path_counts["late_cache_hit"], "color": "#22c55e"},
            {"name": "KMS Fetch", "value": path_counts["kms_fetch"], "color": "#f59e0b"},
            {"name": "KMS Miss", "value": path_counts["kms_miss"], "color": "#ef4444"},
            {"name": "Blocked", "value": path_counts["blocked"], "color": "#a855f7"},
        ],
    }
    baseline_request_count = len(state["baseline_latencies"])
    baseline_metrics = {
        "request_count": baseline_request_count,
        "avg_latency_ms": round(sum(state["baseline_latencies"]) / baseline_request_count, 2)
        if baseline_request_count
        else 0.0,
        "p95_latency_ms": _p95(state["baseline_latencies"]),
        "direct_kms_requests": baseline_request_count,
        "direct_kms_avg_latency_ms": round(sum(baseline_kms_latencies) / len(baseline_kms_latencies), 2)
        if baseline_kms_latencies
        else 0.0,
        "direct_kms_p95_latency_ms": _p95(baseline_kms_latencies),
    }
    baseline_avg = baseline_metrics["avg_latency_ms"]
    pskc_avg = pskc_metrics["avg_latency_ms"]
    comparison = {
        "avg_latency_saved_ms": round(max(0.0, baseline_avg - pskc_avg), 2),
        "latency_improvement_percent": round(((baseline_avg - pskc_avg) / baseline_avg) * 100, 2)
        if baseline_avg > 0
        else 0.0,
    }
    component_status = _component_snapshot(app_state, queue_stats)
    fetcher = get_key_fetcher()
    component_status.update(
        {
            "kms_provider": getattr(getattr(fetcher, "_provider", None), "value", "generic"),
            "kms_endpoint_configured": bool(getattr(fetcher, "_endpoint", None)),
            "configured_rps": float(TRAFFIC_PROFILES.get(session["traffic_type"], TRAFFIC_PROFILES["normal"])["rps"]),
            "virtual_node_count": int(session.get("virtual_nodes", 1)),
            "virtual_l1_cache_size": sum(
                int(node["local_cache"].get_stats().get("size", 0))
                for node in state.get("virtual_nodes", [])
            ),
            "selected_model_version": session["selected_model"].get("version"),
            "selected_model_source": session["selected_model"].get("source"),
            "selected_model_stage": session["selected_model"].get("stage"),
            "selected_model_metric_name": session["selected_model"].get("metric_name"),
            "selected_model_metric_value": session["selected_model"].get("metric_value"),
            "selected_model_is_active_runtime": session["selected_model"].get("is_active_runtime", False),
        }
    )
    session["updated_at"] = _now_iso()
    session["requests_processed"] = state["requests_processed"]
    session["component_status"] = component_status
    session["model"] = session["selected_model"]
    session["live_accuracy"] = live_accuracy
    session["prefetch"] = prefetch
    session["pskc_metrics"] = pskc_metrics
    session["baseline_metrics"] = baseline_metrics
    session["comparison"] = comparison
    session["trace"] = list(state["trace"])
    session["key_breakdown"] = _session_key_breakdown(state)
    session["honesty_checks"] = {
        "uses_ground_truth_next_request": True,
        "prediction_sample_count": state["prediction_samples"],
        "uses_same_request_stream_for_baseline": session["simulate_kms"],
        "cache_path_tracked_explicitly": True,
        "cache_origin_tracked": True,
        "model_loaded": bool(session["selected_model"].get("loaded")),
        "selected_model_is_active_runtime": session["selected_model"].get("is_active_runtime", False),
        "stable_simulation_keys": session.get("key_mode") == "stable",
        "session_learning_overlay": True,
        "key_mode": session.get("key_mode"),
    }


def _update_key_breakdown(state: Dict[str, Any], key_id: str, path: str) -> None:
    counters = state["key_breakdown"].setdefault(key_id, {"total": 0})
    counters["total"] = counters.get("total", 0) + 1
    counters[path] = counters.get(path, 0) + 1


def _cache_origin_key(service_id: str, key_id: str) -> str:
    return f"{service_id}:{key_id}"


def _ingest_worker_events(state: Dict[str, Any], worker_events: List[Dict[str, Any]]) -> None:
    for event in worker_events:
        job_id = event.get("job_id")
        if not job_id or job_id in state["seen_worker_job_ids"]:
            continue
        state["seen_worker_job_ids"].add(job_id)
        if event.get("status") != "completed":
            continue

        service_id = str(event.get("service_id") or "default")
        source_key_id = str(event.get("source_key_id") or "")
        timestamp = float(event.get("timestamp") or time.time())
        for key_id in event.get("prefetched_keys", []) or []:
            state["cache_origins"][_cache_origin_key(service_id, key_id)] = {
                "source": "worker_prefetch",
                "source_key_id": source_key_id,
                "updated_at": timestamp,
            }


async def _process_live_request(
    *,
    session: Dict[str, Any],
    app_state: Any,
    predictor: Optional[KeyPredictor],
    request_item: Dict[str, Any],
) -> None:
    state = session["_state"]
    queue = get_prefetch_queue()
    fetcher = get_key_fetcher()
    _ingest_worker_events(state, state["previous_worker_events"])
    virtual_nodes = state["virtual_nodes"]
    node = virtual_nodes[state["node_cursor"] % len(virtual_nodes)]
    state["node_cursor"] += 1
    secure_manager = node["secure_manager"]
    node_id = node["node_id"]
    key_id = request_item["key_id"]
    service_id = request_item["service_id"]
    ip_address = request_item["ip_address"]
    request_index = state["requests_processed"] + 1
    cache_layer_before = secure_manager.inspect_cache_path(key_id, service_id)
    cache_origin_before = state["cache_origins"].get(_cache_origin_key(service_id, key_id))
    prefetched_before_request = cache_layer_before in {"l1", "l2"}

    previous_predictions = state["previous_predictions_by_service"].get(service_id, [])
    predicted_on_previous = False
    top1_correct = False
    top10_correct = False
    prefetched_by_worker = False
    cache_origin_source = cache_origin_before.get("source") if cache_origin_before else "unknown"
    if previous_predictions:
        predicted_keys = [predicted_key for predicted_key, _ in previous_predictions]
        predicted_on_previous = key_id in predicted_keys
        top1_correct = bool(predicted_keys and predicted_keys[0] == key_id)
        top10_correct = predicted_on_previous
        state["prediction_samples"] += 1
        state["top1_hits"] += int(top1_correct)
        state["top10_hits"] += int(top10_correct)
        if predicted_on_previous:
            state["prefetch_opportunities"] += 1
    if prefetched_before_request:
        if cache_origin_source == "worker_prefetch":
            state["worker_prefetched_hits"] += 1
        elif cache_origin_source == "request_fetch":
            state["request_cached_hits"] += 1
        else:
            state["cache_hits_without_origin"] += 1
    if prefetched_before_request and cache_origin_before is not None:
        prefetched_by_worker = cache_origin_source == "worker_prefetch"
        if prefetched_by_worker and predicted_on_previous:
            state["verified_prefetch_hits"] += 1

    request_started = time.perf_counter()
    key_data, cache_hit, _, allowed = secure_manager.secure_get(key_id, service_id, ip_address)
    kms_latency_ms = None
    if not allowed:
        path = "blocked"
    elif key_data is None:
        target_kms_latency_ms = _resolve_kms_latency_target_ms(session, lane="pskc")
        key_data, kms_latency_ms = await _fetch_key_with_kms_latency(
            fetcher,
            key_id=key_id,
            service_id=service_id,
            target_latency_ms=target_kms_latency_ms,
        )
        _record_kms_latency(state, "pskc", kms_latency_ms)
        if key_data:
            secure_manager.secure_set(key_id, key_data, service_id, ip_address=ip_address)
            state["cache_origins"][_cache_origin_key(service_id, key_id)] = {
                "source": "request_fetch",
                "source_key_id": key_id,
                "updated_at": time.time(),
            }
            path = "kms_fetch"
        else:
            path = "kms_miss"
    else:
        if cache_layer_before == "l1":
            path = "l1_hit"
        elif cache_layer_before == "l2":
            path = "l2_hit"
        else:
            path = "late_cache_hit"

    total_latency_ms = round((time.perf_counter() - request_started) * 1000, 2)
    state["path_counts"][path] = state["path_counts"].get(path, 0) + 1
    state["pskc_latencies"].append(total_latency_ms)
    _update_key_breakdown(state, key_id, path)

    baseline_latency_ms = None
    baseline_kms_latency_ms = None
    if session["simulate_kms"]:
        baseline_kms_latency_ms = _resolve_kms_latency_target_ms(session, lane="direct")
        baseline_latency_ms = round(
            baseline_kms_latency_ms + _resolve_request_overhead_ms(session, lane="direct"),
            2,
        )
        state["baseline_latencies"].append(baseline_latency_ms)
        _record_kms_latency(state, "direct", baseline_kms_latency_ms)

    if allowed and key_data is not None:
        record_runtime_access(
            key_id=key_id,
            service_id=service_id,
            latency_ms=total_latency_ms,
            cache_hit=bool(cache_hit),
            simulated=True,
            simulation_id=session["session_id"],
            journey=request_item["journey"],
            ip_address=ip_address,
        )

    previous_key_for_service = state["last_key_by_service"].get(service_id)
    if previous_key_for_service is not None:
        state["adaptive_transitions"][service_id][previous_key_for_service][key_id] += 1
    state["adaptive_popularity"][service_id][key_id] += 1
    state["last_key_by_service"][service_id] = key_id

    prediction_preview: List[Dict[str, Any]] = []
    prefetch_mode = "noop"
    prediction_source = "none"
    predictions: List[Tuple[str, float]] = []
    if predictor is not None and predictor.model is not None:
        predictor.clear_cache()
        model_predictions = predictor.predict(service_id=service_id, n=10, min_confidence=0.0)
        adaptive_predictions = _session_learning_predictions(
            state,
            service_id=service_id,
            current_key=key_id,
            n=10,
        )
        predictions = _merge_prediction_sources(model_predictions, adaptive_predictions, n=10)
        prediction_source = "hybrid_session_learning" if adaptive_predictions else "model_only"
        overlay_predictor = _SessionOverlayPredictor(predictions) if predictions else predictor
        prefetch_result = schedule_request_path_prefetch(
            secure_manager,
            service_id,
            key_id,
            ip_address,
            predictor_override=overlay_predictor,
        )
        prediction_preview = [
            {"key_id": predicted_key, "confidence": round(float(confidence), 4)}
            for predicted_key, confidence in predictions[:3]
        ]
        prefetch_mode = str(prefetch_result.get("mode") or "noop")
        state["previous_predictions_by_service"][service_id] = predictions
    else:
        state["previous_predictions_by_service"][service_id] = []

    queue_after_iteration = queue.get_stats()
    state["previous_worker_events"] = queue_after_iteration.get("recent_worker_events", [])
    state["requests_processed"] = request_index
    state["trace"].append(
        {
            "index": request_index,
            "service_id": service_id,
            "node_id": node_id,
            "key_id": key_id,
            "path": path,
            "cache_layer_before": cache_layer_before.upper(),
            "cache_hit": bool(cache_hit),
            "latency_ms": total_latency_ms,
            "kms_latency_ms": kms_latency_ms,
            "baseline_kms_latency_ms": baseline_kms_latency_ms,
            "baseline_latency_ms": baseline_latency_ms,
            "latency_saved_ms": round((baseline_latency_ms or 0.0) - total_latency_ms, 2)
            if baseline_latency_ms is not None
            else None,
            "predicted_on_previous": predicted_on_previous,
            "top1_correct": top1_correct,
            "top10_correct": top10_correct,
            "prefetched_before_request": prefetched_before_request,
            "prefetched_by_worker": prefetched_by_worker,
            "cache_origin_before": cache_origin_source,
            "cache_origin_source_key": cache_origin_before.get("source_key_id") if cache_origin_before else None,
            "prediction_preview": prediction_preview,
            "prediction_source": prediction_source,
            "prefetch_mode": prefetch_mode,
            "queue_length": queue_after_iteration.get("queue_length", 0),
        }
    )
    if len(state["trace"]) > _TRACE_LIMIT:
        state["trace"] = state["trace"][-_TRACE_LIMIT:]


async def _run_live_session(session_id: str, app_state: Any) -> None:
    with _SESSION_LOCK:
        session = _LIVE_SESSIONS.get(session_id)
        if session is None:
            return

    queue = get_prefetch_queue()
    try:
        session["status"] = "preparing"
        session["_state"]["virtual_nodes"] = _build_virtual_nodes(app_state, session.get("virtual_nodes", _DEFAULT_VIRTUAL_NODES))
        session["preparation"] = {
            "cleared_simulation_cache_entries": _clear_live_cache_namespace(app_state),
        }
        session["preparation"].update(
            _bootstrap_model_if_needed(
                session_id=session_id,
                scenario=session["scenario"],
                traffic_type=session["traffic_type"],
                seed_data=session["seed_data"],
            )
        )
        predictor, model_meta = _select_simulation_predictor(
            preference=session["model_preference"],
        )
        session["selected_model"] = model_meta
        session["status"] = "running"

        rng = random.Random(session_id)
        buffer: List[Dict[str, Any]] = []
        queue_before = queue.get_stats()
        session["_state"]["queue_completed_before"] = int(queue_before.get("stats", {}).get("completed_total", 0))
        session["_state"]["previous_worker_events"] = queue_before.get("recent_worker_events", [])
        interval_seconds = max(
            0.05,
            1.0 / float(TRAFFIC_PROFILES.get(session["traffic_type"], TRAFFIC_PROFILES["normal"])["rps"]),
        )

        while not session["_stop_requested"]:
            max_requests = session.get("max_requests")
            if max_requests and session["_state"]["requests_processed"] >= max_requests:
                session["status"] = "completed"
                break

            if not buffer:
                buffer = _generate_live_buffer(
                    session=session,
                    rng=rng,
                    request_count=120,
                )

            await _process_live_request(
                session=session,
                app_state=app_state,
                predictor=predictor,
                request_item=buffer.pop(0),
            )
            _refresh_session_view(session, app_state, queue.get_stats())
            await asyncio.sleep(interval_seconds)

        if session["_stop_requested"] and session["status"] == "running":
            session["status"] = "stopped"
            session["stopped_at"] = _now_iso()
        if session["status"] == "running":
            session["status"] = "completed"
    except Exception as exc:
        session["status"] = "failed"
        session["last_error"] = str(exc)
    finally:
        _shutdown_virtual_nodes(session["_state"].get("virtual_nodes", []))
        session["completed_at"] = _now_iso()
        _refresh_session_view(session, app_state, queue.get_stats())


async def start_live_simulation_session(
    *,
    app_state: Any,
    scenario: str,
    traffic_type: str,
    seed_data: bool = True,
    simulate_kms: bool = True,
    model_preference: str = "best_available",
    key_mode: str = "auto",
    virtual_nodes: int = _DEFAULT_VIRTUAL_NODES,
    max_requests: Optional[int] = None,
) -> Dict[str, Any]:
    session_id = str(uuid.uuid4())
    resolved_key_mode = _normalize_key_mode(key_mode, traffic_type)
    session = {
        "session_id": session_id,
        "status": "starting",
        "scenario": scenario,
        "traffic_type": traffic_type,
        "seed_data": seed_data,
        "simulate_kms": simulate_kms,
        "model_preference": model_preference,
        "key_mode": resolved_key_mode,
        "virtual_nodes": max(1, int(virtual_nodes or _DEFAULT_VIRTUAL_NODES)),
        "max_requests": max_requests,
        "started_at": _now_iso(),
        "updated_at": _now_iso(),
        "completed_at": None,
        "stopped_at": None,
        "last_error": None,
        "selected_model": {},
        "component_status": {},
        "live_accuracy": {
            "top_1_accuracy": 0.0,
            "top_10_accuracy": 0.0,
            "prediction_samples": 0,
            "top_1_hits": 0,
            "top_10_hits": 0,
        },
        "prefetch": {
            "prefetch_opportunities": 0,
            "verified_prefetch_hits": 0,
            "verified_prefetch_hit_rate": 0.0,
            "worker_prefetched_hits": 0,
            "request_cached_hits": 0,
            "cache_hits_without_origin": 0,
            "cache_origin_breakdown": [],
            "worker_completed_delta": 0,
            "queue_length": 0,
            "active_workers": [],
        },
        "pskc_metrics": {
            "request_count": 0,
            "avg_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "cache_hit_rate": 0.0,
            "l1_hits": 0,
            "l2_hits": 0,
            "late_cache_hits": 0,
            "kms_fetches": 0,
            "kms_misses": 0,
            "kms_avg_latency_ms": 0.0,
            "kms_p95_latency_ms": 0.0,
            "blocked": 0,
            "path_breakdown": [],
        },
        "baseline_metrics": {
            "request_count": 0,
            "avg_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "direct_kms_requests": 0,
            "direct_kms_avg_latency_ms": 0.0,
            "direct_kms_p95_latency_ms": 0.0,
        },
        "comparison": {
            "avg_latency_saved_ms": 0.0,
            "latency_improvement_percent": 0.0,
        },
        "requests_processed": 0,
        "honesty_checks": {
            "uses_ground_truth_next_request": True,
            "prediction_sample_count": 0,
            "uses_same_request_stream_for_baseline": simulate_kms,
            "cache_path_tracked_explicitly": True,
            "model_loaded": False,
            "selected_model_is_active_runtime": False,
            "stable_simulation_keys": resolved_key_mode == "stable",
            "key_mode": resolved_key_mode,
        },
        "trace": [],
        "key_breakdown": [],
        "_stop_requested": False,
        "_task": None,
        "_state": {
            "requests_processed": 0,
            "pskc_latencies": [],
            "baseline_latencies": [],
            "path_counts": {
                "l1_hit": 0,
                "l2_hit": 0,
                "late_cache_hit": 0,
                "kms_fetch": 0,
                "kms_miss": 0,
                "blocked": 0,
            },
            "prediction_samples": 0,
            "top1_hits": 0,
            "top10_hits": 0,
            "prefetch_opportunities": 0,
            "verified_prefetch_hits": 0,
            "worker_prefetched_hits": 0,
            "request_cached_hits": 0,
            "cache_hits_without_origin": 0,
            "previous_predictions_by_service": {},
            "previous_worker_events": [],
            "queue_completed_before": 0,
            "trace": [],
            "key_breakdown": {},
            "cache_origins": {},
            "seen_worker_job_ids": set(),
            "generation_offset": 0,
            "node_cursor": 0,
            "kms_rng": random.Random(f"{session_id}:kms"),
            "kms_windows": {
                "pskc": deque(),
                "direct": deque(),
            },
            "kms_latency_samples": {
                "pskc": [],
                "direct": [],
            },
            "adaptive_transitions": defaultdict(lambda: defaultdict(Counter)),
            "adaptive_popularity": defaultdict(Counter),
            "last_key_by_service": {},
            "virtual_nodes": [],
        },
    }
    with _SESSION_LOCK:
        _LIVE_SESSIONS[session_id] = session
    session["_task"] = asyncio.create_task(_run_live_session(session_id, app_state))
    return _make_session_snapshot(session)


def get_live_simulation_session(session_id: str) -> Optional[Dict[str, Any]]:
    with _SESSION_LOCK:
        session = _LIVE_SESSIONS.get(session_id)
        if session is None:
            return None
        return _make_session_snapshot(session)


def stop_live_simulation_session(session_id: str) -> Optional[Dict[str, Any]]:
    with _SESSION_LOCK:
        session = _LIVE_SESSIONS.get(session_id)
        if session is None:
            return None
        session["_stop_requested"] = True
        if session["status"] == "running":
            session["status"] = "stopping"
        session["updated_at"] = _now_iso()
        return _make_session_snapshot(session)
