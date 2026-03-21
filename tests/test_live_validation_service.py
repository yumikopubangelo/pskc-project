from src.api.live_validation_service import (
    _find_worker_prefetch_hit,
    _generate_sequence,
    _resolve_request_count,
)


def test_resolve_request_count_uses_duration_profile_with_reasonable_cap():
    assert _resolve_request_count(num_requests=42, duration_seconds=60, traffic_type="normal") == 42
    assert _resolve_request_count(num_requests=None, duration_seconds=30, traffic_type="normal") >= 20
    assert _resolve_request_count(num_requests=None, duration_seconds=300, traffic_type="overload") <= 200


def test_generate_sequence_isolated_by_run_service_prefix():
    sequence = _generate_sequence(
        run_id="run-12345678",
        scenario="test",
        traffic_type="normal",
        request_count=20,
        rng=__import__("random").Random(7),
    )

    assert len(sequence) == 20
    assert all(item["service_id"].startswith("sim-run-1234") for item in sequence)
    assert all(item["key_id"].startswith("run-12345678:") for item in sequence)


def test_find_worker_prefetch_hit_matches_service_and_key():
    worker_events = [
        {"service_id": "svc-a", "prefetched_keys": ["k-1", "k-2"]},
        {"service_id": "svc-b", "prefetched_keys": ["k-9"]},
    ]

    assert _find_worker_prefetch_hit(worker_events, service_id="svc-a", key_id="k-2") is True
    assert _find_worker_prefetch_hit(worker_events, service_id="svc-a", key_id="k-9") is False


def test_generate_sequence_supports_stable_ids_for_realtime_sessions():
    sequence = _generate_sequence(
        run_id="run-12345678",
        scenario="test",
        traffic_type="normal",
        request_count=12,
        rng=__import__("random").Random(11),
        namespace_keys=False,
        stable_services=True,
    )

    assert len(sequence) == 12
    assert all(item["service_id"].startswith("sim-live-") for item in sequence)
    assert all(not item["key_id"].startswith("run-12345678:") for item in sequence)
