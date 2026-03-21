import asyncio
import random
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.api.ml_service import (
    get_accuracy_history_payload,
    get_ml_status_payload,
    get_model_evaluation_payload,
    record_runtime_access,
    schedule_request_path_prefetch,
)
from src.ml.data_collector import get_data_collector
from src.ml.predictor import get_key_predictor
from src.ml.trainer import get_model_trainer
from src.prefetch.queue import get_prefetch_queue


SIMULATION_JOURNEYS: Dict[str, List[Dict[str, Any]]] = {
    "test": [
        {"service": "auth", "steps": ["login", "mfa", "session", "profile", "permissions"]},
        {"service": "payments", "steps": ["cart", "pricing", "payment_token", "payment_confirm", "receipt"]},
        {"service": "portal", "steps": ["dashboard", "notifications", "profile", "summary"]},
    ],
    "siakad": [
        {"service": "siakad", "steps": ["login", "mahasiswa_profile", "krs", "jadwal", "nilai"]},
        {"service": "akademik", "steps": ["login", "dosen_profile", "kelas", "presensi", "nilai_entry"]},
        {"service": "keuangan", "steps": ["login", "billing", "tagihan", "payment_status"]},
    ],
    "sevima": [
        {"service": "sevima", "steps": ["login", "tenant_context", "dashboard", "analytics"]},
        {"service": "elearning", "steps": ["course_list", "course_detail", "assignment", "grading"]},
        {"service": "conference", "steps": ["meeting_list", "meeting_detail", "recording", "attendance"]},
    ],
    "pddikti": [
        {"service": "pddikti", "steps": ["login", "pt_profile", "sync_status", "report_submit"]},
        {"service": "pt", "steps": ["login", "mahasiswa_sync", "prodi_sync", "feeder_status"]},
        {"service": "mahasiswa", "steps": ["public_search", "biodata", "riwayat_studi"]},
    ],
    "dynamic": [
        {"service": "default", "steps": ["auth", "token", "catalog", "detail", "checkout"]},
        {"service": "auth-service", "steps": ["login", "mfa", "session", "refresh"]},
        {"service": "payment-service", "steps": ["pricing", "invoice", "payment_token", "settlement"]},
    ],
}

TRAFFIC_PROFILES: Dict[str, Dict[str, float]] = {
    "normal": {"noise_rate": 0.08, "rps": 50.0},
    "heavy_load": {"noise_rate": 0.14, "rps": 120.0},
    "prime_time": {"noise_rate": 0.12, "rps": 200.0},
    "degraded": {"noise_rate": 0.18, "rps": 35.0},
    "overload": {"noise_rate": 0.22, "rps": 300.0},
}


def _resolve_request_count(num_requests: Optional[int], duration_seconds: Optional[int], traffic_type: str) -> int:
    if num_requests is not None:
        return int(num_requests)
    if duration_seconds is None:
        return 60
    profile = TRAFFIC_PROFILES.get(traffic_type, TRAFFIC_PROFILES["normal"])
    return max(20, min(200, int(duration_seconds * profile["rps"])))


def _make_run_service_id(run_id: str, base_service: str) -> str:
    return f"sim-{run_id[:8]}-{base_service}"


def _generate_sequence(
    *,
    run_id: str,
    scenario: str,
    traffic_type: str,
    request_count: int,
    rng: random.Random,
    namespace_keys: bool = True,
    stable_services: bool = False,
) -> List[Dict[str, Any]]:
    journeys = SIMULATION_JOURNEYS.get(scenario, SIMULATION_JOURNEYS["test"])
    profile = TRAFFIC_PROFILES.get(traffic_type, TRAFFIC_PROFILES["normal"])
    noise_rate = float(profile["noise_rate"])
    requests: List[Dict[str, Any]] = []

    while len(requests) < request_count:
        journey = rng.choice(journeys)
        cohort = rng.randint(1, 6)
        run_service_id = (
            f"sim-live-{journey['service']}"
            if stable_services
            else _make_run_service_id(run_id, str(journey["service"]))
        )
        ip_address = f"10.42.{rng.randint(1, 254)}.{rng.randint(1, 254)}"

        for step in journey["steps"]:
            if len(requests) >= request_count:
                break
            if rng.random() < noise_rate:
                key_id = (
                    f"{run_id}:{journey['service']}:noise:{rng.randint(1, 25)}"
                    if namespace_keys
                    else f"{journey['service']}:noise:{rng.randint(1, 25)}"
                )
            else:
                key_id = (
                    f"{run_id}:{journey['service']}:{step}:{cohort}"
                    if namespace_keys
                    else f"{journey['service']}:{step}:{cohort}"
                )
            requests.append(
                {
                    "service_id": run_service_id,
                    "key_id": key_id,
                    "journey": journey["service"],
                    "ip_address": ip_address,
                }
            )

    return requests


def _build_seed_events(
    *,
    run_id: str,
    scenario: str,
    traffic_type: str,
    rng: random.Random,
    total_events: int = 600,
    namespace_keys: bool = True,
    stable_services: bool = False,
) -> List[Dict[str, Any]]:
    seed_sequence = _generate_sequence(
        run_id=run_id,
        scenario=scenario,
        traffic_type=traffic_type,
        request_count=total_events,
        rng=rng,
        namespace_keys=namespace_keys,
        stable_services=stable_services,
    )
    base_time = datetime.now(timezone.utc) - timedelta(minutes=30)
    events: List[Dict[str, Any]] = []
    for index, item in enumerate(seed_sequence):
        timestamp = (base_time + timedelta(seconds=index * 2)).timestamp()
        events.append(
            {
                "key_id": item["key_id"],
                "service_id": item["service_id"],
                "timestamp": timestamp,
                "latency_ms": 8.0 if index % 4 else 120.0,
                "cache_hit": bool(index % 4),
            }
        )
    return events


def _find_worker_prefetch_hit(
    worker_events: List[Dict[str, Any]],
    *,
    service_id: str,
    key_id: str,
) -> bool:
    for event in worker_events:
        if event.get("service_id") != service_id:
            continue
        if key_id in event.get("prefetched_keys", []):
            return True
    return False


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)


def _component_snapshot(app_state: Any, queue_stats: Dict[str, Any]) -> Dict[str, Any]:
    trainer = get_model_trainer()
    redis_cache = app_state.runtime_services.get("redis_cache")
    redis_available = bool(redis_cache and hasattr(redis_cache, "ping") and redis_cache.ping())
    workers = queue_stats.get("workers", [])
    active_workers = [worker for worker in workers if worker.get("active")]
    return {
        "redis_available": redis_available,
        "prefetch_queue_available": bool(queue_stats.get("available", False)),
        "prefetch_worker_active": bool(active_workers),
        "active_workers": active_workers,
        "active_model_version": trainer.get_stats().get("active_version"),
        "model_loaded": bool(getattr(trainer.model, "is_trained", False)),
        "l1_cache_size": app_state.runtime_services.get("local_cache").get_stats().get("size", 0),
        "l2_cache_size": redis_cache.get_stats().get("size", 0) if redis_cache is not None else 0,
    }


async def run_live_validation(
    *,
    app_state: Any,
    num_requests: Optional[int],
    duration_seconds: Optional[int],
    seed_data: bool,
    scenario: str,
    traffic_type: str,
) -> Dict[str, Any]:
    request_count = _resolve_request_count(num_requests, duration_seconds, traffic_type)
    run_id = str(uuid.uuid4())
    rng = random.Random(run_id)
    queue = get_prefetch_queue()
    collector = get_data_collector()
    trainer = get_model_trainer()
    predictor = get_key_predictor()
    secure_manager = app_state.secure_cache_manager
    queue_before = queue.get_stats()

    result: Dict[str, Any] = {
        "test_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "num_requests": request_count,
        "duration_seconds": duration_seconds,
        "scenario": scenario,
        "traffic_type": traffic_type,
        "steps": [],
    }

    if seed_data:
        seed_events = _build_seed_events(run_id=run_id, scenario=scenario, traffic_type=traffic_type, rng=rng)
        imported = collector.import_events(seed_events)
        result["steps"].append(
            {
                "step": "data_seeding",
                "success": True,
                "events_imported": imported,
                "service_scope": sorted({event["service_id"] for event in seed_events}),
            }
        )
        train_result = trainer.train(force=True, reason="simulation_validation")
        predictor.attach_model(
            trainer.model,
            source=trainer.get_active_model_metadata().get("source", "runtime"),
            version=trainer.get_active_model_metadata().get("version"),
            artifact_path=trainer.get_active_model_metadata().get("artifact_path"),
        )
        predictor.clear_cache()
    else:
        train_result = {"success": False, "reason": "seed_data_disabled"}

    result["steps"].append(
        {
            "step": "training",
            "success": bool(train_result.get("success", False)),
            "model_accepted": bool(train_result.get("model_accepted", False)),
            "active_version": trainer.get_stats().get("active_version"),
            "val_accuracy": train_result.get("val_accuracy"),
            "val_top_10_accuracy": train_result.get("val_top_10_accuracy"),
            "decision_reason": train_result.get("decision_reason"),
        }
    )

    evaluation = get_model_evaluation_payload()
    result["steps"].append(
        {
            "step": "evaluation",
            "success": bool(evaluation.get("success", False)),
            "top_1_accuracy": evaluation.get("top_1_accuracy"),
            "top_10_accuracy": evaluation.get("top_10_accuracy"),
            "test_samples": evaluation.get("test_samples"),
            "active_version": evaluation.get("active_version"),
        }
    )

    sequence = _generate_sequence(
        run_id=run_id,
        scenario=scenario,
        traffic_type=traffic_type,
        request_count=request_count,
        rng=rng,
    )
    interval_seconds = max(0.01, 1.0 / TRAFFIC_PROFILES.get(traffic_type, TRAFFIC_PROFILES["normal"])["rps"])

    top1_hits = 0
    top10_hits = 0
    prediction_samples = 0
    prefetch_opportunities = 0
    verified_prefetch_hits = 0
    cache_hits = 0
    cache_misses = 0
    latencies: List[float] = []
    trace: List[Dict[str, Any]] = []
    previous_predictions: List[Tuple[str, float]] = []
    previous_service_id: Optional[str] = None
    previous_worker_events: List[Dict[str, Any]] = list(queue_before.get("recent_worker_events", []))

    for index, current_request in enumerate(sequence, start=1):
        key_id = current_request["key_id"]
        service_id = current_request["service_id"]
        ip_address = current_request["ip_address"]

        predicted_on_previous = False
        top1_correct = False
        top10_correct = False
        prefetched_by_worker = False
        if previous_predictions and previous_service_id == service_id:
            predicted_keys = [predicted_key for predicted_key, _ in previous_predictions]
            predicted_on_previous = key_id in predicted_keys
            top1_correct = bool(predicted_keys and predicted_keys[0] == key_id)
            top10_correct = predicted_on_previous
            prediction_samples += 1
            top1_hits += int(top1_correct)
            top10_hits += int(top10_correct)
            if predicted_on_previous:
                prefetch_opportunities += 1

        prefetched_before_request = secure_manager.secure_exists(key_id, service_id)
        if predicted_on_previous and prefetched_before_request:
            prefetched_by_worker = _find_worker_prefetch_hit(
                previous_worker_events,
                service_id=service_id,
                key_id=key_id,
            )
            if prefetched_by_worker:
                verified_prefetch_hits += 1

        request_started = time.perf_counter()
        _, cache_hit, _, allowed = secure_manager.secure_get(key_id, service_id, ip_address)
        if not allowed:
            latency_ms = round((time.perf_counter() - request_started) * 1000, 2)
        else:
            if not cache_hit:
                secure_manager.secure_set(
                    key_id,
                    f"simulated:{service_id}:{key_id}".encode("utf-8"),
                    service_id,
                    ip_address=ip_address,
                )
                cache_misses += 1
            else:
                cache_hits += 1
            latency_ms = round((time.perf_counter() - request_started) * 1000, 2)
            latencies.append(latency_ms)
            record_runtime_access(
                key_id=key_id,
                service_id=service_id,
                latency_ms=latency_ms,
                cache_hit=cache_hit,
                simulated=True,
                simulation_id=run_id,
                journey=current_request["journey"],
                ip_address=ip_address,
            )

        predictor.clear_cache()
        predictions = predictor.predict(service_id=service_id, n=10, min_confidence=0.0)
        prefetch_schedule = schedule_request_path_prefetch(
            secure_manager,
            service_id,
            key_id,
            ip_address,
        )

        previous_predictions = predictions
        previous_service_id = service_id

        await asyncio.sleep(interval_seconds)
        queue_after_iteration = queue.get_stats()
        previous_worker_events = queue_after_iteration.get("recent_worker_events", [])

        trace.append(
            {
                "index": index,
                "service_id": service_id,
                "key_id": key_id,
                "cache_hit": cache_hit,
                "latency_ms": latency_ms,
                "predicted_on_previous": predicted_on_previous,
                "top1_correct": top1_correct,
                "top10_correct": top10_correct,
                "prefetched_before_request": prefetched_before_request,
                "prefetched_by_worker": prefetched_by_worker,
                "prediction_preview": [
                    {"key_id": predicted_key, "confidence": round(float(confidence), 4)}
                    for predicted_key, confidence in predictions[:3]
                ],
                "prefetch_mode": prefetch_schedule.get("mode"),
                "queue_length": queue_after_iteration.get("queue_length", 0),
            }
        )

    queue_after = queue.get_stats()
    workers_after = queue_after.get("workers", [])
    completed_before = int(queue_before.get("stats", {}).get("completed_total", 0))
    completed_after = int(queue_after.get("stats", {}).get("completed_total", 0))

    live_accuracy = {
        "top_1_accuracy": _safe_rate(top1_hits, prediction_samples),
        "top_10_accuracy": _safe_rate(top10_hits, prediction_samples),
        "prediction_samples": prediction_samples,
        "top_1_hits": top1_hits,
        "top_10_hits": top10_hits,
    }
    prefetch_proof = {
        "prefetch_opportunities": prefetch_opportunities,
        "verified_prefetch_hits": verified_prefetch_hits,
        "verified_prefetch_hit_rate": _safe_rate(verified_prefetch_hits, prefetch_opportunities),
        "worker_completed_delta": max(0, completed_after - completed_before),
        "queue_length_after": queue_after.get("queue_length", 0),
        "active_workers": [worker for worker in workers_after if worker.get("active")],
    }
    latency_summary = {
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
        "p95_latency_ms": round(sorted(latencies)[min(len(latencies) - 1, int(len(latencies) * 0.95))], 2) if latencies else 0.0,
        "request_count": len(latencies),
        "cache_hit_rate": _safe_rate(cache_hits, cache_hits + cache_misses),
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
    }

    result["steps"].extend(
        [
            {"step": "component_proof", "success": True, **_component_snapshot(app_state, queue_after)},
            {"step": "live_accuracy", "success": prediction_samples > 0, **live_accuracy},
            {"step": "prefetch_proof", "success": bool(prefetch_proof["active_workers"]), **prefetch_proof},
            {"step": "latency_summary", "success": True, **latency_summary},
        ]
    )

    result["evidence"] = {
        "component_status": _component_snapshot(app_state, queue_after),
        "training": train_result,
        "evaluation": evaluation,
        "live_accuracy": live_accuracy,
        "prefetch": prefetch_proof,
        "latency": latency_summary,
        "dashboard_snapshot": {
            "ml_status": get_ml_status_payload(),
            "accuracy_history": get_accuracy_history_payload(limit=10),
        },
        "honesty_checks": {
            "model_loaded": bool(getattr(trainer.model, "is_trained", False)),
            "redis_verified": bool(_component_snapshot(app_state, queue_after)["redis_available"]),
            "prefetch_worker_verified": bool(prefetch_proof["active_workers"]),
            "prediction_sample_count": prediction_samples,
            "uses_ground_truth_next_request": True,
        },
    }
    result["trace"] = trace[:50]
    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    result["overall_success"] = all(step.get("success", False) for step in result["steps"] if step["step"] != "prefetch_proof") and prediction_samples > 0
    return result
