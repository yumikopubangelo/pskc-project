# ============================================================
# Routes Key Management Endpoints Module
# ============================================================
import base64
import binascii
import logging
import time
import ipaddress
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException, status, Request, Depends
from src.api.schemas import KeyAccessRequest, KeyAccessResponse, KeyStoreRequest, KeyStoreResponse, CacheStatsResponse
from src.security.intrusion_detection import SecureCacheManager
from src.auth.key_fetcher import get_key_fetcher
from src.security.security_headers import TRUSTED_PROXIES
from src.observability.metrics_persistence import get_metrics_persistence
from src.api.ml_service import record_runtime_access, schedule_request_path_prefetch
from config.settings import settings

logger = logging.getLogger(__name__)

# In-memory metrics storage for demo purposes
metrics_storage = {
    "cache_hits": 0,
    "cache_misses": 0,
    "total_requests": 0,
    "latencies": [],
    "active_keys": set()
}


def get_metrics_storage():
    """Get the metrics storage dictionary"""
    return metrics_storage


def get_secure_cache_manager(request: Request) -> SecureCacheManager:
    return request.app.state.secure_cache_manager


def extract_client_ip(request: Request) -> Optional[str]:
    client_host = request.client.host if request.client else None
    if not client_host: return None
    try:
        is_trusted = any(ipaddress.ip_address(client_host) in net for net in TRUSTED_PROXIES)
    except ValueError:
        is_trusted = False
    forwarded_for = request.headers.get("X-Forwarded-For")
    if is_trusted and forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return client_host


def create_key_router() -> APIRouter:
    """Create and return the key management router"""
    router = APIRouter(tags=["keys"])

    @router.post("/keys/access", response_model=KeyAccessResponse)
    async def access_key(
        req_body: KeyAccessRequest, 
        request: Request,
        background_tasks: BackgroundTasks,
        secure_manager: SecureCacheManager = Depends(get_secure_cache_manager)
    ):
        """Mengakses kunci dari cache atau KMS menggunakan alur yang aman."""
        ip_address = extract_client_ip(request)
        started_at = time.perf_counter()
        metrics = get_metrics_storage()
        
        try:
            key_data, cache_hit, latency, security_ok = secure_manager.secure_get(
                req_body.key_id,
                req_body.service_id,
                ip_address
            )
            
            if not security_ok:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access blocked by security system")
            
            if key_data is None:
                fetcher = get_key_fetcher()
                key_data = await fetcher.fetch_key(req_body.key_id, req_body.service_id)
                if key_data is None:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Key not found: {req_body.key_id}")
                
                if not secure_manager.secure_set(req_body.key_id, key_data, req_body.service_id, ip_address or ""):
                    logger.error(
                        "Failed to securely cache fetched key key_id=%s service_id=%s",
                        req_body.key_id,
                        req_body.service_id,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Failed to store fetched key securely",
                    )
                cache_hit = False

            total_latency_ms = (time.perf_counter() - started_at) * 1000
            metrics["total_requests"] += 1
            if cache_hit:
                metrics["cache_hits"] += 1
            else:
                metrics["cache_misses"] += 1
            metrics["latencies"].append(total_latency_ms)
            metrics["latencies"] = metrics["latencies"][-500:]
            metrics["active_keys"].add(req_body.key_id)

            metrics_persistence = get_metrics_persistence()
            if metrics_persistence is not None and metrics_persistence.ping():
                try:
                    metrics_persistence.record_request(
                        cache_hit=cache_hit,
                        latency_ms=total_latency_ms,
                        key_id=req_body.key_id
                    )
                except Exception as mp_exc:
                    logger.warning(f"Failed to persist metrics: {mp_exc}")

            try:
                record_runtime_access(
                    key_id=req_body.key_id,
                    service_id=req_body.service_id,
                    latency_ms=total_latency_ms,
                    cache_hit=cache_hit,
                    verify=req_body.verify,
                    source_ip=ip_address or "",
                )
            except Exception as ml_exc:
                logger.warning(f"Failed to record ML runtime access for {req_body.key_id}: {ml_exc}")

            background_tasks.add_task(
                schedule_request_path_prefetch,
                secure_manager,
                req_body.service_id,
                req_body.key_id,
                ip_address or "",
            )
            
            return KeyAccessResponse(
                success=True,
                key_id=req_body.key_id,
                cache_hit=cache_hit,
                latency_ms=total_latency_ms
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Error accessing key: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to access key",
            )

    @router.post("/keys/store", response_model=KeyStoreResponse)
    async def store_key(
        req_body: KeyStoreRequest, 
        request: Request,
        secure_manager: SecureCacheManager = Depends(get_secure_cache_manager)
    ):
        """Menyimpan kunci ke dalam cache yang terenkripsi."""
        ip_address = extract_client_ip(request)
        metrics = get_metrics_storage()
        
        try:
            key_data = base64.b64decode(req_body.key_data, validate=True)
            success = secure_manager.secure_set(
                req_body.key_id,
                key_data,
                req_body.service_id,
                ip_address or "",
                ttl=req_body.ttl,
            )
            
            if not success:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Key rejected by security system")

            metrics["active_keys"].add(req_body.key_id)
            
            return KeyStoreResponse(success=True, key_id=req_body.key_id, service_id=req_body.service_id)

        except HTTPException:
            raise
        except (binascii.Error, ValueError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid base64 key_data payload",
            )
        except Exception as e:
            logger.exception("Error storing key: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to store key",
            )

    @router.get("/keys/cache/stats")
    @router.get("/cache/stats", include_in_schema=False)
    async def get_cache_stats(
        secure_manager: SecureCacheManager = Depends(get_secure_cache_manager)
    ):
        """Get cache statistics"""
        metrics = get_metrics_storage()
        hits = metrics["cache_hits"]
        misses = metrics["cache_misses"]
        total = metrics["total_requests"]
        hit_rate = hits / total if total > 0 else 0.0
        cache_size = len(secure_manager.get_cache_keys())
        
        return CacheStatsResponse(
            size=cache_size,
            max_size=settings.cache_max_size,
            hits=hits,
            misses=misses,
            hit_rate=hit_rate,
            total_requests=total
        )

    @router.get("/keys/keys")
    @router.get("/cache/keys", include_in_schema=False)
    async def get_cache_keys(
        secure_manager: SecureCacheManager = Depends(get_secure_cache_manager)
    ):
        """Get list of cached keys"""
        keys = secure_manager.get_cache_keys()
        return {"keys": keys, "count": len(keys)}

    @router.post("/keys/invalidate/{key}")
    @router.post("/cache/invalidate/{key}", include_in_schema=False)
    async def invalidate_key(
        key: str,
        secure_manager: SecureCacheManager = Depends(get_secure_cache_manager)
    ):
        """Invalidate a cache key"""
        metrics = get_metrics_storage()
        removed = False

        if key in metrics["active_keys"]:
            metrics["active_keys"].discard(key)
            removed = True

        if secure_manager.secure_delete(key, "default", reason="manual_invalidate"):
            removed = True
        else:
            for cache_key in secure_manager.get_cache_keys():
                if cache_key == key:
                    continue
                if cache_key.endswith(f":{key}"):
                    service_id = cache_key.split(":", 1)[0]
                    if secure_manager.secure_delete(key, service_id, reason="manual_invalidate"):
                        removed = True

        if removed:
            return {"success": True, "key": key, "message": "Key invalidated"}
        return {"success": False, "key": key, "message": "Key not found"}
    
    return router
