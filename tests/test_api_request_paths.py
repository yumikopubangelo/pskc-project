import base64
from typing import Any, Dict, Optional

import pytest
from fastapi.testclient import TestClient

from src.api import routes
from src.cache.cache_policy import CachePolicyManager
from src.cache.encrypted_store import EncryptedCacheStore
from src.cache.local_cache import LocalCache
from src.security.fips_module import FipsCryptographicModule
from src.security.intrusion_detection import SecureCacheManager
from src.security.tamper_evident_logger import TamperEvidentAuditLogger


class FakeSharedCache:
    def __init__(self):
        self._store: Dict[str, str] = {}
        self._ttl: Dict[str, Optional[int]] = {}

    def get(self, key: str) -> Optional[str]:
        return self._store.get(key)

    def set(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        self._store[key] = value
        self._ttl[key] = ttl
        return True

    def delete(self, key: str) -> bool:
        existed = key in self._store
        self._store.pop(key, None)
        self._ttl.pop(key, None)
        return existed

    def exists(self, key: str) -> bool:
        return key in self._store

    def get_ttl(self, key: str) -> Optional[int]:
        return self._ttl.get(key)

    def get_keys(self, pattern: str = "*") -> list[str]:
        return list(self._store.keys())

    def get_stats(self) -> Dict[str, Any]:
        return {"enabled": True, "available": True, "size": len(self._store), "prefix": "fake"}

    def close(self) -> None:
        return None


class FakeFetcher:
    def __init__(self, payloads: Optional[Dict[str, Optional[bytes]]] = None):
        self.payloads = payloads or {}

    async def fetch_key(self, key_id: str, service_id: str = "default") -> Optional[bytes]:
        return self.payloads.get(key_id, f"fetched_{service_id}_{key_id}".encode("utf-8"))

    async def fetch_keys_batch(self, key_ids: list[str], service_id: str = "default") -> Dict[str, Optional[bytes]]:
        return {key_id: await self.fetch_key(key_id, service_id) for key_id in key_ids}


class FakePrefetchQueue:
    def ping(self) -> bool:
        return True


def _build_runtime_services(log_directory: str):
    fips_module = FipsCryptographicModule(b"\x02" * FipsCryptographicModule.AES_KEY_SIZE)
    audit_logger = TamperEvidentAuditLogger(fips_module=fips_module, log_directory=log_directory)
    local_cache = LocalCache(max_size=64, default_ttl=300)
    shared_cache = FakeSharedCache()
    encrypted_store = EncryptedCacheStore(
        cache=local_cache,
        policy_manager=CachePolicyManager(),
        fips_module=fips_module,
        audit_logger=audit_logger,
        shared_cache=shared_cache,
    )
    secure_cache_manager = SecureCacheManager(encrypted_store=encrypted_store, audit_logger=audit_logger)
    return {
        "fips_module": fips_module,
        "audit_logger": audit_logger,
        "local_cache": local_cache,
        "redis_cache": shared_cache,
        "encrypted_store": encrypted_store,
        "secure_cache_manager": secure_cache_manager,
    }


def _shutdown_runtime_services(services: Dict[str, Any]) -> None:
    services["local_cache"].shutdown()
    services["redis_cache"].close()
    services["fips_module"].destroy()


@pytest.fixture
def test_client(monkeypatch, tmp_path):
    routes._metrics_storage["cache_hits"] = 0
    routes._metrics_storage["cache_misses"] = 0
    routes._metrics_storage["total_requests"] = 0
    routes._metrics_storage["latencies"] = []
    routes._metrics_storage["active_keys"] = set()

    monkeypatch.setattr(
        routes,
        "build_runtime_services",
        lambda: _build_runtime_services(str(tmp_path / "logs")),
    )
    monkeypatch.setattr(routes, "shutdown_runtime_services", _shutdown_runtime_services)
    monkeypatch.setattr(routes, "run_power_on_self_tests", lambda fips_module: None)
    monkeypatch.setattr(routes, "initialize_ml_runtime", lambda: {"status": "stub"})
    monkeypatch.setattr(routes, "shutdown_ml_runtime", lambda: None)
    monkeypatch.setattr(routes, "record_runtime_access", lambda **kwargs: None)
    monkeypatch.setattr(routes, "schedule_request_path_prefetch", lambda *args, **kwargs: None)
    monkeypatch.setattr(routes, "get_prefetch_queue", lambda: FakePrefetchQueue())

    with TestClient(routes.app) as client:
        yield client


def test_store_key_accepts_valid_base64_and_preserves_ttl(test_client):
    payload = {
        "key_id": "alpha",
        "key_data": base64.b64encode(b"secret-alpha").decode("ascii"),
        "service_id": "svc-a",
        "ttl": 123,
    }

    response = test_client.post("/keys/store", json=payload)

    assert response.status_code == 200
    assert response.json()["success"] is True

    stored_entry = test_client.app.state.runtime_services["local_cache"]._cache["svc-a:alpha"]
    assert stored_entry.ttl == 123


def test_store_key_rejects_invalid_base64_with_400(test_client):
    response = test_client.post(
        "/keys/store",
        json={"key_id": "bad", "key_data": "***notb64***", "service_id": "svc-a"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid base64 key_data payload"


@pytest.mark.parametrize(
    ("endpoint", "payload"),
    [
        (
            "/keys/store",
            {
                "key_id": "unsafe:key",
                "key_data": base64.b64encode(b"secret").decode("ascii"),
                "service_id": "svc-a",
            },
        ),
        (
            "/keys/store",
            {
                "key_id": "alpha",
                "key_data": base64.b64encode(b"secret").decode("ascii"),
                "service_id": "../svc",
            },
        ),
        (
            "/keys/access",
            {"key_id": "../escape", "service_id": "svc-a", "verify": True},
        ),
    ],
)
def test_key_endpoints_reject_unsafe_identifiers(test_client, endpoint, payload):
    response = test_client.post(endpoint, json=payload)

    assert response.status_code == 422


def test_store_key_rejects_out_of_range_ttl(test_client):
    response = test_client.post(
        "/keys/store",
        json={
            "key_id": "ttl-bad",
            "key_data": base64.b64encode(b"secret").decode("ascii"),
            "service_id": "svc-a",
            "ttl": 0,
        },
    )

    assert response.status_code == 422


def test_store_key_security_rejection_stays_400(test_client, monkeypatch):
    monkeypatch.setattr(test_client.app.state.secure_cache_manager, "secure_set", lambda *args, **kwargs: False)

    response = test_client.post(
        "/keys/store",
        json={
            "key_id": "blocked",
            "key_data": base64.b64encode(b"secret").decode("ascii"),
            "service_id": "svc-a",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Key rejected by security system"


def test_access_key_cache_miss_fetches_then_subsequent_hit(test_client, monkeypatch):
    monkeypatch.setattr(routes, "get_key_fetcher", lambda: FakeFetcher({"k-miss": b"fetched-value"}))

    miss_response = test_client.post(
        "/keys/access",
        json={"key_id": "k-miss", "service_id": "svc-a", "verify": True},
    )
    hit_response = test_client.post(
        "/keys/access",
        json={"key_id": "k-miss", "service_id": "svc-a", "verify": True},
    )

    assert miss_response.status_code == 200
    assert miss_response.json()["cache_hit"] is False
    assert hit_response.status_code == 200
    assert hit_response.json()["cache_hit"] is True

    metrics_response = test_client.get("/metrics")
    assert metrics_response.status_code == 200
    metrics_payload = metrics_response.json()
    assert metrics_payload["cache_misses"] == 1
    assert metrics_payload["cache_hits"] == 1
    assert metrics_payload["total_requests"] == 2


def test_access_key_returns_503_when_secure_cache_store_fails_after_fetch(test_client, monkeypatch):
    monkeypatch.setattr(routes, "get_key_fetcher", lambda: FakeFetcher({"k-fail": b"value"}))

    original_secure_get = test_client.app.state.secure_cache_manager.secure_get

    def fake_secure_set(key_id: str, key_data: bytes, service_id: str, ip_address: str = "", **kwargs) -> bool:
        return False

    monkeypatch.setattr(test_client.app.state.secure_cache_manager, "secure_set", fake_secure_set)
    monkeypatch.setattr(test_client.app.state.secure_cache_manager, "secure_get", original_secure_get)

    response = test_client.post(
        "/keys/access",
        json={"key_id": "k-fail", "service_id": "svc-a", "verify": True},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Failed to store fetched key securely"


def test_access_key_error_response_does_not_leak_internal_details(test_client, monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("sensitive backend error")

    monkeypatch.setattr(test_client.app.state.secure_cache_manager, "secure_get", explode)

    response = test_client.post(
        "/keys/access",
        json={"key_id": "boom", "service_id": "svc-a", "verify": True},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to access key"


def test_access_key_blocks_low_reputation_ip(test_client):
    secure_manager = test_client.app.state.secure_cache_manager
    secure_manager.ids.update_reputation("testclient", -15)

    response = test_client.post(
        "/keys/access",
        json={"key_id": "blocked-ip", "service_id": "svc-a", "verify": True},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Access blocked by security system"


def test_cache_invalidate_finds_service_scoped_keys(test_client):
    store_response = test_client.post(
        "/keys/store",
        json={
            "key_id": "invalidate-me",
            "key_data": base64.b64encode(b"secret").decode("ascii"),
            "service_id": "svc-b",
        },
    )
    assert store_response.status_code == 200

    invalidate_response = test_client.post("/cache/invalidate/invalidate-me")

    assert invalidate_response.status_code == 200
    assert invalidate_response.json()["success"] is True


def test_security_audit_endpoint_reads_runtime_log(test_client):
    store_response = test_client.post(
        "/keys/store",
        json={
            "key_id": "audited",
            "key_data": base64.b64encode(b"secret").decode("ascii"),
            "service_id": "svc-a",
        },
    )
    assert store_response.status_code == 200

    audit_response = test_client.get("/security/audit", params={"limit": 10})

    assert audit_response.status_code == 200
    payload = audit_response.json()
    assert payload["total_count"] >= 1
    assert any(event["event_type"] == "KEY_CACHE_SET" for event in payload["audit_events"])


def test_security_intrusions_endpoint_reads_live_ids_alerts(test_client):
    secure_manager = test_client.app.state.secure_cache_manager
    for _ in range(5):
        secure_manager.ids.record_failed_attempt("svc-a", "10.0.0.5", "forced-test")

    intrusion_response = test_client.get("/security/intrusions", params={"limit": 10})

    assert intrusion_response.status_code == 200
    payload = intrusion_response.json()
    assert payload["total_count"] >= 1
    assert any(
        entry["event_type"] == "brute_force_attempt" and entry["source_ip"] == "10.0.0.5"
        for entry in payload["intrusions"]
    )


def test_ml_registry_endpoint_returns_runtime_registry_payload(test_client, monkeypatch):
    monkeypatch.setattr(
        routes,
        "get_model_registry_payload",
        lambda model_name=None: {
            "model_name": model_name or "pskc_model",
            "summary": {"active_version": "v2", "active_stage": "staging", "versions": []},
            "stats": {"signed_versions": 2, "unsigned_versions": 0},
        },
    )

    response = test_client.get("/ml/registry", params={"model_name": "pskc_model"})

    assert response.status_code == 200
    assert response.json()["summary"]["active_version"] == "v2"


def test_ml_lifecycle_endpoint_returns_persisted_history_payload(test_client, monkeypatch):
    monkeypatch.setattr(
        routes,
        "get_model_lifecycle_payload",
        lambda limit=100, model_name=None, event_type=None: {
            "model_name": model_name or "pskc_model",
            "events": [{"event": "promote", "version": "v2"}],
            "stats": {"events_total": 1, "events_by_type": {"promote": 1}},
        },
    )

    response = test_client.get(
        "/ml/lifecycle",
        params={"model_name": "pskc_model", "limit": 10, "event_type": "promote"},
    )

    assert response.status_code == 200
    assert response.json()["events"][0]["event"] == "promote"


def test_ml_promote_endpoint_maps_integrity_failures_to_409(test_client, monkeypatch):
    monkeypatch.setattr(
        routes,
        "promote_runtime_model_version",
        lambda **kwargs: {
            "success": False,
            "reason": "integrity_verification_failed",
            "detail": "signature mismatch",
        },
    )

    response = test_client.post(
        "/ml/promote",
        json={
            "model_name": "pskc_model",
            "version": "v2",
            "target_stage": "production",
            "actor": "tester",
            "notes": "rollout",
            "make_active": True,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "signature mismatch"


def test_ml_rollback_endpoint_returns_success_payload(test_client, monkeypatch):
    monkeypatch.setattr(
        routes,
        "rollback_runtime_model_version",
        lambda **kwargs: {
            "success": True,
            "version": "v1",
            "rolled_back_from": "v2",
            "runtime_reload": {"success": True},
        },
    )

    response = test_client.post(
        "/ml/rollback",
        json={
            "model_name": "pskc_model",
            "version": "v1",
            "actor": "tester",
            "notes": "rollback",
        },
    )

    assert response.status_code == 200
    assert response.json()["version"] == "v1"
    assert response.json()["rolled_back_from"] == "v2"


def test_corrupt_shared_cache_entry_is_deleted_from_shared_store(tmp_path):
    services = _build_runtime_services(str(tmp_path / "logs"))
    try:
        encrypted_store = services["encrypted_store"]
        shared_cache = services["redis_cache"]

        shared_cache.set("svc-a:corrupt", "not-base64", ttl=60)
        value, cache_hit, _ = encrypted_store.get_with_metadata("corrupt", "svc-a")

        assert value is None
        assert cache_hit is False
        assert shared_cache.exists("svc-a:corrupt") is False
    finally:
        _shutdown_runtime_services(services)
