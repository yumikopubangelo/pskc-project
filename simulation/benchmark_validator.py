# ============================================================
# PSKC — Benchmark Validation Suite
# ============================================================
#
# Provides reproducibility and formal statistical validation
# for simulation benchmarks.
#
# Features:
#   1. Reproducibility - seed control, deterministic execution
#   2. Statistical Validation - confidence intervals, hypothesis testing
#   3. Effect Size - Cohen's d, practical significance
#   4. Multi-run Analysis - aggregated results with error bounds
#
# Usage:
#   python simulation/benchmark_validator.py --runs 10 --seed 42
#   python simulation/benchmark_validator.py --scenario siakad --runs 30
# ============================================================

import numpy as np
import argparse
import json
import time
import os
import sys
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from scipy import stats
import logging

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engines.latency_engine import LatencyEngine
from engines.traffic_generator import TrafficGenerator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================
# Configuration
# ============================================================

@dataclass
class ValidationConfig:
    """Configuration for benchmark validation"""
    num_runs: int = 10           # Number of independent runs
    seed: Optional[int] = None   # Base seed for reproducibility
    confidence_level: float = 0.95  # Confidence interval level
    alpha: float = 0.05          # Significance level for hypothesis testing
    min_effect_size: float = 0.2  # Minimum effect size to report as significant
    randomize_seed: bool = False  # Use random seed instead of fixed
    

@dataclass
class MetricStats:
    """Statistical summary of a metric"""
    mean: float
    std: float
    median: float
    min_val: float
    max_val: float
    ci_lower: float
    ci_upper: float
    n: int


@dataclass
class ComparisonResult:
    """Result of statistical comparison between two conditions"""
    metric: str
    mean_without: float
    mean_with: float
    improvement_pct: float
    p_value: float
    is_significant: bool
    effect_size: float
    effect_interpretation: str
    ci_improvement_lower: float
    ci_improvement_upper: float


# ============================================================
# Core Statistical Functions
# ============================================================

def calculate_stats(data: np.ndarray, confidence: float = 0.95) -> MetricStats:
    """
    Calculate comprehensive statistics including confidence intervals.
    
    Args:
        data: Array of values
        confidence: Confidence level (default 95%)
        
    Returns:
        MetricStats with all computed values
    """
    n = len(data)
    mean = np.mean(data)
    std = np.std(data, ddof=1)  # Sample standard deviation
    
    # Confidence interval using t-distribution
    t_crit = stats.t.ppf((1 + confidence) / 2, df=n-1)
    margin = t_crit * (std / np.sqrt(n))
    
    return MetricStats(
        mean=float(mean),
        std=float(std),
        median=float(np.median(data)),
        min_val=float(np.min(data)),
        max_val=float(np.max(data)),
        ci_lower=float(mean - margin),
        ci_upper=float(mean + margin),
        n=n
    )


def cohens_d(group1: np.ndarray, group2: np.ndarray) -> float:
    """
    Calculate Cohen's d effect size.
    
    Interpretation:
        - |d| < 0.2: negligible
        - 0.2 <= |d| < 0.5: small
        - 0.5 <= |d| < 0.8: medium
        - |d| >= 0.8: large
    
    Args:
        group1: First group of values
        group2: Second group of values
        
    Returns:
        Cohen's d value
    """
    n1, n2 = len(group1), len(group2)
    
    # Pooled standard deviation
    var1 = np.var(group1, ddof=1)
    var2 = np.var(group2, ddof=1)
    pooled_std = np.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))
    
    if pooled_std == 0:
        return 0.0
    
    return float((np.mean(group1) - np.mean(group2)) / pooled_std)


def interpret_effect_size(d: float) -> str:
    """Interpret Cohen's d effect size"""
    abs_d = abs(d)
    if abs_d < 0.2:
        return "negligible"
    elif abs_d < 0.5:
        return "small"
    elif abs_d < 0.8:
        return "medium"
    else:
        return "large"


def welch_t_test(group1: np.ndarray, group2: np.ndarray) -> Tuple[float, float]:
    """
    Welch's t-test for comparing two independent samples.
    Does not assume equal variances.
    
    Args:
        group1: First group of values
        group2: Second group of values
        
    Returns:
        Tuple of (t-statistic, p-value)
    """
    t_stat, p_value = stats.ttest_ind(group1, group2, equal_var=False)
    return float(t_stat), float(p_value)


def mann_whitney_test(group1: np.ndarray, group2: np.ndarray) -> Tuple[float, float]:
    """
    Mann-Whitney U test (non-parametric alternative to t-test).
    Use when data is not normally distributed.
    
    Returns:
        Tuple of (U-statistic, p-value)
    """
    statistic, p_value = stats.mannwhitneyu(group1, group2, alternative='two-sided')
    return float(statistic), float(p_value)


def normality_test(data: np.ndarray) -> Tuple[float, float]:
    """
    Shapiro-Wilk test for normality.
    
    Returns:
        Tuple of (W-statistic, p-value)
    """
    # Use up to 5000 samples for Shapiro-Wilk
    sample = data[:5000] if len(data) > 5000 else data
    if len(sample) < 3:
        return 1.0, 1.0
    W, p_value = stats.shapiro(sample)
    return float(W), float(p_value)


# ============================================================
# Reproducibility Manager
# ============================================================

class ReproducibilityManager:
    """
    Manages reproducible random number generation for simulations.
    """
    
    def __init__(self, base_seed: Optional[int] = None, num_runs: int = 1):
        self.base_seed = base_seed
        self.num_runs = num_runs
        self.current_run = 0
        self._rng: Optional[np.random.Generator] = None
        
        if base_seed is not None:
            self._rng = np.random.default_rng(base_seed)
        else:
            self._rng = np.random.default_rng()
    
    def get_seed_for_run(self, run_index: int) -> int:
        """Get deterministic seed for a specific run"""
        if self.base_seed is not None:
            return self.base_seed + run_index
        else:
            # Generate random seed for this run
            return int(self._rng.integers(2**31))
    
    def create_rng_for_run(self, run_index: int) -> np.random.Generator:
        """Create RNG for specific run"""
        seed = self.get_seed_for_run(run_index)
        return np.random.default_rng(seed)
    
    def get_state_summary(self) -> Dict[str, Any]:
        """Get summary of reproducibility state"""
        return {
            "base_seed": self.base_seed,
            "num_runs": self.num_runs,
            "current_run": self.current_run,
            "is_reproducible": self.base_seed is not None
        }


# ============================================================
# Benchmark Validator
# ============================================================

class BenchmarkValidator:
    """
    Comprehensive benchmark validation with statistical testing.
    """
    
    def __init__(self, config: ValidationConfig):
        self.config = config
        self.repro_mgr = ReproducibilityManager(
            base_seed=config.seed if not config.randomize_seed else None,
            num_runs=config.num_runs
        )
        
        # Storage for results
        self._without_pskc_results: List[Dict[str, float]] = []
        self._with_pskc_results: List[Dict[str, float]] = []
        self._run_seeds: List[int] = []
        
    def _run_single_simulation(
        self, 
        scenario_fn, 
        n_requests: int, 
        use_pskc: bool,
        run_index: int
    ) -> Dict[str, float]:
        """Run a single simulation with controlled randomness"""
        rng = self.repro_mgr.create_rng_for_run(run_index)
        
        # Set seed for numpy global state (for compatibility)
        np.random.seed(self.repro_mgr.get_seed_for_run(run_index))
        
        # Run simulation
        result = scenario_fn(n_requests, use_pskc=use_pskc)
        
        return result
    
    def _extract_metrics(self, result: Dict) -> Dict[str, float]:
        """Extract key metrics from simulation result"""
        return {
            "avg_ms": result.get("avg_ms", 0),
            "p95_ms": result.get("p95_ms", 0),
            "p99_ms": result.get("p99_ms", 0),
            "cache_hit_rate": result.get("cache_hit_rate", 0),
            "timeout_rate": result.get("timeout_rate", 0),
            "total_requests": result.get("total_requests", 0),
        }
    
    def run_comparative_benchmark(
        self,
        scenario_fn,
        scenario_name: str,
        n_requests: int = 1000,
        **scenario_kwargs
    ) -> Dict[str, Any]:
        """
        Run benchmark with statistical validation.
        
        Args:
            scenario_fn: Function that runs the simulation
            scenario_name: Name for reporting
            n_requests: Number of requests per run
            **scenario_kwargs: Additional arguments to pass to scenario_fn
            
        Returns:
            Comprehensive benchmark results with statistics
        """
        logger.info(f"Starting benchmark: {scenario_name}")
        logger.info(f"Configuration: runs={self.config.num_runs}, seed={self.config.seed}")
        
        start_time = time.time()
        
        for run_idx in range(self.config.num_runs):
            seed = self.repro_mgr.get_seed_for_run(run_idx)
            self._run_seeds.append(seed)
            
            # Run WITHOUT PSKC
            result_without = self._run_single_simulation(
                scenario_fn, n_requests, use_pskc=False, run_index=run_idx
            )
            self._without_pskc_results.append(self._extract_metrics(result_without))
            
            # Run WITH PSKC
            result_with = self._run_single_simulation(
                scenario_fn, n_requests, use_pskc=True, run_index=run_idx
            )
            self._with_pskc_results.append(self._extract_metrics(result_with))
            
            logger.info(f"  Run {run_idx + 1}/{self.config.num_runs} complete (seed={seed})")
        
        elapsed = time.time() - start_time
        
        # Analyze results
        analysis = self._analyze_results()
        
        return {
            "scenario": scenario_name,
            "configuration": {
                "num_runs": self.config.num_runs,
                "n_requests_per_run": n_requests,
                "base_seed": self.config.seed,
                "randomize_seed": self.config.randomize_seed,
                "confidence_level": self.config.confidence_level,
                "alpha": self.config.alpha,
            },
            "seeds": self._run_seeds,
            "timing": {
                "total_seconds": round(elapsed, 2),
                "avg_per_run_seconds": round(elapsed / self.config.num_runs, 2)
            },
            "individual_runs": {
                "without_pskc": self._without_pskc_results,
                "with_pskc": self._with_pskc_results
            },
            "statistics": analysis
        }
    
    def _analyze_results(self) -> Dict[str, Any]:
        """Perform statistical analysis on benchmark results"""
        metrics = ["avg_ms", "p95_ms", "p99_ms", "cache_hit_rate"]
        
        stats_results = {}
        comparisons = {}
        
        for metric in metrics:
            # Extract data for this metric
            without = np.array([r[metric] for r in self._without_pskc_results])
            with_pskc = np.array([r[metric] for r in self._with_pskc_results])
            
            # Calculate stats for each group
            stats_results[metric] = {
                "without_pskc": calculate_stats(without, self.config.confidence_level).__dict__,
                "with_pskc": calculate_stats(with_pskc, self.config.confidence_level).__dict__,
            }
            
            # Statistical comparison
            if metric in ["avg_ms", "p95_ms", "p99_ms"]:
                # For latency metrics, lower is better
                improvement_pct = (1 - np.mean(with_pskc) / np.mean(without)) * 100
            else:
                # For rates, higher is better
                improvement_pct = (np.mean(with_pskc) - np.mean(without)) / max(np.mean(without), 0.001) * 100
            
            # Hypothesis testing
            t_stat, p_value = welch_t_test(without, with_pskc)
            
            # Effect size
            effect = cohens_d(without, with_pskc)
            
            # Confidence interval for improvement (bootstrap-like approximation)
            # For simplicity, using normal approximation
            se_improvement = np.sqrt(
                np.var(without) / len(without) + 
                np.var(with_pskc) / len(with_pskc)
            )
            ci_margin = stats.norm.ppf((1 + self.config.confidence_level) / 2) * se_improvement
            
            is_significant = p_value < self.config.alpha
            
            comparisons[metric] = ComparisonResult(
                metric=metric,
                mean_without=float(np.mean(without)),
                mean_with=float(np.mean(with_pskc)),
                improvement_pct=round(improvement_pct, 2),
                p_value=round(p_value, 6),
                is_significant=is_significant,
                effect_size=round(effect, 3),
                effect_interpretation=interpret_effect_size(effect),
                ci_improvement_lower=round(improvement_pct - ci_margin * 100, 2),
                ci_improvement_upper=round(improvement_pct + ci_margin * 100, 2)
            ).__dict__
        
        return {
            "metrics": stats_results,
            "comparisons": comparisons,
            "summary": {
                "all_significant": all(c["is_significant"] for c in comparisons.values()),
                "avg_improvement": round(
                    np.mean([c["improvement_pct"] for c in comparisons.values()]), 2
                ),
                "avg_effect_size": round(
                    np.mean([abs(c["effect_size"]) for c in comparisons.values()]), 3
                )
            }
        }
    
    def get_reproducibility_report(self) -> Dict[str, Any]:
        """Generate reproducibility report"""
        return {
            "reproducibility_manager": self.repro_mgr.get_state_summary(),
            "seeds_used": self._run_seeds,
            "validation": {
                "deterministic": self.config.seed is not None,
                "verified": self._run_seeds == [self.repro_mgr.get_seed_for_run(i) for i in range(len(self._run_seeds))]
            }
        }


# ============================================================
# Convenience Functions
# ============================================================

def run_validated_benchmark(
    scenario_fn,
    scenario_name: str,
    num_runs: int = 10,
    seed: int = 42,
    n_requests: int = 1000
) -> Dict[str, Any]:
    """
    Convenience function to run a validated benchmark.
    
    Args:
        scenario_fn: Simulation function
        scenario_name: Name for reporting
        num_runs: Number of runs
        seed: Random seed
        n_requests: Requests per run
        
    Returns:
        Benchmark results
    """
    config = ValidationConfig(
        num_runs=num_runs,
        seed=seed,
        confidence_level=0.95,
        alpha=0.05
    )
    
    validator = BenchmarkValidator(config)
    return validator.run_comparative_benchmark(
        scenario_fn, scenario_name, n_requests
    )


def print_benchmark_report(results: Dict[str, Any]) -> None:
    """Pretty print benchmark results"""
    print("\n" + "=" * 70)
    print(f"  BENCHMARK VALIDATION REPORT: {results['scenario']}")
    print("=" * 70)
    
    # Configuration
    cfg = results['configuration']
    print(f"\n[Configuration]")
    print(f"  Runs: {cfg['num_runs']} | Requests/run: {cfg['n_requests_per_run']}")
    print(f"  Seed: {cfg['base_seed']} | Confidence: {cfg['confidence_level']*100}%")
    print(f"  Alpha: {cfg['alpha']}")
    
    # Timing
    print(f"\n[Timing]")
    print(f"  Total: {results['timing']['total_seconds']}s")
    print(f"  Avg/run: {results['timing']['avg_per_run_seconds']}s")
    
    # Comparisons
    print(f"\n[Statistical Comparisons]")
    comparisons = results['statistics']['comparisons']
    
    for metric, comp in comparisons.items():
        sig_marker = "✓" if comp['is_significant'] else "✗"
        print(f"\n  {metric}:")
        print(f"    Without PSKC: {comp['mean_without']:.2f}")
        print(f"    With PSKC:    {comp['mean_with']:.2f}")
        print(f"    Improvement:  {comp['improvement_pct']:+.2f}% [{comp['ci_improvement_lower']:+.2f}%, {comp['ci_improvement_upper']:+.2f}%]")
        print(f"    p-value:     {comp['p_value']:.6f} {sig_marker}")
        print(f"    Effect size: {comp['effect_size']:.3f} ({comp['effect_interpretation']})")
    
    # Summary
    summary = results['statistics']['summary']
    print(f"\n[Summary]")
    print(f"  All significant: {'Yes' if summary['all_significant'] else 'No'}")
    print(f"  Avg improvement: {summary['avg_improvement']:.2f}%")
    print(f"  Avg effect size: {summary['avg_effect_size']:.3f}")
    
    print("\n" + "=" * 70)


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="PSKC Benchmark Validation Suite"
    )
    parser.add_argument(
        "--scenario",
        default="test",
        choices=["test", "siakad", "sevima", "pddikti", "dynamic"],
        help="Scenario to benchmark"
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=10,
        help="Number of independent runs"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Base random seed for reproducibility"
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=500,
        help="Requests per run"
    )
    parser.add_argument(
        "--random-seed",
        action="store_true",
        help="Use random seed instead of fixed"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON file"
    )
    
    args = parser.parse_args()
    
    # Configuration
    config = ValidationConfig(
        num_runs=args.runs,
        seed=None if args.random_seed else args.seed,
        confidence_level=0.95,
        alpha=0.05,
        randomize_seed=args.random_seed
    )
    
    validator = BenchmarkValidator(config)
    
    # Import scenarios
    from scenarios.siakad_sso import run_batch as run_siakad
    from scenarios.sevima_cloud import run_batch as run_sevima
    from scenarios.pddikti_auth import run_batch as run_pddikti
    from scenarios.dynamic_production import run_batch as run_dynamic
    
    # Select scenario
    scenario_map = {
        "siakad": (run_siakad, "SIAKAD SSO"),
        "sevima": (run_sevima, "SEVIMA Cloud"),
        "pddikti": (run_pddikti, "PDDikti"),
        "dynamic": (run_dynamic, "Dynamic Production"),
    }
    
    if args.scenario == "test":
        # Simple test scenario
        def test_scenario(n, use_pskc):
            return {
                "avg_ms": np.random.lognormal(5, 0.5) if use_pskc else np.random.lognormal(5.3, 0.5),
                "p95_ms": np.random.lognormal(5.5, 0.4) if use_pskc else np.random.lognormal(5.8, 0.4),
                "p99_ms": np.random.lognormal(6, 0.3) if use_pskc else np.random.lognormal(6.3, 0.3),
                "cache_hit_rate": 0.75 if use_pskc else 0.3,
                "timeout_rate": 0.01 if use_pskc else 0.05,
                "total_requests": n
            }
        scenario_fn = test_scenario
        scenario_name = "Test Scenario"
    else:
        scenario_fn, scenario_name = scenario_map[args.scenario]
    
    # Run benchmark
    results = validator.run_comparative_benchmark(
        scenario_fn, scenario_name, args.requests
    )
    
    # Print report
    print_benchmark_report(results)
    
    # Save to file if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\nResults saved to: {args.output}")
