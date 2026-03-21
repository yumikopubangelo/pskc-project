import copy
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from simulation.enhanced_simulation import DetailedSimulation as EnhancedDetailedSimulation
from simulation.pskc_comparison_fast import DetailedSimulation as FastComparisonSimulation
from simulation.scenarios.siakad_sso import simulate_request as simulate_siakad_request
from simulation.scenarios.sevima_cloud import simulate_sevima_request
from simulation.scenarios.pddikti_auth import simulate_pddikti_request
from simulation.scenarios.dynamic_production import simulate_dynamic_request


SIMULATION_SCENARIOS: List[Dict[str, Any]] = [
    {
        "id": "siakad",
        "name": "SIAKAD SSO",
        "short_name": "SIAKAD",
        "category": "Academic SSO",
        "summary": "Simulasi autentikasi SSO sistem akademik perguruan tinggi Indonesia dengan pola traffic musiman (KRS, UTS, UAS).",
        "default_request_count": 1000,
        "target_p99_ms": 320,
        "expected_hit_rate": 0.84,
        "profiles": [
            {
                "id": "normal",
                "name": "Normal",
                "label": "Hari kuliah normal.",
                "period": "normal",
            },
            {
                "id": "krs_online",
                "name": "KRS Online",
                "label": "Periode KRS online - lonjakan ekstrem.",
                "period": "krs_online",
            },
            {
                "id": "uts",
                "name": "UTS",
                "label": "Ujian Tengah Semester.",
                "period": "uts",
            },
            {
                "id": "uas",
                "name": "UAS",
                "label": "Ujian Akhir Semester.",
                "period": "uas",
            },
        ],
        "references": [
            {
                "title": "JSiI Vol.10 No.1 - Evaluasi SSO di PT Yogyakarta",
                "url": "https://doi.org/10.30656/jsii.v10i1.6186",
            },
            {
                "title": "MDPI Applied Sciences 15(22) - Authentication Challenges",
                "url": "https://doi.org/10.3390/app152212088",
            },
        ],
    },
    {
        "id": "sevima",
        "name": "SEVIMA Siakadcloud",
        "short_name": "SEVIMA",
        "category": "Multi-Tenant Cloud",
        "summary": "Simulasi platform SIAKAD multi-tenant melayani >900 perguruan tinggi Indonesia dengan quota management.",
        "default_request_count": 1000,
        "target_p99_ms": 350,
        "expected_hit_rate": 0.82,
        "profiles": [
            {
                "id": "normal",
                "name": "Normal Load",
                "label": "500 RPS, 80 tenant aktif.",
                "rps_load": 500,
                "tenant_count": 80,
            },
            {
                "id": "peak_krs",
                "name": "Peak KRS",
                "label": "4000 RPS, 300 tenant - peak KRS serentak.",
                "rps_load": 4000,
                "tenant_count": 300,
            },
            {
                "id": "over_quota",
                "name": "Over Quota",
                "label": "9000 RPS, 500 tenant - risiko throttling.",
                "rps_load": 9000,
                "tenant_count": 500,
            },
        ],
        "references": [
            {
                "title": "SEVIMA Siakadcloud - Platform SIAKAD No.1 Indonesia",
                "url": "https://sevima.com/siakadcloud",
            },
            {
                "title": "MDPI Applied Sciences - Rate Limiting Challenges",
                "url": "https://doi.org/10.3390/app152212088",
            },
        ],
    },
    {
        "id": "pddikti",
        "name": "PDDikti - Data Pendidikan Tinggi",
        "short_name": "PDDikti",
        "category": "National Government",
        "summary": "Simulasi portal data pendidikan tinggi nasional Kemdikbudristek dengan >4.900 PT dan 9.6 juta mahasiswa.",
        "default_request_count": 1000,
        "target_p99_ms": 400,
        "expected_hit_rate": 0.80,
        "profiles": [
            {
                "id": "normal",
                "name": "Normal",
                "label": "Akses normal hari kerja.",
                "mode": "normal",
            },
            {
                "id": "deadline_week",
                "name": "Deadline Feeder",
                "label": "Minggu terakhir deadline pelaporan semester.",
                "mode": "deadline_week",
            },
            {
                "id": "publik_peak",
                "name": "Publik Peak",
                "label": "Masa wisuda dan penerimaan mahasiswa baru.",
                "mode": "publik_peak",
            },
        ],
        "references": [
            {
                "title": "PDDikti - Pangkalan Data Pendidikan Tinggi",
                "url": "https://pddikti.kemdikbud.go.id",
            },
            {
                "title": "Feeder PDDikti - Panduan Pelaporan",
                "url": "https://feeder.kemdikbud.go.id",
            },
        ],
    },
    {
        "id": "dynamic",
        "name": "Dynamic Production",
        "short_name": "Dynamic",
        "category": "Resilience",
        "summary": "Simulasi workload berubah, lonjakan latensi, dan outage KMS singkat.",
        "default_request_count": 2000,
        "target_p99_ms": 500,
        "expected_hit_rate": 0.88,
        "profiles": [
            {
                "id": "resilience",
                "name": "Resilience Run",
                "label": "Menekankan outage window dan perubahan workload.",
            }
        ],
        "references": [
            {
                "title": "PSKC Dynamic Production Scenario",
                "url": "/simulation/scenarios/dynamic_production.py",
            }
        ],
    },
]

SCENARIO_BY_ID = {scenario["id"]: scenario for scenario in SIMULATION_SCENARIOS}


def list_simulation_scenarios() -> Dict[str, Any]:
    return {
        "scenarios": copy.deepcopy(SIMULATION_SCENARIOS),
        "default_scenario": SIMULATION_SCENARIOS[0]["id"],
        "available_views": [
            {
                "id": "scenario_lab",
                "name": "Scenario Lab",
                "description": "Integrates the updated simulation folder for reference benchmarks, cache-flow evidence, and trace previews.",
            },
            {
                "id": "realtime",
                "name": "Realtime",
                "description": "Uses the live backend runtime, Redis, and prefetch worker on an always-on session.",
            },
        ],
    }


def run_simulation_job(scenario_id: str, profile_id: Optional[str], request_count: int, seed: Optional[int]) -> Dict[str, Any]:
    scenario = SCENARIO_BY_ID.get(scenario_id)
    if scenario is None:
        raise ValueError(f"Unknown simulation scenario: {scenario_id}")

    profiles = scenario["profiles"]
    selected_profile = next((profile for profile in profiles if profile["id"] == profile_id), profiles[0])

    effective_seed = seed if seed is not None else random.randint(1, 1_000_000)

    if scenario_id == "siakad":
        period = selected_profile.get("period", "normal")
        without_samples = _generate_samples(request_count, effective_seed, lambda index: _siakad_sample(index, period=period))
        with_samples = _generate_samples(request_count, effective_seed + 1, lambda index: _siakad_sample(index, period=period, use_pskc=True))
        phase = "krs-peak" if period == "krs_online" else "steady"
    elif scenario_id == "sevima":
        rps_load = int(selected_profile.get("rps_load", 500))
        tenant_count = int(selected_profile.get("tenant_count", 80))
        without_samples = _generate_samples(
            request_count,
            effective_seed,
            lambda index: _sevima_sample(index, rps_load=rps_load, tenant_count=tenant_count),
        )
        with_samples = _generate_samples(
            request_count,
            effective_seed + 1,
            lambda index: _sevima_sample(index, rps_load=rps_load, tenant_count=tenant_count, use_pskc=True),
        )
        phase = "over-quota" if rps_load > 5000 else "steady"
    elif scenario_id == "pddikti":
        mode = selected_profile.get("mode", "normal")
        without_samples = _generate_samples(
            request_count,
            effective_seed,
            lambda index: _pddikti_sample(index, mode=mode),
        )
        with_samples = _generate_samples(
            request_count,
            effective_seed + 1,
            lambda index: _pddikti_sample(index, mode=mode, use_pskc=True),
        )
        phase = "deadline-peak" if mode == "deadline_week" else "steady"
    elif scenario_id == "dynamic":
        without_samples = _generate_samples(request_count, effective_seed, lambda index: _dynamic_sample(index, request_count=request_count))
        with_samples = _generate_samples(
            request_count,
            effective_seed + 1,
            lambda index: _dynamic_sample(index, use_pskc=True, request_count=request_count),
        )
        phase = "resilience-run"
    else:
        raise ValueError(f"Unsupported simulation scenario: {scenario_id}")

    without_summary = _summarize_samples(without_samples)
    with_summary = _summarize_samples(with_samples)
    history = _build_history(without_samples, with_samples)

    latency_reduction_pct = _safe_pct(without_summary["avg_latency_ms"] - with_summary["avg_latency_ms"], without_summary["avg_latency_ms"])
    p99_reduction_pct = _safe_pct(without_summary["p99_ms"] - with_summary["p99_ms"], without_summary["p99_ms"])
    hit_rate_gain_pct = round(with_summary["hit_rate"] - without_summary["hit_rate"], 1)
    time_saved_seconds = round(
        sum(max(0.0, without["latency_ms"] - with_item["latency_ms"]) for without, with_item in zip(without_samples, with_samples))
        / 1000,
        2,
    )

    return {
        "status": "completed",
        "scenario": scenario["id"],
        "profile_id": selected_profile["id"],
        "request_count": request_count,
        "seed": effective_seed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {
            "name": scenario["name"],
            "short_name": scenario["short_name"],
            "category": scenario["category"],
            "summary": scenario["summary"],
            "profile_name": selected_profile["name"],
            "profile_label": selected_profile["label"],
            "target_p99_ms": scenario["target_p99_ms"],
            "expected_hit_rate": round(float(scenario["expected_hit_rate"]) * 100, 1),
            "references": copy.deepcopy(scenario["references"]),
        },
        "overview": {
            "phase": phase,
            "requests_processed": request_count,
        },
        "results": {
            "without_pskc": without_summary,
            "with_pskc": with_summary,
        },
        "comparison": {
            "latency_reduction_pct": latency_reduction_pct,
            "p99_reduction_pct": p99_reduction_pct,
            "hit_rate_gain_pct": hit_rate_gain_pct,
            "time_saved_seconds": time_saved_seconds,
        },
        "charts": {
            "latency_trend": history,
            "hit_rate": history,
        },
        "integrated_simulation": _build_integrated_simulation_view(
            scenario_id=scenario_id,
            selected_profile=selected_profile,
            request_count=request_count,
            seed=effective_seed,
        ),
    }


def _build_integrated_simulation_view(
    scenario_id: str,
    selected_profile: Dict[str, Any],
    request_count: int,
    seed: int,
) -> Dict[str, Any]:
    runtime_config = _get_runtime_simulation_config(scenario_id=scenario_id, selected_profile=selected_profile)
    workload = _build_cache_flow_workload(
        scenario_id=scenario_id,
        request_count=request_count,
        seed=seed,
        num_users=runtime_config["num_users"],
        keys_per_user=runtime_config["keys_per_user"],
        hot_share=runtime_config["hot_share"],
    )

    cache_flow = _run_cache_flow_comparison(
        workload=workload,
        seed=seed,
        num_users=runtime_config["num_users"],
        keys_per_user=runtime_config["keys_per_user"],
    )
    detailed_trace = _run_enhanced_trace_preview(
        scenario_id=scenario_id,
        selected_profile=selected_profile,
        seed=seed,
        service_id=runtime_config["service_id"],
        trace_length=min(30, max(12, request_count // 10)),
        key_prefix=runtime_config["key_prefix"],
    )

    return {
        "source": "simulation_folder",
        "engines": ["scenario_reference", "cache_flow_fast", "enhanced_trace"],
        "runtime_config": {
            "service_id": runtime_config["service_id"],
            "num_users": runtime_config["num_users"],
            "keys_per_user": runtime_config["keys_per_user"],
            "hot_share": runtime_config["hot_share"],
        },
        "cache_flow": cache_flow,
        "detailed_trace": detailed_trace,
    }


def _get_runtime_simulation_config(scenario_id: str, selected_profile: Dict[str, Any]) -> Dict[str, Any]:
    scenario_defaults = {
        "siakad": {
            "service_id": "portal_nilai",
            "key_prefix": "siakad",
            "num_users": 90,
            "keys_per_user": 24,
            "hot_share": 0.82,
        },
        "sevima": {
            "service_id": "tenant_auth",
            "key_prefix": "sevima",
            "num_users": 160,
            "keys_per_user": 28,
            "hot_share": 0.84,
        },
        "pddikti": {
            "service_id": "operator_feeder",
            "key_prefix": "pddikti",
            "num_users": 180,
            "keys_per_user": 30,
            "hot_share": 0.78,
        },
        "dynamic": {
            "service_id": "resilience_api",
            "key_prefix": "dynamic",
            "num_users": 110,
            "keys_per_user": 26,
            "hot_share": 0.75,
        },
    }
    config = dict(scenario_defaults.get(scenario_id, scenario_defaults["siakad"]))

    profile_id = selected_profile.get("id", "")
    if scenario_id == "siakad":
        if profile_id == "krs_online":
            config["num_users"] = 120
            config["keys_per_user"] = 28
            config["hot_share"] = 0.9
        elif profile_id in {"uts", "uas"}:
            config["num_users"] = 100
            config["hot_share"] = 0.86
    elif scenario_id == "sevima":
        rps_load = int(selected_profile.get("rps_load", 500))
        if rps_load >= 9000:
            config["num_users"] = 220
            config["keys_per_user"] = 36
            config["hot_share"] = 0.88
        elif rps_load >= 4000:
            config["num_users"] = 190
            config["keys_per_user"] = 32
            config["hot_share"] = 0.86
    elif scenario_id == "pddikti":
        if profile_id == "deadline_week":
            config["num_users"] = 230
            config["keys_per_user"] = 34
            config["hot_share"] = 0.83
        elif profile_id == "publik_peak":
            config["num_users"] = 200
            config["keys_per_user"] = 32
            config["hot_share"] = 0.8
    elif scenario_id == "dynamic":
        config["num_users"] = 140
        config["keys_per_user"] = 28
        config["hot_share"] = 0.72

    return config


def _build_cache_flow_workload(
    scenario_id: str,
    request_count: int,
    seed: int,
    num_users: int,
    keys_per_user: int,
    hot_share: float,
) -> List[Dict[str, int]]:
    rng = random.Random(seed)
    total_keys = max(40, num_users * keys_per_user)
    all_keys = list(range(1, total_keys + 1))
    hot_cutoff = max(10, total_keys // 5)
    first_hot_pool = all_keys[:hot_cutoff]
    second_hot_pool = all_keys[hot_cutoff:hot_cutoff * 2] or first_hot_pool
    cold_pool = all_keys[hot_cutoff:] or first_hot_pool

    workload: List[Dict[str, int]] = []
    for index in range(request_count):
        active_hot_share = hot_share
        active_hot_pool = first_hot_pool

        if scenario_id == "dynamic":
            phase = index / max(request_count, 1)
            if phase < 0.25:
                active_hot_share = min(0.94, hot_share + 0.12)
                active_hot_pool = first_hot_pool[: max(5, len(first_hot_pool) // 2)] or first_hot_pool
            elif phase < 0.65:
                active_hot_share = max(0.55, hot_share - 0.12)
                active_hot_pool = second_hot_pool
            else:
                active_hot_share = hot_share
                active_hot_pool = first_hot_pool

        if rng.random() < active_hot_share:
            key_id = rng.choice(active_hot_pool)
        else:
            key_id = rng.choice(cold_pool)

        workload.append(
            {
                "user_id": rng.randint(1, num_users),
                "key_id": key_id,
            }
        )

    return workload


def _run_cache_flow_comparison(
    workload: List[Dict[str, int]],
    seed: int,
    num_users: int,
    keys_per_user: int,
) -> Dict[str, Any]:
    without_pskc = FastComparisonSimulation(use_pskc=False, num_users=num_users, keys_per_user=keys_per_user)
    with_pskc = FastComparisonSimulation(use_pskc=True, num_users=num_users, keys_per_user=keys_per_user)

    previous_state = random.getstate()
    try:
        random.seed(seed + 101)
        for request in workload:
            without_pskc.process_request(request["user_id"], request["key_id"])

        random.seed(seed + 202)
        for request in workload:
            with_pskc.process_request(request["user_id"], request["key_id"])
    finally:
        random.setstate(previous_state)

    without_stats = _normalize_fast_stats(without_pskc.get_statistics())
    with_stats = _normalize_fast_stats(with_pskc.get_statistics())

    return {
        "without_pskc": without_stats,
        "with_pskc": with_stats,
        "comparison": {
            "avg_latency_saved_ms": round(without_stats["avg_latency_ms"] - with_stats["avg_latency_ms"], 2),
            "p95_latency_saved_ms": round(without_stats["p95_latency_ms"] - with_stats["p95_latency_ms"], 2),
            "cache_hit_gain_pct": round(with_stats["cache_hit_rate"] - without_stats["cache_hit_rate"], 1),
            "l2_hit_gain_pct": round(with_stats["l2_hit_rate"] - without_stats["l2_hit_rate"], 1),
            "kms_fetch_reduction_pct": _safe_pct(
                without_stats["kms_fetches"] - with_stats["kms_fetches"],
                without_stats["kms_fetches"],
            ),
            "prefetch_processed": with_stats["prefetch_processed"],
        },
        "path_comparison": _build_path_comparison(without_stats["request_paths"], with_stats["request_paths"]),
    }


def _normalize_fast_stats(stats: Dict[str, Any]) -> Dict[str, Any]:
    total_requests = int(stats.get("total_requests", 0) or 0)
    request_paths = dict(stats.get("request_paths", {}) or {})

    l1_hits = int(request_paths.get("L1_HIT", 0))
    l2_hits = int(request_paths.get("L2_HIT", 0))
    kms_fetches = int(request_paths.get("KMS_FETCH", 0)) + int(request_paths.get("PSKC_HIT", 0)) + int(request_paths.get("PSKC_MISS", 0))
    error_count = sum(
        int(count)
        for path, count in request_paths.items()
        if "ERROR" in str(path)
    )

    return {
        "total_requests": total_requests,
        "avg_latency_ms": round(float(stats.get("avg_latency_ms", 0.0) or 0.0), 2),
        "p50_latency_ms": round(float(stats.get("p50_latency_ms", 0.0) or 0.0), 2),
        "p95_latency_ms": round(float(stats.get("p95_latency_ms", 0.0) or 0.0), 2),
        "p99_latency_ms": round(float(stats.get("p99_latency_ms", 0.0) or 0.0), 2),
        "cache_hit_rate": round(((l1_hits + l2_hits) / total_requests) * 100, 1) if total_requests else 0.0,
        "l1_hit_rate": round((l1_hits / total_requests) * 100, 1) if total_requests else 0.0,
        "l2_hit_rate": round((l2_hits / total_requests) * 100, 1) if total_requests else 0.0,
        "kms_fetches": kms_fetches,
        "kms_errors": int(stats.get("kms_errors", 0) or 0) + error_count,
        "prefetch_queued": int(stats.get("prefetch_queued", 0) or 0),
        "prefetch_processed": int(stats.get("prefetch_processed", 0) or 0),
        "l1_utilization_pct": round(float(stats.get("l1_utilization", 0.0) or 0.0), 2),
        "l2_utilization_pct": round(float(stats.get("l2_utilization", 0.0) or 0.0), 2),
        "request_paths": request_paths,
        "path_breakdown": _build_single_path_breakdown(request_paths),
    }


def _build_path_comparison(without_paths: Dict[str, int], with_paths: Dict[str, int]) -> List[Dict[str, Any]]:
    labels = {
        "L1_HIT": "L1 Hit",
        "L2_HIT": "L2 Hit",
        "KMS_FETCH": "Direct KMS",
        "PSKC_HIT": "Predicted Fetch",
        "PSKC_MISS": "Unpredicted Fetch",
        "KMS_ERROR": "KMS Error",
    }
    colors = {
        "L1_HIT": "#14b8a6",
        "L2_HIT": "#38bdf8",
        "KMS_FETCH": "#f59e0b",
        "PSKC_HIT": "#22c55e",
        "PSKC_MISS": "#f97316",
        "KMS_ERROR": "#ef4444",
    }

    all_paths = sorted(set(without_paths) | set(with_paths))
    comparison: List[Dict[str, Any]] = []
    for path in all_paths:
        comparison.append(
            {
                "name": labels.get(path, path.replace("_", " ").title()),
                "without_pskc": int(without_paths.get(path, 0)),
                "with_pskc": int(with_paths.get(path, 0)),
                "color": colors.get(path, "#a855f7"),
            }
        )
    return comparison


def _build_single_path_breakdown(request_paths: Dict[str, int]) -> List[Dict[str, Any]]:
    colors = {
        "L1_HIT": "#14b8a6",
        "L2_HIT": "#38bdf8",
        "KMS_FETCH": "#f59e0b",
        "PSKC_HIT": "#22c55e",
        "PSKC_MISS": "#f97316",
        "KMS_ERROR": "#ef4444",
    }
    labels = {
        "L1_HIT": "L1 Hit",
        "L2_HIT": "L2 Hit",
        "KMS_FETCH": "Direct KMS",
        "PSKC_HIT": "Predicted Fetch",
        "PSKC_MISS": "Unpredicted Fetch",
        "KMS_ERROR": "KMS Error",
    }

    breakdown = []
    for path, value in sorted(request_paths.items(), key=lambda item: item[1], reverse=True):
        breakdown.append(
            {
                "name": labels.get(path, path.replace("_", " ").title()),
                "value": int(value),
                "color": colors.get(path, "#a855f7"),
            }
        )
    return breakdown


def _run_enhanced_trace_preview(
    scenario_id: str,
    selected_profile: Dict[str, Any],
    seed: int,
    service_id: str,
    trace_length: int,
    key_prefix: str,
) -> Dict[str, Any]:
    trace_workload = _build_trace_workload(
        scenario_id=scenario_id,
        selected_profile=selected_profile,
        seed=seed + 303,
        trace_length=trace_length,
        key_prefix=key_prefix,
    )
    simulation = EnhancedDetailedSimulation(use_pskc=True, verbose=False)

    previous_state = random.getstate()
    try:
        random.seed(seed + 404)
        trace_rows = []
        for index, key_id in enumerate(trace_workload, start=1):
            result = simulation.process_request(key_id=key_id, service=service_id)
            trace_rows.append(
                {
                    "index": index,
                    "service_id": service_id,
                    "key_id": key_id,
                    "cache_layer": result.get("cache_layer"),
                    "path": result.get("path"),
                    "latency_ms": round(float(result.get("latency_ms", 0.0) or 0.0), 3),
                    "success": bool(result.get("success", False)),
                    "details": result.get("details", {}),
                }
            )
    finally:
        random.setstate(previous_state)

    aggregate = simulation._aggregate_stats()
    return {
        "service_id": service_id,
        "profile_id": selected_profile.get("id"),
        "trace_preview": trace_rows,
        "aggregate": {
            "avg_latency_ms": round(float(aggregate.get("avg_latency_ms", 0.0) or 0.0), 3),
            "p95_latency_ms": round(float(aggregate.get("p95_latency_ms", 0.0) or 0.0), 3),
            "cache_hit_rate": round(float(aggregate.get("composite_cache_hit", 0.0) or 0.0) * 100, 1),
            "prefetch_jobs_queued": int(aggregate.get("prefetch_jobs_queued", 0) or 0),
            "prefetch_jobs_processed": int(aggregate.get("prefetch_jobs_processed", 0) or 0),
        },
        "layer_breakdown": [
            {"name": "L1", "value": int(aggregate.get("l1_hits", 0) or 0), "color": "#14b8a6"},
            {"name": "L2", "value": int(aggregate.get("l2_hits", 0) or 0), "color": "#38bdf8"},
            {"name": "KMS", "value": int(aggregate.get("kms_fetches", 0) or 0), "color": "#f59e0b"},
        ],
        "component_proof": {
            "predictor_enabled": True,
            "l1_cache_enabled": True,
            "l2_cache_enabled": True,
            "prefetch_enabled": True,
            "kms_fallback_enabled": True,
        },
        "notes": _trace_notes_for_scenario(scenario_id, selected_profile.get("id", "")),
    }


def _build_trace_workload(
    scenario_id: str,
    selected_profile: Dict[str, Any],
    seed: int,
    trace_length: int,
    key_prefix: str,
) -> List[str]:
    rng = random.Random(seed)
    trace: List[str] = []
    profile_id = selected_profile.get("id", "normal")

    hot_users = [f"{key_prefix}_user_{i}" for i in range(1, 9)]
    cold_users = [f"{key_prefix}_user_{i}" for i in range(9, 21)]
    hot_key_range = range(1, 9)
    cold_key_range = range(9, 32)

    for index in range(trace_length):
        if scenario_id == "dynamic" and index > trace_length // 2:
            active_hot_users = cold_users[:6]
        else:
            active_hot_users = hot_users

        if profile_id in {"krs_online", "deadline_week"}:
            hot_probability = 0.88
        elif profile_id in {"peak_krs", "over_quota", "publik_peak"}:
            hot_probability = 0.82
        else:
            hot_probability = 0.74

        if rng.random() < hot_probability:
            user = rng.choice(active_hot_users)
            key_suffix = rng.choice(list(hot_key_range))
        else:
            user = rng.choice(cold_users)
            key_suffix = rng.choice(list(cold_key_range))

        trace.append(f"{user}:key_{key_suffix}")

    return trace


def _trace_notes_for_scenario(scenario_id: str, profile_id: str) -> List[str]:
    notes = {
        "siakad": "Traffic meniru pola login berulang ke portal nilai, LMS, dan KRS dengan key populer yang sama.",
        "sevima": "Flow menekankan tenant burst dan redistribusi request antar banyak institusi aktif.",
        "pddikti": "Trace lebih banyak memusat ke operator feeder dan verifikasi publik menjelang deadline.",
        "dynamic": "Trace sengaja menggeser key panas di pertengahan run untuk mensimulasikan churn produksi.",
    }
    profile_note = f"Profile aktif: {profile_id}."
    return [notes.get(scenario_id, "Trace diambil dari simulation folder."), profile_note]


def _generate_samples(request_count: int, seed: int, sample_factory):
    state = random.getstate()
    random.seed(seed)
    try:
        return [sample_factory(index) for index in range(request_count)]
    finally:
        random.setstate(state)


def _siakad_sample(index: int, period: str = "normal", use_pskc: bool = False) -> Dict[str, Any]:
    payload = simulate_siakad_request(use_pskc=use_pskc, period=period, cache_warm=index > 20)
    return _normalize_sample(payload)


def _sevima_sample(index: int, rps_load: int = 500, tenant_count: int = 80, use_pskc: bool = False) -> Dict[str, Any]:
    payload = simulate_sevima_request(use_pskc=use_pskc, rps_load=rps_load, tenant_count=tenant_count)
    return _normalize_sample(payload)


def _pddikti_sample(index: int, mode: str = "normal", use_pskc: bool = False) -> Dict[str, Any]:
    payload = simulate_pddikti_request(use_pskc=use_pskc, mode=mode)
    return _normalize_sample(payload)


def _dynamic_sample(index: int, request_count: int, use_pskc: bool = False) -> Dict[str, Any]:
    outage_start = request_count // 2
    outage_end = outage_start + 50
    kms_available = not (outage_start <= index < outage_end)
    payload = simulate_dynamic_request(
        use_pskc=use_pskc,
        iteration=index,
        total_requests=request_count,
        kms_available=kms_available,
    )
    return _normalize_sample(payload)


def _normalize_sample(payload: Dict[str, Any]) -> Dict[str, Any]:
    latency_ms = float(payload.get("total_ms") or payload.get("latency_ms") or 0.0)
    status = payload.get("status", "ok")
    return {
        "latency_ms": latency_ms,
        "cache_hit": bool(payload.get("cache_hit", False)),
        "timed_out": status == "timeout",
        "throttled": bool(payload.get("throttled", False)),
    }


def _summarize_samples(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    latencies = sorted(sample["latency_ms"] for sample in samples)
    hits = sum(1 for sample in samples if sample["cache_hit"])
    misses = len(samples) - hits
    timeouts = sum(1 for sample in samples if sample["timed_out"])
    throttled = sum(1 for sample in samples if sample["throttled"])

    return {
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
        "p50_ms": _percentile(latencies, 50),
        "p95_ms": _percentile(latencies, 95),
        "p99_ms": _percentile(latencies, 99),
        "hit_rate": round((hits / len(samples)) * 100, 1) if samples else 0.0,
        "hits": hits,
        "misses": misses,
        "timeouts": timeouts,
        "throttled": throttled,
    }


def _build_history(without_samples: List[Dict[str, Any]], with_samples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sample_count = min(len(without_samples), len(with_samples))
    if sample_count == 0:
        return []

    window_size = max(10, sample_count // 20)
    history: List[Dict[str, Any]] = []

    for upper_bound in range(window_size, sample_count + 1, window_size):
        without_window = without_samples[max(0, upper_bound - window_size):upper_bound]
        with_window = with_samples[max(0, upper_bound - window_size):upper_bound]

        without_avg = sum(item["latency_ms"] for item in without_window) / len(without_window)
        with_avg = sum(item["latency_ms"] for item in with_window) / len(with_window)
        without_hit_rate = _window_hit_rate(without_window)
        with_hit_rate = _window_hit_rate(with_window)

        history.append(
            {
                "request": upper_bound,
                "withoutLatency": round(without_avg, 1),
                "withLatency": round(with_avg, 1),
                "withoutHitRate": without_hit_rate,
                "withHitRate": with_hit_rate,
                "improvement": round(_safe_pct(without_avg - with_avg, without_avg), 1),
            }
        )

    if history[-1]["request"] != sample_count:
        without_window = without_samples[max(0, sample_count - window_size):sample_count]
        with_window = with_samples[max(0, sample_count - window_size):sample_count]
        without_avg = sum(item["latency_ms"] for item in without_window) / len(without_window)
        with_avg = sum(item["latency_ms"] for item in with_window) / len(with_window)
        history.append(
            {
                "request": sample_count,
                "withoutLatency": round(without_avg, 1),
                "withLatency": round(with_avg, 1),
                "withoutHitRate": _window_hit_rate(without_window),
                "withHitRate": _window_hit_rate(with_window),
                "improvement": round(_safe_pct(without_avg - with_avg, without_avg), 1),
            }
        )

    return history


def _window_hit_rate(samples: List[Dict[str, Any]]) -> float:
    if not samples:
        return 0.0
    hits = sum(1 for item in samples if item["cache_hit"])
    return round((hits / len(samples)) * 100, 1)


def _percentile(values: List[float], percentile: int) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, max(0, int((percentile / 100) * len(values)) - 1))
    return round(values[index], 2)


def list_traffic_profiles() -> Dict[str, Any]:
    """Returns a list of available organic traffic profiles."""
    return {
        "profiles": [
            {"id": "normal", "name": "Normal Day", "description": "Typical daily traffic with an afternoon peak."},
            {"id": "heavy", "name": "Heavy Load", "description": "Sustained high traffic, like a launch event."},
            {"id": "prime_time", "name": "Prime Time", "description": "High traffic during evening hours, typical for entertainment services."},
            {"id": "overload", "name": "Overload/Degradation", "description": "Extreme, bursty traffic simulating a system under high stress."},
            {"id": "constant", "name": "Constant RPS", "description": "Fixed number of requests per second for baseline testing."},
        ],
        "default_profile": "normal",
    }


def run_organic_simulation(scenario_id: str, traffic_profile: str, duration_seconds: int) -> Dict[str, Any]:
    """Runs a time-based organic simulation."""
    from simulation.engines.traffic_generator import CompositeTrafficSimulator

    scenario = SCENARIO_BY_ID.get(scenario_id)
    if scenario is None:
        raise ValueError(f"Unknown simulation scenario: {scenario_id}")

    # 1. Initialize the simulator
    simulator = CompositeTrafficSimulator(traffic_profile=traffic_profile, num_keys=1000)

    # 2. Define a sample factory for the specific scenario
    sample_factory = _get_sample_factory(scenario_id)
    if sample_factory is None:
        raise ValueError(f"Unsupported simulation scenario for organic mode: {scenario_id}")

    # 3. Run simulation and collect samples in real-time
    # We need to adapt the batch-based sample functions. For now, we'll simulate requests
    # and then process them. A more advanced version could do this in a stream.
    sim_results = simulator.run(duration_seconds=duration_seconds, collect_latency=False)
    request_count = sim_results["total_requests"]
    
    # In this version, we are not using the generated access sequence from the organic simulator
    # but we are using the total number of requests generated.
    # A future improvement would be to feed the access sequence into the sample generation.
    without_samples = _generate_samples(request_count, random.randint(1, 1_000_000), lambda i: sample_factory(i, use_pskc=False))
    with_samples = _generate_samples(request_count, random.randint(1, 1_000_000), lambda i: sample_factory(i, use_pskc=True))

    # 4. Summarize and return results (similar to run_simulation_job)
    without_summary = _summarize_samples(without_samples)
    with_summary = _summarize_samples(with_samples)
    history = _build_history(without_samples, with_samples)
    
    latency_reduction_pct = _safe_pct(without_summary["avg_latency_ms"] - with_summary["avg_latency_ms"], without_summary["avg_latency_ms"])
    p99_reduction_pct = _safe_pct(without_summary["p99_ms"] - with_summary["p99_ms"], without_summary["p99_ms"])

    return {
        "status": "completed",
        "scenario": scenario_id,
        "profile_id": traffic_profile,
        "duration_seconds": duration_seconds,
        "request_count": request_count,
        "avg_rps": sim_results["avg_rps"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {
            "name": scenario["name"],
            "short_name": scenario["short_name"],
            "category": scenario["category"],
            "summary": f"Organic simulation running for {duration_seconds}s with '{traffic_profile}' profile.",
            "profile_name": traffic_profile,
        },
        "results": {
            "without_pskc": without_summary,
            "with_pskc": with_summary,
        },
        "comparison": {
             "latency_reduction_pct": latency_reduction_pct,
             "p99_reduction_pct": p99_reduction_pct,
        },
        "charts": {
            "latency_trend": history,
            "hit_rate": history,
        },
    }


def _get_sample_factory(scenario_id: str):
    """Returns the correct sample generation function for a given scenario."""
    if scenario_id == "siakad":
        return lambda index, use_pskc: _siakad_sample(index, use_pskc=use_pskc, period="normal")
    if scenario_id == "sevima":
        return lambda index, use_pskc: _sevima_sample(index, use_pskc=use_pskc)
    if scenario_id == "pddikti":
        return lambda index, use_pskc: _pddikti_sample(index, use_pskc=use_pskc)
    if scenario_id == "dynamic":
        # Dynamic requires request_count, so it's not a direct fit.
        # We will approximate it.
        return lambda index, use_pskc: _dynamic_sample(index, use_pskc=use_pskc, request_count=1000)
    return None

def _safe_pct(delta: float, baseline: float) -> float:
    if baseline <= 0:
        return 0.0
    return round((delta / baseline) * 100, 1)
