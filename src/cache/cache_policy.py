# ============================================================
# PSKC — Cache Policy Module
# TTL and eviction policy management
# ============================================================
import time
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class EvictionPolicy(Enum):
    """Available eviction policies"""
    LRU = "lru"           # Least Recently Used
    LFU = "lfu"           # Least Frequently Used
    FIFO = "fifo"         # First In First Out
    TTL = "ttl"           # Time To Live (expire oldest)
    ADAPTIVE = "adaptive" # Adaptive policy based on access patterns


class CacheTier(Enum):
    """Cache tiers for hierarchical caching"""
    HOT = "hot"           # Frequently accessed, longer TTL
    WARM = "warm"         # Moderately accessed
    COLD = "cold"         # Rarely accessed, shorter TTL


@dataclass
class CachePolicy:
    """Cache policy configuration"""
    eviction_policy: EvictionPolicy = EvictionPolicy.LRU
    default_ttl: int = 300  # seconds
    max_size: int = 10000
    
    # Tier-specific settings
    hot_ttl: int = 600       # 10 minutes
    warm_ttl: int = 300       # 5 minutes
    cold_ttl: int = 60        # 1 minute
    
    # Thresholds
    hot_threshold: float = 0.8   # Access frequency threshold for hot
    warm_threshold: float = 0.4  # Access frequency threshold for warm
    
    # Dynamic TTL settings
    enable_dynamic_ttl: bool = True
    min_ttl: int = 30
    max_ttl: int = 3600


@dataclass
class KeyMetadata:
    """Metadata for cached keys"""
    key_id: str
    access_count: int = 0
    last_accessed: float = field(default_factory=time.time)
    first_accessed: float = field(default_factory=time.time)
    size_bytes: int = 0
    predicted: bool = False  # True if pre-cached by ML
    priority: float = 0.0    # ML-predicted priority
    
    def access_frequency(self) -> float:
        """Calculate access frequency (accesses per second)"""
        duration = time.time() - self.first_accessed
        if duration <= 0.01:  # If less than 10ms, consider as burst access
            # For burst accesses, use access count as frequency indicator
            # This allows distinguishing hot vs cold keys in burst scenarios
            if self.access_count >= 50:
                return 1.0  # Hot
            elif self.access_count >= 10:
                return 0.5  # Warm
            else:
                return 0.1  # Cold
        if duration <= 0:
            return 0.0
        return self.access_count / duration


class CachePolicyManager:
    """Manages cache policies and determines TTL/eviction"""
    
    def __init__(self, policy: Optional[CachePolicy] = None):
        self._policy = policy or CachePolicy()
        self._key_metadata: Dict[str, KeyMetadata] = {}
    
    @property
    def policy(self) -> CachePolicy:
        return self._policy
    
    def update_key_access(self, key_id: str, size_bytes: int = 0):
        """Update access metadata for a key"""
        now = time.time()
        
        if key_id not in self._key_metadata:
            self._key_metadata[key_id] = KeyMetadata(
                key_id=key_id,
                first_accessed=now,
                size_bytes=size_bytes
            )
        
        meta = self._key_metadata[key_id]
        meta.access_count += 1
        meta.last_accessed = now
        if size_bytes > 0:
            meta.size_bytes = size_bytes
    
    def set_key_priority(self, key_id: str, priority: float):
        """Set ML-predicted priority for a key"""
        if key_id not in self._key_metadata:
            self._key_metadata[key_id] = KeyMetadata(key_id=key_id)
        
        self._key_metadata[key_id].priority = priority
        self._key_metadata[key_id].predicted = True
    
    def get_ttl(self, key_id: str) -> int:
        """
        Determine TTL for a key based on access patterns and policy.
        
        Args:
            key_id: The key to get TTL for
            
        Returns:
            TTL in seconds
        """
        if not self._policy.enable_dynamic_ttl:
            return self._policy.default_ttl
        
        meta = self._key_metadata.get(key_id)
        
        if meta is None:
            return self._policy.default_ttl
        
        # Calculate TTL based on access frequency
        frequency = meta.access_frequency()
        
        if frequency >= self._policy.hot_threshold:
            # Hot key - longer TTL
            ttl = self._policy.hot_ttl
        elif frequency >= self._policy.warm_threshold:
            # Warm key - medium TTL
            ttl = self._policy.warm_ttl
        else:
            # Cold key - shorter TTL
            ttl = self._policy.cold_ttl
        
        # Boost TTL for ML-predicted high-priority keys
        # High-priority keys should always get at least default_ttl
        if meta.predicted and meta.priority > 0.7:
            # First apply the 1.5x boost
            boosted_ttl = min(ttl * 1.5, self._policy.max_ttl)
            # But ensure it's at least the default TTL for high-priority keys
            ttl = max(boosted_ttl, self._policy.default_ttl)
        
        # Clamp to min/max
        return max(self._policy.min_ttl, min(ttl, self._policy.max_ttl))
    
    def get_tier(self, key_id: str) -> CacheTier:
        """Determine cache tier for a key"""
        meta = self._key_metadata.get(key_id)
        
        if meta is None:
            return CacheTier.COLD
        
        frequency = meta.access_frequency()
        
        if frequency >= self._policy.hot_threshold:
            return CacheTier.HOT
        elif frequency >= self._policy.warm_threshold:
            return CacheTier.WARM
        else:
            return CacheTier.COLD
    
    def should_evict(self, key_id: str, current_size: int) -> bool:
        """
        Determine if a key should be evicted.
        
        Args:
            key_id: Key to check
            current_size: Current cache size
            
        Returns:
            True if key should be evicted
        """
        if current_size < self._policy.max_size:
            return False
        
        # If full, evict cold keys first
        tier = self.get_tier(key_id)
        
        if tier == CacheTier.COLD:
            return True
        
        # For non-cold keys, consider priority
        meta = self._key_metadata.get(key_id)
        if meta and meta.priority < 0.3:
            return True
        
        return False
    
    def get_eviction_candidates(
        self,
        count: int,
        exclude_keys: set = None
    ) -> list:
        """
        Get keys that are candidates for eviction.
        
        Args:
            count: Number of candidates to return
            exclude_keys: Keys to exclude from eviction
            
        Returns:
            List of key IDs to evict
        """
        exclude_keys = exclude_keys or set()
        
        # Sort by (tier priority, last accessed, access count)
        candidates = []
        
        for key_id, meta in self._key_metadata.items():
            if key_id in exclude_keys:
                continue
            
            # Score: lower is better for eviction
            tier_order = {CacheTier.COLD: 0, CacheTier.WARM: 1, CacheTier.HOT: 2}
            tier = self.get_tier(key_id)
            
            score = (
                tier_order[tier] * 10000 +
                meta.last_accessed * 0.1 +
                (1.0 / (meta.access_count + 1))
            )
            
            candidates.append((score, key_id, meta))
        
        # Sort by score (lower = better eviction candidate)
        candidates.sort(key=lambda x: x[0])
        
        return [c[1] for c in candidates[:count]]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get policy statistics"""
        tiers = {CacheTier.HOT: 0, CacheTier.WARM: 0, CacheTier.COLD: 0}
        
        for key_id in self._key_metadata:
            tier = self.get_tier(key_id)
            tiers[tier] += 1
        
        return {
            "total_tracked_keys": len(self._key_metadata),
            "tier_distribution": {t.value: c for t, c in tiers.items()},
            "policy": {
                "eviction": self._policy.eviction_policy.value,
                "dynamic_ttl": self._policy.enable_dynamic_ttl,
                "default_ttl": self._policy.default_ttl
            }
        }
    
    def reset(self):
        """Reset all metadata"""
        self._key_metadata.clear()
        logger.info("Cache policy metadata reset")


# Global policy manager
_policy_manager: Optional[CachePolicyManager] = None


def get_policy_manager() -> CachePolicyManager:
    """Get global policy manager"""
    global _policy_manager
    if _policy_manager is None:
        _policy_manager = CachePolicyManager()
    return _policy_manager
