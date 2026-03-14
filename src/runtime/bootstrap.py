import logging
import secrets
from typing import Any, Dict, Optional

from config.settings import settings
from src.cache.cache_policy import CachePolicyManager
from src.cache.encrypted_store import EncryptedCacheStore
from src.cache.local_cache import LocalCache
from src.cache.redis_cache import RedisCache
from src.security.fips_module import FipsCryptographicModule
from src.security.intrusion_detection import SecureCacheManager
from src.security.tamper_evident_logger import TamperEvidentAuditLogger

logger = logging.getLogger(__name__)


def build_runtime_services(log_directory: Optional[str] = None) -> Dict[str, Any]:
    effective_log_directory = log_directory or settings.audit_log_directory
    raw_key = settings.cache_encryption_key or secrets.token_hex(32)
    master_key = FipsCryptographicModule.derive_key_hkdf(raw_key.encode("utf-8"), "pskc-fips-master-key-v1")
    fips_module = FipsCryptographicModule(master_key)

    audit_logger = TamperEvidentAuditLogger(
        fips_module=fips_module,
        log_directory=effective_log_directory,
    )
    local_cache = LocalCache(max_size=settings.cache_max_size, default_ttl=settings.cache_ttl_seconds)
    policy_manager = CachePolicyManager()
    redis_cache = RedisCache()

    encrypted_store = EncryptedCacheStore(
        cache=local_cache,
        policy_manager=policy_manager,
        fips_module=fips_module,
        audit_logger=audit_logger,
        shared_cache=redis_cache,
    )
    secure_cache_manager = SecureCacheManager(
        encrypted_store=encrypted_store,
        audit_logger=audit_logger,
    )

    return {
        "fips_module": fips_module,
        "audit_logger": audit_logger,
        "local_cache": local_cache,
        "policy_manager": policy_manager,
        "redis_cache": redis_cache,
        "encrypted_store": encrypted_store,
        "secure_cache_manager": secure_cache_manager,
    }


def shutdown_runtime_services(services: Dict[str, Any]) -> None:
    redis_cache = services.get("redis_cache")
    if redis_cache is not None:
        redis_cache.close()

    local_cache = services.get("local_cache")
    if local_cache is not None:
        local_cache.shutdown()

    fips_module = services.get("fips_module")
    if fips_module is not None:
        fips_module.destroy()

    logger.info("Runtime services shut down")
