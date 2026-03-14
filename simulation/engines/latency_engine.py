# ============================================================
# PSKC — Latency Engine
# Log-normal latency generator based on production data
# ============================================================
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class LatencyParams:
    """Latency distribution parameters"""
    mean_ms: float       # Average latency in ms
    p95_ms: float        # 95th percentile
    p99_ms: float        # 99th percentile
    std_dev: float       # Standard deviation
    
    @classmethod
    def from_percentiles(cls, mean: float, p95: float, p99: float) -> 'LatencyParams':
        """Create params from percentiles using log-normal approximation"""
        # For log-normal: 
        # mean = exp(mu + sigma^2/2)
        # We estimate sigma from percentiles
        
        # Use ratio between percentiles to estimate sigma
        ratio_p95 = p99 / p95
        
        # Estimate sigma (simplified)
        sigma = np.log(ratio_p95) / 1.645  # Approximate
        
        # Calculate mu
        mu = np.log(mean) - (sigma ** 2) / 2
        
        # Calculate actual std dev
        variance = (np.exp(sigma ** 2) - 1) * np.exp(2 * mu + sigma ** 2)
        std_dev = np.sqrt(variance)
        
        return cls(
            mean_ms=mean,
            p95_ms=p95,
            p99_ms=p99,
            std_dev=std_dev
        )


class LatencyEngine:
    """
    Generates realistic latency samples using log-normal distribution.
    Based on parameters from production systems (Spotify, AWS, Netflix).
    """
    
    # Pre-defined latency profiles from production systems
    PROFILES = {
        "spotify_padlock": LatencyParams(
            mean_ms=5.0,      # Cache hit
            p95_ms=8.0,
            p99_ms=12.0,
            std_dev=2.5
        ),
        "spotify_padlock_no_cache": LatencyParams(
            mean_ms=15.0,     # No cache
            p95_ms=20.0,
            p99_ms=25.0,
            std_dev=4.0
        ),
        "aws_kms": LatencyParams(
            mean_ms=85.0,     # AWS KMS baseline
            p95_ms=150.0,
            p99_ms=250.0,
            std_dev=45.0
        ),
        "aws_kms_throttled": LatencyParams(
            mean_ms=250.0,    # Throttled
            p95_ms=400.0,
            p99_ms=500.0,
            std_dev=120.0
        ),
        "netflix_zuul": LatencyParams(
            mean_ms=197.0,    # Netflix baseline (MDPI)
            p95_ms=270.0,
            p99_ms=320.0,
            std_dev=80.0
        ),
        "netflix_zuul_prime": LatencyParams(
            mean_ms=250.0,    # Prime time
            p95_ms=350.0,
            p99_ms=450.0,
            std_dev=100.0
        ),
        "pskc_cached": LatencyParams(
            mean_ms=2.0,      # PSKC with cache hit
            p95_ms=5.0,
            p99_ms=8.0,
            std_dev=1.5
        ),
        "pskc_prefetch": LatencyParams(
            mean_ms=10.0,     # PSKC with prefetch
            p95_ms=18.0,
            p99_ms=25.0,
            std_dev=5.0
        ),
        "baseline": LatencyParams(
            mean_ms=197.0,    # MDPI baseline
            p95_ms=270.0,
            p99_ms=320.0,
            std_dev=80.0
        )
    }
    
    def __init__(self, profile: str = "baseline"):
        """
        Initialize latency engine.
        
        Args:
            profile: Name of latency profile to use
        """
        self._profile_name = profile
        self._params = self.PROFILES.get(profile, self.PROFILES["baseline"])
        self._mu = None
        self._sigma = None
        self._fit_log_normal()
        
        logger.info(f"LatencyEngine initialized: profile={profile}, mean={self._params.mean_ms}ms")
    
    def _fit_log_normal(self):
        """Fit log-normal distribution to parameters"""
        mean = self._params.mean_ms
        std = self._params.std_dev
        
        # Convert to log-normal parameters
        # mu = ln(mean^2 / sqrt(mean^2 + std^2))
        # sigma = sqrt(ln(1 + std^2 / mean^2))
        
        cv = std / mean  # Coefficient of variation
        self._sigma = np.sqrt(np.log(1 + cv ** 2))
        self._mu = np.log(mean) - (self._sigma ** 2) / 2
    
    def sample(self, n: int = 1) -> np.ndarray:
        """
        Generate latency samples.
        
        Args:
            n: Number of samples
            
        Returns:
            Array of latency values in milliseconds
        """
        samples = np.random.lognormal(self._mu, self._sigma, n)
        
        # Ensure minimum latency (network overhead)
        samples = np.maximum(samples, 0.5)
        
        return samples
    
    def sample_single(self) -> float:
        """Generate a single latency sample"""
        return float(self.sample(1)[0])
    
    def get_percentiles(self, n: int = 10000) -> Dict[str, float]:
        """
        Get percentiles for current profile.
        
        Args:
            n: Number of samples for estimation
            
        Returns:
            Dict with percentiles
        """
        samples = self.sample(n)
        
        return {
            "p50": float(np.percentile(samples, 50)),
            "p95": float(np.percentile(samples, 95)),
            "p99": float(np.percentile(samples, 99)),
            "mean": float(np.mean(samples)),
            "std": float(np.std(samples)),
            "min": float(np.min(samples)),
            "max": float(np.max(samples))
        }
    
    def set_profile(self, profile: str):
        """Change latency profile"""
        if profile not in self.PROFILES:
            logger.warning(f"Unknown profile: {profile}")
            return
        
        self._profile_name = profile
        self._params = self.PROFILES[profile]
        self._fit_log_normal()
        
        logger.info(f"Latency profile changed to: {profile}")
    
    @property
    def params(self) -> LatencyParams:
        return self._params
    
    @property
    def profile_name(self) -> str:
        return self._profile_name


class CompositeLatencyEngine:
    """
    Composite engine that simulates different scenarios.
    Mixes cache hits/misses, throttling, etc.
    """
    
    def __init__(self):
        self._engines = {
            name: LatencyEngine(name)
            for name in self.PROFILES.keys()
        }
        
        # Default probabilities for composite scenarios
        self._scenario_probs = {
            "cache_hit": 0.8,
            "cache_miss": 0.1,
            "throttled": 0.1
        }
        
        self._current_scenario = "normal"
    
    def set_scenario(self, scenario: str):
        """Set the current scenario"""
        self._current_scenario = scenario
        
        if scenario == "normal":
            self._scenario_probs = {"cache_hit": 0.8, "cache_miss": 0.1, "throttled": 0.1}
        elif scenario == "heavy_load":
            self._scenario_probs = {"cache_hit": 0.6, "cache_miss": 0.2, "throttled": 0.2}
        elif scenario == "prime_time":
            self._scenario_probs = {"cache_hit": 0.5, "cache_miss": 0.3, "throttled": 0.2}
        elif scenario == "degraded":
            self._scenario_probs = {"cache_hit": 0.3, "cache_miss": 0.3, "throttled": 0.4}
    
    def sample_with_scenario(self, n: int = 1) -> Tuple[np.ndarray, Dict]:
        """
        Generate samples based on current scenario.
        
        Returns:
            Tuple of (samples, scenario_info)
        """
        samples = []
        scenario_info = {}
        
        for _ in range(n):
            # Determine which type of request
            rand = np.random.random()
            
            if rand < self._scenario_probs["cache_hit"]:
                sample = self._engines["pskc_cached"].sample_single()
                scenario = "cache_hit"
            elif rand < self._scenario_probs["cache_hit"] + self._scenario_probs["cache_miss"]:
                sample = self._engines["pskc_prefetch"].sample_single()
                scenario = "cache_miss"
            else:
                sample = self._engines["aws_kms_throttled"].sample_single()
                scenario = "throttled"
            
            samples.append(sample)
            scenario_info[scenario] = scenario_info.get(scenario, 0) + 1
        
        return np.array(samples), scenario_info
    
    def get_engine(self, profile: str) -> LatencyEngine:
        """Get a specific latency engine"""
        return self._engines.get(profile)


# Global instances
_latency_engine: Optional[LatencyEngine] = None
_composite_engine: Optional[CompositeLatencyEngine] = None


def get_latency_engine(profile: str = "baseline") -> LatencyEngine:
    """Get global latency engine"""
    global _latency_engine
    if _latency_engine is None:
        _latency_engine = LatencyEngine(profile)
    return _latency_engine


def get_composite_engine() -> CompositeLatencyEngine:
    """Get global composite engine"""
    global _composite_engine
    if _composite_engine is None:
        _composite_engine = CompositeLatencyEngine()
    return _composite_engine
