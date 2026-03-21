import random
import time
from collections import Counter, defaultdict, deque

from src.api.live_simulation_service import (
    _cache_origin_key,
    _ingest_worker_events,
    _merge_prediction_sources,
    _resolve_kms_latency_target_ms,
    _session_learning_predictions,
)


def _build_session(*, traffic_type: str, direct_count: int, pskc_count: int):
    now = time.time()
    return {
        "traffic_type": traffic_type,
        "virtual_nodes": 5,
        "_state": {
            "kms_rng": random.Random("seed"),
            "kms_windows": {
                "direct": deque([now - 0.05] * direct_count),
                "pskc": deque([now - 0.05] * pskc_count),
            },
            "adaptive_transitions": defaultdict(lambda: defaultdict(Counter)),
            "adaptive_popularity": defaultdict(Counter),
        },
    }


def test_direct_kms_lane_gets_higher_latency_under_same_profile():
    direct_session = _build_session(traffic_type="overload", direct_count=50, pskc_count=2)
    pskc_session = _build_session(traffic_type="overload", direct_count=50, pskc_count=2)

    direct_latency = _resolve_kms_latency_target_ms(direct_session, lane="direct")
    pskc_latency = _resolve_kms_latency_target_ms(pskc_session, lane="pskc")

    assert direct_latency > pskc_latency


def test_session_learning_predictions_prioritize_observed_transitions():
    session = _build_session(traffic_type="normal", direct_count=0, pskc_count=0)
    state = session["_state"]
    state["adaptive_transitions"]["svc"]["key-a"]["key-b"] = 6
    state["adaptive_transitions"]["svc"]["key-a"]["key-c"] = 2
    state["adaptive_popularity"]["svc"]["key-d"] = 5

    adaptive = _session_learning_predictions(state, service_id="svc", current_key="key-a", n=4)
    merged = _merge_prediction_sources(
        [("key-c", 0.7), ("key-d", 0.6)],
        adaptive,
        n=4,
    )

    assert adaptive[0][0] == "key-b"
    assert merged[0][0] == "key-b"


def test_ingest_worker_events_marks_cache_origin_for_prefetched_keys():
    state = {
        "cache_origins": {},
        "seen_worker_job_ids": set(),
    }
    worker_events = [
        {
            "job_id": "job-1",
            "status": "completed",
            "service_id": "svc",
            "source_key_id": "source-key",
            "timestamp": 123.0,
            "prefetched_keys": ["key-a", "key-b"],
        }
    ]

    _ingest_worker_events(state, worker_events)

    assert state["cache_origins"][_cache_origin_key("svc", "key-a")]["source"] == "worker_prefetch"
    assert state["cache_origins"][_cache_origin_key("svc", "key-a")]["source_key_id"] == "source-key"
    assert "job-1" in state["seen_worker_job_ids"]


def test_ingest_worker_events_is_idempotent_for_same_job_id():
    state = {
        "cache_origins": {
            _cache_origin_key("svc", "key-a"): {
                "source": "request_fetch",
                "source_key_id": "key-a",
                "updated_at": 100.0,
            }
        },
        "seen_worker_job_ids": {"job-1"},
    }
    worker_events = [
        {
            "job_id": "job-1",
            "status": "completed",
            "service_id": "svc",
            "source_key_id": "source-key",
            "timestamp": 123.0,
            "prefetched_keys": ["key-a"],
        }
    ]

    _ingest_worker_events(state, worker_events)

    assert state["cache_origins"][_cache_origin_key("svc", "key-a")]["source"] == "request_fetch"
