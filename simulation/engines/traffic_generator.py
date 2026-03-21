# ============================================================
# PSKC — Traffic Generator
# Realistic traffic patterns (bursty, peak, seasonal)
# ============================================================
import numpy as np
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class TrafficParams:
    """Traffic pattern parameters"""
    base_rps: float          # Base requests per second
    peak_multiplier: float   # Multiplier during peak hours
    peak_start_hour: int     # Hour when peak starts (0-23)
    peak_end_hour: int       # Hour when peak ends (0-23)
    burst_probability: float # Probability of burst
    burst_size: int          # Size of burst
    seasonality: bool         # Enable daily seasonality
    
    @classmethod
    def spotify(cls) -> 'TrafficParams':
        """Spotify-like traffic pattern"""
        return cls(
            base_rps=1000.0,
            peak_multiplier=5.0,
            peak_start_hour=18,
            peak_end_hour=23,
            burst_probability=0.3,
            burst_size=50,
            seasonality=True
        )
    
    @classmethod
    def netflix(cls) -> 'TrafficParams':
        """Netflix-like traffic pattern"""
        return cls(
            base_rps=5000.0,
            peak_multiplier=3.0,
            peak_start_hour=19,
            peak_end_hour=23,
            burst_probability=0.2,
            burst_size=100,
            seasonality=True
        )
    
    @classmethod
    def aws_kms(cls) -> 'TrafficParams':
        """AWS KMS-like traffic"""
        return cls(
            base_rps=100.0,
            peak_multiplier=2.0,
            peak_start_hour=9,
            peak_end_hour=17,
            burst_probability=0.1,
            burst_size=20,
            seasonality=True
        )

    @classmethod
    def normal_day(cls) -> 'TrafficParams':
        """Normal day traffic for a typical web service."""
        return cls(
            base_rps=200.0,
            peak_multiplier=3.0,
            peak_start_hour=14,
            peak_end_hour=17,
            burst_probability=0.1,
            burst_size=10,
            seasonality=True
        )

    @classmethod
    def heavy_load(cls) -> 'TrafficParams':
        """Sustained heavy load, like a launch day."""
        return cls(
            base_rps=1000.0,
            peak_multiplier=2.0,  # Already high base
            peak_start_hour=9,
            peak_end_hour=18,
            burst_probability=0.2,
            burst_size=50,
            seasonality=False # Sustained
        )

    @classmethod
    def prime_time(cls) -> 'TrafficParams':
        """Peak usage in the evening, e.g. streaming service."""
        return cls(
            base_rps=800.0,
            peak_multiplier=4.0,
            peak_start_hour=19,
            peak_end_hour=23,
            burst_probability=0.15,
            burst_size=80,
            seasonality=True
        )

    @classmethod
    def overload_degradation(cls) -> 'TrafficParams':
        """Extreme traffic causing system degradation."""
        return cls(
            base_rps=2000.0,
            peak_multiplier=5.0,
            peak_start_hour=0, # All day
            peak_end_hour=23,
            burst_probability=0.5, # Very bursty
            burst_size=200,
            seasonality=False
        )


class TrafficGenerator:
    """
    Generates realistic traffic patterns for simulation.
    Models burstiness, peak hours, and daily seasonality.
    """
    
    def __init__(
        self,
        params: TrafficParams = None,
        profile: str = "spotify"
    ):
        """
        Initialize traffic generator.
        
        Args:
            params: Traffic parameters (or use profile preset)
            profile: Preset profile name
        """
        if params is None:
            params = self._get_profile(profile)
        
        self._params = params
        self._start_time = datetime.now()
        
        # State
        self._total_requests = 0
        self._current_rps = params.base_rps
        
        logger.info(f"TrafficGenerator initialized: profile={profile}, base_rps={params.base_rps}")
    
    def _get_profile(self, profile: str) -> TrafficParams:
        """Get preset traffic profile"""
        profiles = {
            "normal": TrafficParams.normal_day(),
            "heavy": TrafficParams.heavy_load(),
            "prime_time": TrafficParams.prime_time(),
            "overload": TrafficParams.overload_degradation(),
            "spotify": TrafficParams.spotify(),
            "netflix": TrafficParams.netflix(),
            "aws": TrafficParams.aws_kms(),
            "constant": TrafficParams(
                base_rps=100.0,
                peak_multiplier=1.0,
                peak_start_hour=0,
                peak_end_hour=23,
                burst_probability=0.0,
                burst_size=0,
                seasonality=False
            )
        }
        return profiles.get(profile, TrafficParams.normal_day())
    
    def get_current_rps(self, timestamp: datetime = None) -> float:
        """
        Calculate RPS at given time.
        
        Args:
            timestamp: Time to calculate for (default: now)
            
        Returns:
            Requests per second
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        hour = timestamp.hour
        
        # Base RPS
        rps = self._params.base_rps
        
        # Peak multiplier
        if self._params.peak_start_hour <= hour < self._params.peak_end_hour:
            rps *= self._params.peak_multiplier
        
        # Seasonality (smooth variation)
        if self._params.seasonality:
            # Add some variation based on hour
            hour_factor = 0.5 + 0.5 * np.sin(2 * np.pi * hour / 24)
            rps *= hour_factor
        
        self._current_rps = rps
        return rps
    
    def generate_interval(self) -> float:
        """
        Generate time interval between requests (in seconds).
        
        Returns:
            Interval in seconds
        """
        rps = self.get_current_rps()
        
        if rps <= 0:
            return float('inf')
        
        # Check for burst
        if np.random.random() < self._params.burst_probability:
            # Return small interval (burst)
            interval = 1.0 / (rps * self._params.burst_size)
        else:
            # Exponential distribution for Poisson process
            interval = np.random.exponential(1.0 / rps)
        
        self._total_requests += 1
        return max(interval, 0.001)  # Minimum 1ms
    
    def generate_batch(self, n: int) -> List[float]:
        """Generate n request intervals"""
        return [self.generate_interval() for _ in range(n)]
    
    def get_hourly_distribution(self, hours: int = 24) -> Dict[int, float]:
        """
        Get expected RPS for each hour.
        
        Args:
            hours: Number of hours to generate
            
        Returns:
            Dict of hour -> RPS
        """
        distribution = {}
        
        for hour in range(hours):
            test_time = datetime.now().replace(hour=hour, minute=0, second=0)
            distribution[hour] = self.get_current_rps(test_time)
        
        return distribution
    
    def simulate_traffic_stream(
        self,
        duration_seconds: int,
        callback: Callable[[int, float], None] = None
    ) -> List[Tuple[float, int]]:
        """
        Simulate traffic stream over time.
        
        Args:
            duration_seconds: Duration to simulate
            callback: Optional callback(request_count, timestamp)
            
        Returns:
            List of (timestamp, cumulative_requests)
        """
        events = []
        current_time = 0.0
        request_count = 0
        
        while current_time < duration_seconds:
            interval = self.generate_interval()
            current_time += interval
            
            if current_time < duration_seconds:
                request_count += 1
                events.append((current_time, request_count))
                
                if callback:
                    callback(request_count, current_time)
        
        self._total_requests = request_count
        return events
    
    @property
    def total_requests(self) -> int:
        return self._total_requests
    
    @property
    def current_rps(self) -> float:
        return self._current_rps
    
    @property
    def params(self) -> TrafficParams:
        return self._params


class AccessPatternGenerator:
    """
    Generates key access patterns based on traffic.
    Models hot keys, cold keys, and access correlations.
    """
    
    def __init__(
        self,
        num_keys: int = 1000,
        hot_key_ratio: float = 0.2
    ):
        """
        Initialize access pattern generator.
        
        Args:
            num_keys: Total number of keys
            hot_key_ratio: Ratio of hot (frequently accessed) keys
        """
        self._num_keys = num_keys
        self._hot_key_ratio = hot_key_ratio
        
        # Create key popularity (Zipf distribution)
        self._key_weights = self._generate_zipf_weights()
        
        logger.info(f"AccessPatternGenerator initialized: {num_keys} keys, {hot_key_ratio*100}% hot")
    
    def _generate_zipf_weights(self) -> np.ndarray:
        """Generate Zipf-distributed key weights"""
        # Zipf distribution: popularity follows power law
        ranks = np.arange(1, self._num_keys + 1)
        weights = 1.0 / (ranks ** 1.5)  # Zipf exponent
        
        # Normalize
        weights = weights / weights.sum()
        
        return weights
    
    def sample_keys(
        self,
        n: int,
        hot_weight: float = None
    ) -> List[str]:
        """
        Sample keys based on popularity.
        
        Args:
            n: Number of keys to sample
            hot_weight: Additional weight for hot keys
            
        Returns:
            List of key IDs
        """
        if hot_weight is not None:
            # Adjust weights for hot key preference
            weights = self._key_weights.copy()
            hot_count = int(self._num_keys * self._hot_key_ratio)
            weights[:hot_count] *= (1 + hot_weight)
            weights = weights / weights.sum()
        else:
            weights = self._key_weights
        
        # Sample
        indices = np.random.choice(
            self._num_keys,
            size=n,
            p=weights,
            replace=True
        )
        
        return [f"key_{i}" for i in indices]
    
    def generate_access_sequence(
        self,
        n: int,
        temporal_correlation: float = 0.5
    ) -> List[str]:
        """
        Generate access sequence with temporal correlation.
        
        Args:
            n: Number of accesses
            temporal_correlation: How correlated consecutive accesses are
            
        Returns:
            List of key IDs in access order
        """
        keys = []
        
        # Start with random key
        current_key = np.random.choice(self._num_keys)
        
        for _ in range(n):
            # Decide whether to stay with current or switch
            if np.random.random() < temporal_correlation:
                # Stay with current (high correlation)
                keys.append(f"key_{current_key}")
            else:
                # Switch to new key based on popularity
                new_key = np.random.choice(
                    self._num_keys,
                    p=self._key_weights
                )
                current_key = new_key
                keys.append(f"key_{new_key}")
        
        return keys


class CompositeTrafficSimulator:
    """
    Combines traffic generation with access patterns.
    """
    
    def __init__(
        self,
        traffic_profile: str = "spotify",
        num_keys: int = 1000
    ):
        self._traffic = TrafficGenerator(profile=traffic_profile)
        self._access = AccessPatternGenerator(num_keys=num_keys)
        
        self._results = []
    
    def run(
        self,
        duration_seconds: int,
        collect_latency: bool = False
    ) -> Dict:
        """
        Run simulation.
        
        Args:
            duration_seconds: How long to simulate
            collect_latency: Whether to collect latency stats
            
        Returns:
            Simulation results
        """
        from simulation.engines.latency_engine import get_latency_engine
        
        latency_engine = get_latency_engine()
        
        # Run traffic stream
        events = self._traffic.simulate_traffic_stream(duration_seconds)
        
        # Generate key accesses
        access_sequence = self._access.generate_access_sequence(
            len(events),
            temporal_correlation=0.7
        )
        
        # Collect results
        results = {
            "duration": duration_seconds,
            "total_requests": len(events),
            "avg_rps": len(events) / duration_seconds,
            "access_sequence": access_sequence
        }
        
        if collect_latency:
            latencies = latency_engine.sample(len(events))
            results["latencies"] = latencies
            results["avg_latency"] = float(np.mean(latencies))
            results["p95_latency"] = float(np.percentile(latencies, 95))
            results["p99_latency"] = float(np.percentile(latencies, 99))
        
        self._results.append(results)
        return results
    
    @property
    def traffic_generator(self) -> TrafficGenerator:
        return self._traffic
    
    @property
    def access_generator(self) -> AccessPatternGenerator:
        return self._access


# Global instances
_traffic_generator: Optional[TrafficGenerator] = None
_access_pattern_generator: Optional[AccessPatternGenerator] = None


def get_traffic_generator(profile: str = "spotify") -> TrafficGenerator:
    """Get global traffic generator"""
    global _traffic_generator
    if _traffic_generator is None:
        _traffic_generator = TrafficGenerator(profile=profile)
    return _traffic_generator


def get_access_pattern_generator(num_keys: int = 1000) -> AccessPatternGenerator:
    """Get global access pattern generator"""
    global _access_pattern_generator
    if _access_pattern_generator is None:
        _access_pattern_generator = AccessPatternGenerator(num_keys=num_keys)
    return _access_pattern_generator
