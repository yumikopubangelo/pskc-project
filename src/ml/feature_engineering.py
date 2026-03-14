# ============================================================
# PSKC — Feature Engineering Module
# Extract temporal and statistical features for ML
# ============================================================
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


class FeatureEngineer:
    """
    Extracts features from key access patterns.
    Features are used for LSTM + Random Forest ensemble model.
    """
    
    def __init__(self):
        self._feature_cache = {}
        logger.info("FeatureEngineer initialized")
    
    def extract_features(
        self,
        access_data: List[Dict[str, Any]],
        key_id: str = None
    ) -> np.ndarray:
        """
        Extract feature vector from access data.
        
        Args:
            access_data: List of access events
            key_id: Optional key ID for specific feature extraction
            
        Returns:
            Feature vector as numpy array
        """
        if not access_data:
            return self._get_default_features()
        
        features = []
        
        # 1. Temporal features
        features.extend(self._extract_temporal_features(access_data))
        
        # 2. Access pattern features
        features.extend(self._extract_pattern_features(access_data))
        
        # 3. Service-related features
        features.extend(self._extract_service_features(access_data))
        
        # 4. Latency features
        features.extend(self._extract_latency_features(access_data))
        
        # 5. Frequency features
        features.extend(self._extract_frequency_features(access_data))
        
        return np.array(features, dtype=np.float32)
    
    def _get_default_features(self) -> np.ndarray:
        """Return default features when no data available"""
        return np.zeros(30, dtype=np.float32)
    
    def _extract_temporal_features(self, data: List[Dict]) -> List[float]:
        """Extract temporal patterns"""
        if not data:
            return [0.0] * 8
        
        timestamps = [d['timestamp'] for d in data]
        hours = [d.get('hour', datetime.fromtimestamp(t).hour) for d, t in zip(data, timestamps)]
        
        # Time-based features
        now = timestamps[-1] if timestamps else 0
        
        # Hour distribution (cyclical encoding)
        hour_sin = np.sin(2 * np.pi * np.mean(hours) / 24) if hours else 0
        hour_cos = np.cos(2 * np.pi * np.mean(hours) / 24) if hours else 0
        
        # Day of week
        dow = [d.get('day_of_week', datetime.fromtimestamp(t).weekday()) for d, t in zip(data, timestamps)]
        dow_sin = np.sin(2 * np.pi * np.mean(dow) / 7) if dow else 0
        dow_cos = np.cos(2 * np.pi * np.mean(dow) / 7) if dow else 0
        
        # Access frequency in last hour vs total
        last_hour = now - 3600
        last_hour_count = sum(1 for t in timestamps if t >= last_hour)
        total_count = len(timestamps)
        
        recent_freq = last_hour_count / max(total_count, 1)
        
        # Time since last access
        time_since_last = now - timestamps[-1] if timestamps else 999999
        
        # Interval statistics
        if len(timestamps) > 1:
            intervals = np.diff(timestamps)
            avg_interval = np.mean(intervals)
            std_interval = np.std(intervals)
        else:
            avg_interval = 0
            std_interval = 0
        
        return [
            hour_sin,
            hour_cos,
            dow_sin,
            dow_cos,
            recent_freq,
            time_since_last,
            avg_interval,
            std_interval
        ]
    
    def _extract_pattern_features(self, data: List[Dict]) -> List[float]:
        """Extract access pattern features"""
        if not data:
            return [0.0] * 6
        
        # Cache hit rate
        cache_hits = [d.get('cache_hit', 0) for d in data]
        cache_hit_rate = np.mean(cache_hits) if cache_hits else 0
        
        # Unique keys ratio (for sequence data)
        unique_keys = len(set(d.get('key_id', '') for d in data))
        key_diversity = unique_keys / max(len(data), 1)
        
        # Access burst detection
        timestamps = [d['timestamp'] for d in data]
        if len(timestamps) > 2:
            intervals = np.diff(timestamps)
            # Burst: intervals < 1 second
            burst_ratio = np.mean(intervals < 1.0) if len(intervals) > 0 else 0
            # Regular: intervals between 10-60 seconds
            regular_ratio = np.mean((intervals >= 10) & (intervals <= 60)) if len(intervals) > 0 else 0
        else:
            burst_ratio = 0
            regular_ratio = 0
        
        # Trend: increasing or decreasing access
        if len(timestamps) > 10:
            half = len(timestamps) // 2
            first_half = len([t for t in timestamps[:half] if t >= timestamps[0]])
            second_half = len([t for t in timestamps[half:] if t >= timestamps[half]])
            trend = (second_half - first_half) / max(first_half, 1) if first_half > 0 else 0
        else:
            trend = 0
        
        return [
            cache_hit_rate,
            key_diversity,
            burst_ratio,
            regular_ratio,
            trend,
            unique_keys
        ]
    
    def _extract_service_features(self, data: List[Dict]) -> List[float]:
        """Extract service-related features"""
        if not data:
            return [0.0] * 4
        
        # Service distribution
        services = [d.get('service_id', 'unknown') for d in data]
        unique_services = len(set(services))
        
        # Most frequent service
        service_counts = defaultdict(int)
        for s in services:
            service_counts[s] += 1
        
        top_service_ratio = max(service_counts.values()) / max(len(services), 1) if service_counts else 0
        
        # Service diversity entropy
        probs = [c / len(services) for c in service_counts.values()]
        entropy = -sum(p * np.log(p + 1e-10) for p in probs)
        
        # Cross-service access pattern
        service_switches = sum(
            1 for i in range(1, len(services))
            if services[i] != services[i-1]
        )
        switch_ratio = service_switches / max(len(services) - 1, 1)
        
        return [
            unique_services,
            top_service_ratio,
            entropy,
            switch_ratio
        ]
    
    def _extract_latency_features(self, data: List[Dict]) -> List[float]:
        """Extract latency statistics"""
        if not data:
            return [0.0] * 6
        
        latencies = [d.get('latency_ms', 0) for d in data if d.get('latency_ms', 0) > 0]
        
        if not latencies:
            return [0.0] * 6
        
        return [
            np.mean(latencies),
            np.std(latencies),
            np.min(latencies),
            np.max(latencies),
            np.percentile(latencies, 95),
            np.percentile(latencies, 99)
        ]
    
    def _extract_frequency_features(self, data: List[Dict]) -> List[float]:
        """Extract frequency-based features"""
        if not data:
            return [0.0] * 6
        
        timestamps = [d['timestamp'] for d in data]
        
        # Requests per minute
        if len(timestamps) > 1:
            duration = timestamps[-1] - timestamps[0]
            rpm = len(data) / max(duration / 60, 1)
        else:
            rpm = 0
        
        # Requests per hour
        if timestamps:
            recent_window = min(timestamps[-1] - timestamps[0], 3600)
            rph = len(data) / max(recent_window / 3600, 1)
        else:
            rph = 0
        
        # Coefficient of variation
        if len(timestamps) > 1:
            intervals = np.diff(timestamps)
            cv = np.std(intervals) / np.mean(intervals) if np.mean(intervals) > 0 else 0
        else:
            cv = 0
        
        # Recent activity (last 5 minutes)
        if timestamps:
            recent_window = timestamps[-1] - 300
            recent_count = sum(1 for t in timestamps if t >= recent_window)
        else:
            recent_count = 0
        
        # Short-term vs long-term ratio
        short_term = sum(1 for t in timestamps if t >= timestamps[-1] - 600)
        long_term = len(timestamps)
        short_term_ratio = short_term / max(long_term, 1)
        
        return [
            rpm,
            rph,
            cv,
            recent_count,
            short_term_ratio,
            len(data)  # Total events in window
        ]
    
    def create_sequences(
        self,
        data: List[Dict[str, Any]],
        sequence_length: int = 20,
        stride: int = 1
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Create sequences for LSTM training.
        
        Args:
            data: Access events
            sequence_length: Length of each sequence
            stride: Step between sequences
            
        Returns:
            Tuple of (X, y) where X is sequences and y is next key
        """
        if len(data) < sequence_length + 1:
            return np.array([]), np.array([])
        
        # Encode keys
        key_to_idx = {}
        idx_counter = 0
        
        def get_key_idx(key_id):
            nonlocal idx_counter
            if key_id not in key_to_idx:
                key_to_idx[key_id] = idx_counter
                idx_counter += 1
            return key_to_idx[key_id]
        sequences_x = []
        sequences_y = []
        
        for i in range(0, len(data) - sequence_length, stride):
            seq_data = data[i:i+sequence_length]
            next_key = data[i+sequence_length]['key_id']
            
            # Extract features for sequence
            features = self.extract_features(seq_data)
            sequences_x.append(features)
            sequences_y.append(get_key_idx(next_key))
        
        return np.array(sequences_x), np.array(sequences_y)
    
    def get_feature_names(self) -> List[str]:
        """Get list of feature names"""
        return [
            # Temporal (8)
            "hour_sin", "hour_cos", "dow_sin", "dow_cos",
            "recent_freq", "time_since_last", "avg_interval", "interval_std",
            # Pattern (6)
            "cache_hit_rate", "key_diversity", "burst_ratio",
            "regular_ratio", "trend", "unique_keys",
            # Service (4)
            "unique_services", "top_service_ratio", "entropy", "switch_ratio",
            # Latency (6)
            "latency_mean", "latency_std", "latency_min", "latency_max",
            "latency_p95", "latency_p99",
            # Frequency (6)
            "rpm", "rph", "cv", "recent_count", "short_term_ratio", "total_events"
        ]


# Global feature engineer instance
_feature_engineer: Optional[FeatureEngineer] = None


def get_feature_engineer() -> FeatureEngineer:
    """Get global feature engineer"""
    global _feature_engineer
    if _feature_engineer is None:
        _feature_engineer = FeatureEngineer()
    return _feature_engineer
