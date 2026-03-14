import logging
import time
from typing import Any, Dict, List, Optional

import redis
from redis.exceptions import RedisError

from config.settings import settings

logger = logging.getLogger(__name__)


def _get_setting(name: str, default: Any) -> Any:
    return getattr(settings, name, default)


class RedisCache:
    """Redis-backed shared cache used as encrypted L2 storage."""

    def __init__(
        self,
        redis_url: Optional[str] = None,
        key_prefix: Optional[str] = None,
        default_ttl: Optional[int] = None,
    ):
        effective_redis_url = redis_url or _get_setting("redis_url", "redis://localhost:6379/0")
        effective_key_prefix = key_prefix or _get_setting("redis_cache_prefix", "pskc:cache")
        effective_default_ttl = (
            default_ttl if default_ttl is not None else _get_setting("cache_ttl_seconds", 300)
        )
        effective_connect_timeout = float(_get_setting("redis_socket_connect_timeout_seconds", 0.5))
        effective_socket_timeout = float(_get_setting("redis_socket_timeout_seconds", 0.5))
        self._failure_backoff_seconds = float(_get_setting("redis_failure_backoff_seconds", 30.0))
        self._disabled_until = 0.0

        self._key_prefix = str(effective_key_prefix).rstrip(":")
        self._default_ttl = int(effective_default_ttl)
        self._client = redis.Redis.from_url(
            effective_redis_url,
            decode_responses=True,
            socket_connect_timeout=effective_connect_timeout,
            socket_timeout=effective_socket_timeout,
            retry_on_timeout=False,
        )
        logger.info("RedisCache initialized: prefix=%s", self._key_prefix)

    def _is_available(self) -> bool:
        return time.time() >= self._disabled_until

    def _record_failure(self, operation: str, key: Optional[str], exc: Exception) -> None:
        self._disabled_until = time.time() + self._failure_backoff_seconds
        target = f" for {key}" if key else ""
        logger.warning("Redis %s failed%s: %s", operation, target, exc)

    def _full_key(self, key: str) -> str:
        return f"{self._key_prefix}:{key}"

    def ping(self) -> bool:
        if not self._is_available():
            return False
        try:
            return bool(self._client.ping())
        except RedisError as exc:
            self._record_failure("ping", None, exc)
            return False

    def get(self, key: str) -> Optional[str]:
        if not self._is_available():
            return None
        try:
            return self._client.get(self._full_key(key))
        except RedisError as exc:
            self._record_failure("get", key, exc)
            return None

    def set(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        if not self._is_available():
            return False
        try:
            effective_ttl = ttl if ttl is not None else self._default_ttl
            return bool(self._client.set(self._full_key(key), value, ex=effective_ttl))
        except RedisError as exc:
            self._record_failure("set", key, exc)
            return False

    def delete(self, key: str) -> bool:
        if not self._is_available():
            return False
        try:
            return bool(self._client.delete(self._full_key(key)))
        except RedisError as exc:
            self._record_failure("delete", key, exc)
            return False

    def exists(self, key: str) -> bool:
        if not self._is_available():
            return False
        try:
            return bool(self._client.exists(self._full_key(key)))
        except RedisError as exc:
            self._record_failure("exists", key, exc)
            return False

    def get_ttl(self, key: str) -> Optional[int]:
        if not self._is_available():
            return None
        try:
            ttl = int(self._client.ttl(self._full_key(key)))
        except RedisError as exc:
            self._record_failure("ttl", key, exc)
            return None

        if ttl < 0:
            return None
        return ttl

    def get_keys(self, pattern: str = "*") -> List[str]:
        if not self._is_available():
            return []
        try:
            keys = list(self._client.scan_iter(match=f"{self._key_prefix}:{pattern}"))
        except RedisError as exc:
            self._record_failure("key_scan", None, exc)
            return []

        prefix = f"{self._key_prefix}:"
        return [key[len(prefix):] if key.startswith(prefix) else key for key in keys]

    def get_stats(self) -> Dict[str, Any]:
        keys = self.get_keys()
        return {
            "enabled": True,
            "available": self.ping(),
            "size": len(keys),
            "prefix": self._key_prefix,
        }

    def close(self) -> None:
        try:
            self._client.close()
        except RedisError as exc:
            self._record_failure("close", None, exc)
