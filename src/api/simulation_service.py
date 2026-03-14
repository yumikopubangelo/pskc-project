import copy
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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
    }


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


def _safe_pct(delta: float, baseline: float) -> float:
    if baseline <= 0:
        return 0.0
    return round((delta / baseline) * 100, 1)
