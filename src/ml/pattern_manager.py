# ============================================================
# PSKC — Pattern Manager for Redis
# ============================================================
"""
Manages safe pattern extraction and storage for non-sensitive data.
Patterns are learned from user behavior and stored in Redis with TTL.
"""

import json
import logging
from typing import Dict, List, Optional, Set, Tuple, Any
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import redis
from config.settings import settings

logger = logging.getLogger(__name__)


class PatternManager:
    """
    Manages pattern extraction and storage in Redis.
    
    Safe patterns extracted:
    - Page access frequency (which pages accessed, how often)
    - Time-based patterns (peak hours, off-hours access)
    - Sequential patterns (page navigation sequences)
    - Cache hit/miss patterns
    - NOT: passwords, tokens, sensitive credentials
    """
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        """
        Initialize PatternManager.
        
        Args:
            redis_client: Redis client instance (optional, will create if not provided)
        """
        self.redis = redis_client or self._get_redis_client()
        self.pattern_ttl = 86400 * 7  # 7 days retention for patterns
        self.prefix = "pskc:patterns"
    
    def _get_redis_client(self) -> redis.Redis:
        """Get or create Redis client."""
        try:
            return redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                db=settings.redis_db or 0,
                decode_responses=True
            )
        except Exception as e:
            logger.error(f"Failed to create Redis client: {e}")
            raise
    
    def extract_page_access_pattern(
        self,
        session_id: str,
        pages_accessed: List[str]
    ) -> Dict[str, Any]:
        """
        Extract page access pattern from session.
        
        Args:
            session_id: Session identifier
            pages_accessed: List of pages accessed in order
            
        Returns:
            Pattern dict with frequency and probabilities
        """
        if not pages_accessed:
            return {}
        
        pattern = {
            "pages": pages_accessed,
            "unique_pages": len(set(pages_accessed)),
            "total_accesses": len(pages_accessed),
            "timestamp": datetime.utcnow().isoformat(),
            "page_frequency": dict(Counter(pages_accessed)),
            "access_sequence": pages_accessed[-10:],  # Last 10 pages
        }
        
        # Calculate transition probabilities
        transitions = defaultdict(Counter)
        for i in range(len(pages_accessed) - 1):
            transitions[pages_accessed[i]][pages_accessed[i + 1]] += 1
        
        pattern["page_transitions"] = {
            page: dict(next_counter)
            for page, next_counter in transitions.items()
        }
        
        return pattern
    
    def extract_temporal_pattern(
        self,
        session_id: str,
        access_times: List[datetime]
    ) -> Dict[str, Any]:
        """
        Extract time-based access patterns.
        
        Args:
            session_id: Session identifier
            access_times: List of access timestamps
            
        Returns:
            Pattern dict with temporal statistics
        """
        if not access_times:
            return {}
        
        hours_accessed = [t.hour for t in access_times]
        hour_frequency = Counter(hours_accessed)
        
        pattern = {
            "hours_accessed": list(hour_frequency.keys()),
            "hour_frequency": dict(hour_frequency),
            "peak_hours": sorted(
                hour_frequency.items(),
                key=lambda x: x[1],
                reverse=True
            )[:3],  # Top 3 peak hours
            "off_peak_hours": sorted(
                hour_frequency.items(),
                key=lambda x: x[1]
            )[:3],  # Top 3 off-peak hours
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        # Calculate inter-request time (request frequency)
        if len(access_times) > 1:
            time_deltas = [
                (access_times[i+1] - access_times[i]).total_seconds()
                for i in range(len(access_times) - 1)
            ]
            pattern["avg_request_interval_seconds"] = sum(time_deltas) / len(time_deltas)
            pattern["min_request_interval_seconds"] = min(time_deltas)
            pattern["max_request_interval_seconds"] = max(time_deltas)
        
        return pattern
    
    def extract_cache_hit_pattern(
        self,
        session_id: str,
        cache_operations: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Extract cache hit/miss patterns.
        
        Args:
            session_id: Session identifier
            cache_operations: List of cache operation dicts with 'key' and 'hit' fields
            
        Returns:
            Pattern dict with hit/miss statistics
        """
        if not cache_operations:
            return {}
        
        total_ops = len(cache_operations)
        hits = sum(1 for op in cache_operations if op.get('hit', False))
        misses = total_ops - hits
        
        hit_rate = hits / total_ops if total_ops > 0 else 0
        
        # Keys hit frequently
        hit_keys = [op['key'] for op in cache_operations if op.get('hit')]
        key_hit_frequency = Counter(hit_keys)
        
        pattern = {
            "total_operations": total_ops,
            "hits": hits,
            "misses": misses,
            "hit_rate": hit_rate,
            "miss_rate": 1.0 - hit_rate,
            "frequently_hit_keys": dict(key_hit_frequency.most_common(10)),
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        return pattern
    
    def store_pattern(
        self,
        version_id: int,
        pattern_type: str,
        pattern_key: str,
        pattern_data: Dict[str, Any]
    ) -> bool:
        """
        Store pattern in Redis.
        
        Args:
            version_id: Model version ID for versioning patterns
            pattern_type: Type of pattern (page_access, temporal, cache_hit, etc)
            pattern_key: Key identifier (session_id, user_id, etc)
            pattern_data: Pattern data dictionary
            
        Returns:
            True if successful, False otherwise
        """
        try:
            redis_key = f"{self.prefix}:{version_id}:{pattern_type}:{pattern_key}"
            
            # Store with TTL
            self.redis.setex(
                redis_key,
                self.pattern_ttl,
                json.dumps(pattern_data)
            )
            
            # Also store in a set of all patterns for this version/type
            index_key = f"{self.prefix}:{version_id}:{pattern_type}:keys"
            self.redis.sadd(index_key, pattern_key)
            self.redis.expire(index_key, self.pattern_ttl)
            
            return True
        except Exception as e:
            logger.error(f"Failed to store pattern {pattern_type}:{pattern_key}: {e}")
            return False
    
    def get_pattern(
        self,
        version_id: int,
        pattern_type: str,
        pattern_key: str
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve pattern from Redis.
        
        Args:
            version_id: Model version ID
            pattern_type: Type of pattern
            pattern_key: Key identifier
            
        Returns:
            Pattern dictionary or None if not found
        """
        try:
            redis_key = f"{self.prefix}:{version_id}:{pattern_type}:{pattern_key}"
            data = self.redis.get(redis_key)
            return json.loads(data) if data else None
        except Exception as e:
            logger.error(f"Failed to get pattern {pattern_type}:{pattern_key}: {e}")
            return None
    
    def get_all_patterns(
        self,
        version_id: int,
        pattern_type: str
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get all patterns for a specific version and type.
        
        Args:
            version_id: Model version ID
            pattern_type: Type of pattern
            
        Returns:
            Dictionary mapping pattern_key to pattern_data
        """
        try:
            index_key = f"{self.prefix}:{version_id}:{pattern_type}:keys"
            keys = self.redis.smembers(index_key)
            
            patterns = {}
            for key in keys:
                pattern = self.get_pattern(version_id, pattern_type, key)
                if pattern:
                    patterns[key] = pattern
            
            return patterns
        except Exception as e:
            logger.error(f"Failed to get all patterns for {pattern_type}: {e}")
            return {}
    
    def delete_pattern(
        self,
        version_id: int,
        pattern_type: str,
        pattern_key: str
    ) -> bool:
        """
        Delete a specific pattern from Redis.
        
        Args:
            version_id: Model version ID
            pattern_type: Type of pattern
            pattern_key: Key identifier
            
        Returns:
            True if successful, False otherwise
        """
        try:
            redis_key = f"{self.prefix}:{version_id}:{pattern_type}:{pattern_key}"
            index_key = f"{self.prefix}:{version_id}:{pattern_type}:keys"
            
            self.redis.delete(redis_key)
            self.redis.srem(index_key, pattern_key)
            
            return True
        except Exception as e:
            logger.error(f"Failed to delete pattern {pattern_type}:{pattern_key}: {e}")
            return False
    
    def cleanup_patterns(
        self,
        version_id: int,
        pattern_type: Optional[str] = None
    ) -> int:
        """
        Clean up patterns for a specific version.
        
        Args:
            version_id: Model version ID
            pattern_type: Specific pattern type to clean (optional, all if None)
            
        Returns:
            Number of patterns deleted
        """
        try:
            deleted_count = 0
            
            # Get all keys for this version
            if pattern_type:
                pattern_types = [pattern_type]
            else:
                # Scan for all pattern types
                scan_pattern = f"{self.prefix}:{version_id}:*:keys"
                cursor = 0
                pattern_types_set = set()
                
                while True:
                    cursor, keys = self.redis.scan(cursor, match=scan_pattern)
                    for key in keys:
                        # Extract pattern type from key
                        parts = key.split(":")
                        if len(parts) >= 4:
                            pattern_types_set.add(parts[3])
                    if cursor == 0:
                        break
                
                pattern_types = list(pattern_types_set)
            
            # Delete all patterns of each type
            for ptype in pattern_types:
                patterns = self.get_all_patterns(version_id, ptype)
                for key in patterns.keys():
                    if self.delete_pattern(version_id, ptype, key):
                        deleted_count += 1
            
            return deleted_count
        except Exception as e:
            logger.error(f"Failed to cleanup patterns for version {version_id}: {e}")
            return 0
    
    def calculate_pattern_statistics(
        self,
        patterns: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Calculate aggregate statistics from multiple patterns.
        
        Args:
            patterns: Dictionary of patterns
            
        Returns:
            Statistics dictionary
        """
        if not patterns:
            return {}
        
        # Calculate average hit rate
        hit_rates = [
            p.get("hit_rate", 0) for p in patterns.values()
            if "hit_rate" in p
        ]
        avg_hit_rate = sum(hit_rates) / len(hit_rates) if hit_rates else 0
        
        # Most common pages across all patterns
        all_pages = []
        for p in patterns.values():
            if "page_frequency" in p:
                all_pages.extend(p["page_frequency"].keys())
        
        page_frequency = Counter(all_pages)
        
        # Most common hours
        all_hours = []
        for p in patterns.values():
            if "hours_accessed" in p:
                all_hours.extend(p["hours_accessed"])
        
        hour_frequency = Counter(all_hours)
        
        return {
            "total_patterns": len(patterns),
            "avg_hit_rate": avg_hit_rate,
            "most_common_pages": dict(page_frequency.most_common(10)),
            "peak_hours": sorted(
                hour_frequency.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5],
            "calculated_at": datetime.utcnow().isoformat(),
        }
    
    def compare_patterns(
        self,
        patterns_v1: Dict[str, Dict[str, Any]],
        patterns_v2: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Compare patterns between two versions.
        
        Args:
            patterns_v1: Patterns from version 1
            patterns_v2: Patterns from version 2
            
        Returns:
            Comparison statistics
        """
        stats_v1 = self.calculate_pattern_statistics(patterns_v1)
        stats_v2 = self.calculate_pattern_statistics(patterns_v2)
        
        return {
            "version_1": stats_v1,
            "version_2": stats_v2,
            "hit_rate_diff": (
                stats_v2.get("avg_hit_rate", 0) - stats_v1.get("avg_hit_rate", 0)
            ),
            "comparison_timestamp": datetime.utcnow().isoformat(),
        }
