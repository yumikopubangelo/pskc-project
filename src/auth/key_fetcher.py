# ============================================================
# PSKC — Key Fetcher Module
# Fetch cryptographic keys from KMS
# ============================================================
import time
import asyncio
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum
import logging
import httpx

logger = logging.getLogger(__name__)


class KMSProvider(Enum):
    """Supported KMS providers"""
    AWS_KMS = "aws_kms"
    VAULT = "vault"
    SPOTIFY_PADLOCK = "spotify_padlock"
    GENERIC = "generic"


@dataclass
class KeyMetadata:
    """Metadata for a cryptographic key"""
    key_id: str
    key_type: str = "symmetric"  # symmetric, asymmetric
    algorithm: str = "AES-256"
    created_at: Optional[float] = None
    expires_at: Optional[float] = None
    enabled: bool = True
    provider: KMSProvider = KMSProvider.GENERIC


class KeyFetcher:
    """
    Fetches cryptographic keys from Key Management Service.
    Supports multiple KMS providers (AWS KMS, Vault, Spotify Padlock, etc.)
    """
    
    def __init__(
        self,
        provider: KMSProvider = KMSProvider.GENERIC,
        endpoint: str = None,
        timeout: float = 5.0,
        max_retries: int = 3
    ):
        self._provider = provider
        self._endpoint = endpoint
        self._timeout = timeout
        self._max_retries = max_retries
        
        # Cache for key metadata
        self._key_metadata: Dict[str, KeyMetadata] = {}
        
        logger.info(f"KeyFetcher initialized: provider={provider.value}")
    
    async def fetch_key(
        self,
        key_id: str,
        service_id: str = "default"
    ) -> Optional[bytes]:
        """
        Fetch key from KMS.
        
        Args:
            key_id: Key identifier
            service_id: Service requesting the key
            
        Returns:
            Raw key bytes or None if failed
        """
        start_time = time.time()
        
        try:
            if self._provider == KMSProvider.AWS_KMS:
                key_data = await self._fetch_aws_kms(key_id)
            elif self._provider == KMSProvider.VAULT:
                key_data = await self._fetch_vault(key_id)
            elif self._provider == KMSProvider.SPOTIFY_PADLOCK:
                key_data = await self._fetch_spotify_padlock(key_id)
            else:
                key_data = await self._fetch_generic(key_id)
            
            latency = (time.time() - start_time) * 1000
            logger.info(f"Fetched key {key_id} in {latency:.2f}ms")
            
            return key_data
            
        except Exception as e:
            latency = (time.time() - start_time) * 1000
            logger.error(f"Failed to fetch key {key_id}: {e}")
            return None
    
    async def _fetch_aws_kms(self, key_id: str) -> bytes:
        """Fetch from AWS KMS"""
        # Simulated AWS KMS fetch
        # In production, use boto3 AWS SDK
        await asyncio.sleep(0.05)  # Simulate network latency
        
        # Return simulated key data
        return f"aws_kms_key_{key_id}".encode()[:32]
    
    async def _fetch_vault(self, key_id: str) -> bytes:
        """Fetch from HashiCorp Vault"""
        if not self._endpoint:
            raise ValueError("Vault endpoint not configured")
        
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(
                f"{self._endpoint}/v1/secret/data/keys/{key_id}"
            )
            response.raise_for_status()
            
            data = response.json()
            return data["data"]["data"]["key"].encode()
    
    async def _fetch_spotify_padlock(self, key_id: str) -> bytes:
        """Fetch from Spotify Padlock"""
        # Simulated Spotify Padlock fetch
        await asyncio.sleep(0.02)  # Simulate network latency
        
        # Return simulated key data
        return f"spotify_key_{key_id}".encode()[:32]
    
    async def _fetch_generic(self, key_id: str) -> bytes:
        """Generic KMS fetch"""
        if not self._endpoint:
            # Return simulated key for testing
            return f"generic_key_{key_id}".encode()[:32]
        
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(
                f"{self._endpoint}/keys/{key_id}"
            )
            response.raise_for_status()
            
            data = response.json()
            return data["key"].encode()
    
    async def fetch_keys_batch(
        self,
        key_ids: List[str],
        service_id: str = "default"
    ) -> Dict[str, Optional[bytes]]:
        """
        Fetch multiple keys in parallel.
        
        Args:
            key_ids: List of key identifiers
            service_id: Service requesting the keys
            
        Returns:
            Dict of {key_id: key_data or None}
        """
        tasks = [
            self.fetch_key(key_id, service_id)
            for key_id in key_ids
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        return {
            key_id: result if isinstance(result, bytes) else None
            for key_id, result in zip(key_ids, results)
        }
    
    def get_key_metadata(self, key_id: str) -> Optional[KeyMetadata]:
        """Get metadata for a key"""
        return self._key_metadata.get(key_id)
    
    def store_key_metadata(self, metadata: KeyMetadata):
        """Store key metadata"""
        self._key_metadata[metadata.key_id] = metadata


class KeyCache:
    """In-memory cache for fetched keys (short TTL)"""
    
    def __init__(self, ttl: int = 60):
        self._cache: Dict[str, tuple] = {}
        self._ttl = ttl
    
    def get(self, key_id: str) -> Optional[bytes]:
        """Get key from cache if not expired"""
        if key_id in self._cache:
            key_data, timestamp = self._cache[key_id]
            if time.time() - timestamp < self._ttl:
                return key_data
            else:
                del self._cache[key_id]
        return None
    
    def set(self, key_id: str, key_data: bytes):
        """Cache key with timestamp"""
        self._cache[key_id] = (key_data, time.time())


# Global fetcher instance
_fetcher_instance: Optional[KeyFetcher] = None
_key_cache: Optional[KeyCache] = None


def get_key_fetcher() -> KeyFetcher:
    """Get global key fetcher instance"""
    global _fetcher_instance
    if _fetcher_instance is None:
        _fetcher_instance = KeyFetcher()
    return _fetcher_instance


def get_key_cache() -> KeyCache:
    """Get global key cache"""
    global _key_cache
    if _key_cache is None:
        _key_cache = KeyCache()
    return _key_cache


async def fetch_key_with_cache(
    key_id: str,
    service_id: str = "default"
) -> Optional[bytes]:
    """Fetch key with local caching"""
    cache = get_key_cache()
    
    # Check cache first
    cached = cache.get(key_id)
    if cached:
        logger.debug(f"Key cache hit: {key_id}")
        return cached
    
    # Fetch from KMS
    fetcher = get_key_fetcher()
    key_data = await fetcher.fetch_key(key_id, service_id)
    
    # Cache if successful
    if key_data:
        cache.set(key_id, key_data)
    
    return key_data
