from src.cache import redis_cache as redis_cache_module
from src.prefetch import queue as queue_module


def test_redis_cache_configures_short_socket_timeouts(monkeypatch):
    captured = {}

    class DummyClient:
        def close(self):
            return None

    def fake_from_url(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return DummyClient()

    monkeypatch.setattr(redis_cache_module.redis.Redis, "from_url", fake_from_url)

    cache = redis_cache_module.RedisCache(redis_url="redis://example:6379/0", key_prefix="test", default_ttl=10)

    assert captured["url"] == "redis://example:6379/0"
    assert captured["kwargs"]["socket_connect_timeout"] == 0.5
    assert captured["kwargs"]["socket_timeout"] == 0.5
    assert captured["kwargs"]["retry_on_timeout"] is False
    assert cache._key_prefix == "test"


def test_prefetch_queue_configures_short_socket_timeouts(monkeypatch):
    captured = {}

    class DummyClient:
        def close(self):
            return None

    def fake_from_url(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return DummyClient()

    monkeypatch.setattr(queue_module.redis.Redis, "from_url", fake_from_url)

    queue = queue_module.PrefetchQueue(redis_url="redis://example:6379/0", queue_key="jobs")

    assert captured["url"] == "redis://example:6379/0"
    assert captured["kwargs"]["socket_connect_timeout"] == 0.5
    assert captured["kwargs"]["socket_timeout"] == 0.5
    assert captured["kwargs"]["retry_on_timeout"] is False
    assert queue._queue_key == "jobs"
