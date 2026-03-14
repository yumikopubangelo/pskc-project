# ============================================================
# PSKC — Cache Module Tests
# ============================================================
import pytest
import time
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cache.local_cache import LocalCache, CacheEntry
from src.cache.cache_policy import CachePolicy, CachePolicyManager, EvictionPolicy
from src.security.encryption import AES256Encryptor


class TestLocalCache:
    """Test cases for LocalCache"""
    
    def test_cache_set_and_get(self):
        """Test basic set and get operations"""
        cache = LocalCache(max_size=100, default_ttl=60)
        
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"
    
    def test_cache_miss(self):
        """Test cache miss returns None"""
        cache = LocalCache(max_size=100, default_ttl=60)
        
        assert cache.get("nonexistent") is None
    
    def test_cache_expiry(self):
        """Test cache entry expiry"""
        cache = LocalCache(max_size=100, default_ttl=1)
        
        cache.set("key1", "value1")
        
        # Wait for expiry
        time.sleep(1.5)
        
        assert cache.get("key1") is None
    
    def test_cache_delete(self):
        """Test cache deletion"""
        cache = LocalCache(max_size=100, default_ttl=60)
        
        cache.set("key1", "value1")
        assert cache.delete("key1") is True
        assert cache.get("key1") is None
    
    def test_cache_lru_eviction(self):
        """Test LRU eviction when cache is full"""
        cache = LocalCache(max_size=3, default_ttl=60)
        
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")
        
        # This should evict key1
        cache.set("key4", "value4")
        
        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"
    
    def test_cache_stats(self):
        """Test cache statistics"""
        cache = LocalCache(max_size=100, default_ttl=60)
        
        cache.set("key1", "value1")
        cache.get("key1")  # hit
        cache.get("key2")  # miss
        
        stats = cache.get_stats()
        
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 1
    
    def test_cache_clear(self):
        """Test cache clear"""
        cache = LocalCache(max_size=100, default_ttl=60)
        
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        
        cache.clear()
        
        assert cache.get("key1") is None
        assert cache.get_stats()["size"] == 0


class TestCachePolicy:
    """Test cases for CachePolicy"""
    
    def test_policy_ttl_hot_key(self):
        """Test TTL for hot keys"""
        policy = CachePolicy()
        manager = CachePolicyManager(policy)
        
        # Simulate frequent access
        for _ in range(100):
            manager.update_key_access("hot_key")
        
        ttl = manager.get_ttl("hot_key")
        
        assert ttl >= policy.warm_ttl
    
    def test_policy_ttl_cold_key(self):
        """Test TTL for cold keys"""
        policy = CachePolicy()
        manager = CachePolicyManager(policy)
        
        # Single access
        manager.update_key_access("cold_key")
        
        ttl = manager.get_ttl("cold_key")
        
        assert ttl <= policy.cold_ttl
    
    def test_priority_boost(self):
        """Test ML priority boosting"""
        policy = CachePolicy()
        manager = CachePolicyManager(policy)
        
        manager.update_key_access("key1")
        manager.set_key_priority("key1", 0.9)
        
        ttl = manager.get_ttl("key1")
        
        # Should have longer TTL due to high priority
        assert ttl >= policy.default_ttl
    
    def test_eviction_candidates(self):
        """Test eviction candidate selection"""
        policy = CachePolicy(max_size=10)
        manager = CachePolicyManager(policy)
        
        # Add some keys
        for i in range(15):
            manager.update_key_access(f"key_{i}")
        
        candidates = manager.get_eviction_candidates(5)
        
        assert len(candidates) <= 5


class TestCacheEntry:
    """Test cases for CacheEntry"""
    
    def test_is_expired(self):
        """Test expiry check"""
        entry = CacheEntry(key="key1", value="value1", ttl=1)
        
        assert entry.is_expired() is False
        
        time.sleep(1.5)
        
        assert entry.is_expired() is True
    
    def test_touch(self):
        """Test touch updates access time"""
        entry = CacheEntry(key="key1", value="value1")
        
        initial_access = entry.access_count
        entry.touch()
        
        assert entry.access_count == initial_access + 1


class TestEncryption:
    """Test cases for encryption integration"""
    
    def test_encrypt_decrypt(self):
        """Test encryption and decryption"""
        key = "test_key_32_characters_long!!"
        encryptor = AES256Encryptor(key)
        
        original = b"secret_key_data_here"
        
        encrypted = encryptor.encrypt_hex(original)
        decrypted = encryptor.decrypt_hex(encrypted)
        
        assert decrypted == original
    
    def test_different_ivs(self):
        """Test that different IVs produce different ciphertext"""
        key = "test_key_32_characters_long!!"
        encryptor = AES256Encryptor(key)
        
        plaintext = b"same_data"
        
        encrypted1, _ = encryptor.encrypt(plaintext)
        encrypted2, _ = encryptor.encrypt(plaintext)
        
        # Should be different due to random IV
        assert encrypted1 != encrypted2
    
    def test_invalid_key_length(self):
        """Test invalid key length raises error"""
        with pytest.raises(ValueError):
            AES256Encryptor("short_key")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
