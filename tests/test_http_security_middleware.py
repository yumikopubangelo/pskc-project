from src.api.routes import app
from src.cache import redis_cache as redis_cache_module
from src.security.security_headers import (
    TRUSTED_PROXIES,
    SecurityHeadersMiddleware,
    SlidingWindowRateLimiter,
    configure_trusted_proxies,
)


def test_routes_app_registers_http_security_middleware():
    middleware_classes = [middleware.cls for middleware in app.user_middleware]

    assert SecurityHeadersMiddleware in middleware_classes
    assert SlidingWindowRateLimiter in middleware_classes
    assert middleware_classes.index(SlidingWindowRateLimiter) < middleware_classes.index(
        SecurityHeadersMiddleware
    )


def test_configure_trusted_proxies_accepts_valid_cidrs_and_reports_invalid_entries():
    original_trusted_proxies = set(TRUSTED_PROXIES)
    try:
        invalid_entries = configure_trusted_proxies(
            ["127.0.0.1/32", "10.0.0.0/8", "invalid-cidr"]
        )

        assert invalid_entries == ["invalid-cidr"]
        assert any(str(network) == "127.0.0.1/32" for network in TRUSTED_PROXIES)
        assert any(str(network) == "10.0.0.0/8" for network in TRUSTED_PROXIES)
    finally:
        TRUSTED_PROXIES.clear()
        TRUSTED_PROXIES.update(original_trusted_proxies)


def test_redis_cache_falls_back_to_defaults_when_legacy_settings_lack_new_fields(monkeypatch):
    captured = {}

    class LegacySettings:
        pass

    class DummyRedisClient:
        def close(self):
            return None

    def fake_from_url(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return DummyRedisClient()

    monkeypatch.setattr(redis_cache_module, "settings", LegacySettings())
    monkeypatch.setattr(redis_cache_module.redis.Redis, "from_url", fake_from_url)

    cache = redis_cache_module.RedisCache()

    assert captured["url"] == "redis://localhost:6379/0"
    assert captured["kwargs"]["decode_responses"] is True
    assert cache._key_prefix == "pskc:cache"
    assert cache._default_ttl == 300
