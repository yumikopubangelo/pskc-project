from __future__ import annotations

import argparse
import base64
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.prefetch.queue import PrefetchQueue


SECURITY_HEADERS = (
    "strict-transport-security",
    "content-security-policy",
    "x-content-type-options",
    "x-frame-options",
    "x-request-id",
)


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _require_security_headers(response: httpx.Response, context: str) -> None:
    missing = [header for header in SECURITY_HEADERS if header not in response.headers]
    _expect(
        not missing,
        f"{context} missing security headers: {', '.join(missing)}",
    )


def _request_json(
    client: httpx.Client,
    method: str,
    path: str,
    expected_status: int = 200,
    **kwargs: Any,
) -> Dict[str, Any]:
    response = client.request(method, path, **kwargs)
    _require_security_headers(response, f"{method} {path}")
    _expect(
        response.status_code == expected_status,
        f"{method} {path} returned {response.status_code}: {response.text}",
    )
    return response.json()


def _wait_for_health(client: httpx.Client, timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    last_error = "no response"
    while time.time() < deadline:
        try:
            payload = _request_json(client, "GET", "/health")
            _expect(payload.get("status") == "healthy", f"/health unexpected payload: {payload}")
            return
        except Exception as exc:  # pragma: no cover - exercised by CI runtime
            last_error = str(exc)
            time.sleep(2)
    raise RuntimeError(f"Backend did not become healthy within {timeout_seconds}s: {last_error}")


def _wait_for_prefetch_completion(
    client: httpx.Client,
    initial_completed_total: int,
    timeout_seconds: int,
) -> Dict[str, Any]:
    deadline = time.time() + timeout_seconds
    latest_payload: Dict[str, Any] = {}
    while time.time() < deadline:
        latest_payload = _request_json(client, "GET", "/metrics/prefetch")
        stats = latest_payload.get("stats") or {}
        if int(stats.get("completed_total", 0)) >= initial_completed_total + 1:
            return latest_payload
        if int(latest_payload.get("dlq_length", 0)) > 0:
            raise RuntimeError(f"Prefetch job moved to DLQ: {latest_payload}")
        time.sleep(1)
    raise RuntimeError(f"Prefetch worker did not complete in time. Latest stats: {latest_payload}")


def run_smoke(args: argparse.Namespace) -> None:
    run_id = uuid.uuid4().hex[:8]
    service_id = f"smoke-{run_id}"
    stored_key_id = f"stored-{run_id}"
    fetched_key_id = f"fetched-{run_id}"
    prefetched_key_id = f"prefetched-{run_id}"

    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=args.http_timeout_seconds) as client:
        print(f"[smoke] waiting for backend at {args.base_url}")
        _wait_for_health(client, timeout_seconds=args.startup_timeout_seconds)

        health_payload = _request_json(client, "GET", "/health")
        print(f"[smoke] health ok: {health_payload['status']}")

        invalid_store_response = client.post(
            "/keys/store",
            json={"key_id": f"invalid-{run_id}", "key_data": "***", "service_id": service_id},
        )
        _require_security_headers(invalid_store_response, "POST /keys/store invalid")
        _expect(
            invalid_store_response.status_code == 400,
            f"Invalid base64 request should return 400, got {invalid_store_response.status_code}",
        )

        invalid_identifier_response = client.post(
            "/keys/access",
            json={"key_id": "../escape", "service_id": service_id, "verify": True},
        )
        _require_security_headers(invalid_identifier_response, "POST /keys/access invalid identifier")
        _expect(
            invalid_identifier_response.status_code == 422,
            f"Unsafe identifier should return 422, got {invalid_identifier_response.status_code}",
        )

        store_payload = {
            "key_id": stored_key_id,
            "key_data": base64.b64encode(f"stored-secret-{run_id}".encode("utf-8")).decode("ascii"),
            "service_id": service_id,
            "ttl": 120,
        }
        store_result = _request_json(client, "POST", "/keys/store", json=store_payload)
        _expect(store_result.get("success") is True, f"Store key failed: {store_result}")
        print(f"[smoke] stored key {stored_key_id}")

        stored_access = _request_json(
            client,
            "POST",
            "/keys/access",
            json={"key_id": stored_key_id, "service_id": service_id, "verify": True},
        )
        _expect(stored_access.get("cache_hit") is True, f"Stored key should be a cache hit: {stored_access}")

        fetched_access_miss = _request_json(
            client,
            "POST",
            "/keys/access",
            json={"key_id": fetched_key_id, "service_id": service_id, "verify": True},
        )
        _expect(
            fetched_access_miss.get("cache_hit") is False,
            f"First access should miss and fetch upstream: {fetched_access_miss}",
        )

        fetched_access_hit = _request_json(
            client,
            "POST",
            "/keys/access",
            json={"key_id": fetched_key_id, "service_id": service_id, "verify": True},
        )
        _expect(
            fetched_access_hit.get("cache_hit") is True,
            f"Second access should hit cache: {fetched_access_hit}",
        )
        print(f"[smoke] request path store/miss/hit validated for service {service_id}")

        metrics_payload = _request_json(client, "GET", "/metrics")
        _expect(metrics_payload.get("total_requests", 0) >= 3, f"Unexpected metrics payload: {metrics_payload}")
        _expect(metrics_payload.get("cache_hits", 0) >= 2, f"Expected cache hits in metrics: {metrics_payload}")
        _expect(metrics_payload.get("cache_misses", 0) >= 1, f"Expected cache miss in metrics: {metrics_payload}")

        cache_stats_payload = _request_json(client, "GET", "/cache/stats")
        _expect(cache_stats_payload.get("size", 0) >= 2, f"Unexpected cache stats: {cache_stats_payload}")

        cache_keys_payload = _request_json(client, "GET", "/cache/keys")
        _expect(
            any(key.endswith(f":{stored_key_id}") for key in cache_keys_payload.get("keys", [])),
            f"Stored key missing from cache listing: {cache_keys_payload}",
        )

        ml_status_payload = _request_json(client, "GET", "/ml/status")
        _expect("prefetch_queue" in ml_status_payload, f"ML status missing prefetch queue stats: {ml_status_payload}")
        _expect(
            bool((ml_status_payload.get("prefetch_queue") or {}).get("available")),
            f"Prefetch queue should be available in Docker smoke test: {ml_status_payload}",
        )
        _request_json(client, "GET", "/ml/predictions?n=5")

        simulation_payload = _request_json(
            client,
            "POST",
            "/simulation/run",
            json={
                "scenario": "spotify",
                "request_count": 50,
                "duration_seconds": 60,
                "traffic_rate": 100,
                "seed": 123,
            },
        )
        simulation_id = simulation_payload["simulation_id"]
        simulation_result_payload = _request_json(client, "GET", f"/simulation/results/{simulation_id}")
        _expect(
            simulation_result_payload.get("status") == "completed",
            f"Simulation did not complete: {simulation_result_payload}",
        )

        prefetch_metrics_before = _request_json(client, "GET", "/metrics/prefetch")
        initial_completed_total = int((prefetch_metrics_before.get("stats") or {}).get("completed_total", 0))

        queue = PrefetchQueue(redis_url=args.redis_url, queue_key=args.prefetch_queue_key)
        try:
            enqueue_success = queue.enqueue(
                {
                    "job_id": f"smoke-{run_id}",
                    "service_id": service_id,
                    "source_key_id": fetched_key_id,
                    "ip_address": "",
                    "candidates": [{"key_id": prefetched_key_id, "priority": 0.99}],
                    "enqueued_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            _expect(enqueue_success, "Failed to enqueue prefetch smoke job")
        finally:
            queue.close()

        prefetch_metrics_after = _wait_for_prefetch_completion(
            client,
            initial_completed_total=initial_completed_total,
            timeout_seconds=args.worker_timeout_seconds,
        )
        _expect(
            int((prefetch_metrics_after.get("stats") or {}).get("completed_total", 0)) >= initial_completed_total + 1,
            f"Prefetch completion not reflected in metrics: {prefetch_metrics_after}",
        )

        prefetched_access = _request_json(
            client,
            "POST",
            "/keys/access",
            json={"key_id": prefetched_key_id, "service_id": service_id, "verify": True},
        )
        _expect(
            prefetched_access.get("cache_hit") is True,
            f"Prefetched key should already be in cache: {prefetched_access}",
        )
        print(f"[smoke] prefetch worker validated for key {prefetched_key_id}")

        audit_payload = _request_json(client, "GET", "/security/audit?limit=20")
        _expect(audit_payload.get("total_count", 0) > 0, f"Audit endpoint returned no events: {audit_payload}")

        _request_json(client, "GET", "/security/intrusions?limit=20")
        _request_json(client, "GET", "/metrics/latency")
        _request_json(client, "GET", "/metrics/cache-distribution")
        _request_json(client, "GET", "/metrics/accuracy")
        _request_json(client, "GET", "/prefetch/dlq?limit=10")

        prometheus_response = client.get("/metrics/prometheus")
        _require_security_headers(prometheus_response, "GET /metrics/prometheus")
        _expect(
            prometheus_response.status_code == 200 and "pskc_requests_total" in prometheus_response.text,
            f"Prometheus exporter missing expected metric names: {prometheus_response.text[:200]}",
        )

    print("[smoke] backend runtime validation completed successfully")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a live PSKC backend smoke test against Docker Compose.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Base URL for the API service")
    parser.add_argument(
        "--redis-url",
        default="redis://:pskc_redis_secret@127.0.0.1:6379/0",
        help="Redis URL used to enqueue a prefetch worker validation job",
    )
    parser.add_argument(
        "--prefetch-queue-key",
        default="pskc:prefetch:jobs",
        help="Redis queue key used by the prefetch worker",
    )
    parser.add_argument(
        "--startup-timeout-seconds",
        type=int,
        default=120,
        help="Maximum time to wait for the API health endpoint",
    )
    parser.add_argument(
        "--worker-timeout-seconds",
        type=int,
        default=60,
        help="Maximum time to wait for the prefetch worker to finish a smoke job",
    )
    parser.add_argument(
        "--http-timeout-seconds",
        type=float,
        default=15.0,
        help="Per-request HTTP timeout",
    )
    return parser


if __name__ == "__main__":
    try:
        run_smoke(build_parser().parse_args())
    except Exception as exc:
        print(f"[smoke] failed: {exc}", file=sys.stderr)
        sys.exit(1)
