# ============================================================
# PSKC — Local Cache Module
# In-memory cache manager with TTL support
# ============================================================
import time
import threading
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass, field
from collections import OrderedDict
import logging

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Single cache entry with metadata"""
    key: str
    value: Any
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    ttl: int = 300  # Default TTL in seconds
    
    def is_expired(self) -> bool:
        """Check if entry has expired"""
        return (time.time() - self.created_at) > self.ttl
    
    def touch(self):
        """Update last accessed time"""
        self.last_accessed = time.time()
        self.access_count += 1


class LocalCache:
    """
    Thread-safe in-memory LRU cache with TTL support.
    Implements a hybrid of LRU and TTL eviction policies.
    """
    
    def __init__(
        self,
        max_size: int = 10000,
        default_ttl: int = 300,
        cleanup_interval: int = 60
    ):
        """
        Initialize local cache.
        
        Args:
            max_size: Maximum number of entries
            default_ttl: Default time-to-live in seconds
            cleanup_interval: Interval for expired entry cleanup
        """
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._cleanup_interval = cleanup_interval
        
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        
        self._hits = 0
        self._misses = 0
        
        # Start cleanup thread
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._running = True
        self._cleanup_thread.start()
        
        logger.info(f"LocalCache initialized: max_size={max_size}, ttl={default_ttl}s")
    
    def _cleanup_loop(self):
        """Background cleanup of expired entries"""
        while self._running:
            time.sleep(self._cleanup_interval)
            self._cleanup_expired()
    
    def _cleanup_expired(self):
        """Remove expired entries"""
        with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items()
                if entry.is_expired()
            ]
            
            for key in expired_keys:
                del self._cache[key]
                logger.debug(f"Evicted expired key: {key}")
            
            if expired_keys:
                logger.info(f"Cleaned up {len(expired_keys)} expired entries")
    
    def _evict_if_needed(self):
        """Evict oldest entries if cache is full"""
        while len(self._cache) >= self._max_size:
            # Remove oldest (first) entry
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
            logger.debug(f"Evicted LRU key: {oldest_key}")
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found/expired
        """
        with self._lock:
            entry = self._cache.get(key)
            
            if entry is None:
                self._misses += 1
                logger.debug(f"Cache miss: {key}")
                return None
            
            if entry.is_expired():
                del self._cache[key]
                self._misses += 1
                logger.debug(f"Cache expired: {key}")
                return None
            
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            entry.touch()
            self._hits += 1
            
            logger.debug(f"Cache hit: {key}")
            return entry.value
    
    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ) -> bool:
        """
        Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds (uses default if not specified)
            
        Returns:
            True if successful
        """
        with self._lock:
            # Evict if needed
            if key not in self._cache and len(self._cache) >= self._max_size:
                self._evict_if_needed()
            
            entry = CacheEntry(
                key=key,
                value=value,
                ttl=ttl if ttl is not None else self._default_ttl
            )
            
            self._cache[key] = entry
            logger.debug(f"Cache set: {key} (ttl={entry.ttl}s)")
            return True
    
    def delete(self, key: str) -> bool:
        """
        Delete entry from cache.
        
        Args:
            key: Cache key
            
        Returns:
            True if key was found and deleted
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                logger.debug(f"Cache delete: {key}")
                return True
            return False
    
    def exists(self, key: str) -> bool:
        """Check if key exists and is not expired"""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return False
            if entry.is_expired():
                del self._cache[key]
                return False
            return True
    
    def clear(self):
        """Clear all cache entries"""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            logger.info("Cache cleared")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0.0
            
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": hit_rate,
                "total_requests": total
            }
    
    def get_keys(self, pattern: str = "*") -> list:
        """Get all keys matching pattern (simple wildcard support)"""
        with self._lock:
            if pattern == "*":
                return list(self._cache.keys())
            
            # Simple pattern matching
            prefix = pattern.rstrip("*")
            return [k for k in self._cache.keys() if k.startswith(prefix)]
    
    def get_ttl(self, key: str) -> Optional[int]:
        """Get remaining TTL for a key"""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            
            remaining = entry.ttl - (time.time() - entry.created_at)
            return max(0, int(remaining))
    
    def shutdown(self):
        """Gracefully shutdown the cache"""
        self._running = False
        logger.info("Cache shutdown initiated")


# Global cache instance
_cache_instance: Optional[LocalCache] = None


def get_cache() -> LocalCache:
    """Get global cache instance"""
    global _cache_instance
    if _cache_instance is None:
        from config.settings import settings
        _cache_instance = LocalCache(
            max_size=settings.cache_max_size,
            default_ttl=settings.cache_ttl_seconds
        )
    return _cache_instance
