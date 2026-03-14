#!/usr/bin/env python3
# ============================================================
# PSKC — Benchmark Script
# Benchmark latency with and without PSKC
# ============================================================
import argparse
import sys
import os
import time
import json
from datetime import datetime
from typing import Dict, List

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def simulate_without_pskc(
    num_requests: int = 1000,
    scenario: str = "baseline"
) -> Dict:
    """Simulate latency without PSKC (direct KMS calls)"""
    
    from simulation.engines.latency_engine import LatencyEngine
    
    # Use baseline latency profile
    engine = LatencyEngine(scenario)
    
    latencies = engine.sample(num_requests)
    
    return {
        "method": "without_pskc",
        "scenario": scenario,
        "num_requests": num_requests,
        "avg_latency": float(np.mean(latencies)),
        "p50_latency": float(np.percentile(latencies, 50)),
        "p95_latency": float(np.percentile(latencies, 95)),
        "p99_latency": float(np.percentile(latencies, 99)),
        "min_latency": float(np.min(latencies)),
        "max_latency": float(np.max(latencies)),
        "std_latency": float(np.std(latencies))
    }


def simulate_with_pskc(
    num_requests: int = 1000,
    scenario: str = "baseline",
    cache_hit_rate: float = 0.8,
    prefetch_rate: float = 0.1
) -> Dict:
    """Simulate latency with PSKC (cache hits + prefetch)"""
    
    from simulation.engines.latency_engine import LatencyEngine
    
    # Simulate different latency types
    cached_engine = LatencyEngine("pskc_cached")  # Cache hit
    prefetch_engine = LatencyEngine("pskc_prefetch")  # Prefetch
    direct_engine = LatencyEngine(scenario)  # Direct KMS (miss)
    
    results = []
    
    for i in range(num_requests):
        rand = np.random.random()
        
        if rand < cache_hit_rate:
            # Cache hit
            latency = cached_engine.sample_single()
        elif rand < cache_hit_rate + prefetch_rate:
            # Prefetch hit
            latency = prefetch_engine.sample_single()
        else:
            # Cache miss - direct KMS
            latency = direct_engine.sample_single()
        
        results.append(latency)
    
    latencies = np.array(results)
    
    return {
        "method": "with_pskc",
        "scenario": scenario,
        "num_requests": num_requests,
        "cache_hit_rate": cache_hit_rate,
        "prefetch_rate": prefetch_rate,
        "avg_latency": float(np.mean(latencies)),
        "p50_latency": float(np.percentile(latencies, 50)),
        "p95_latency": float(np.percentile(latencies, 95)),
        "p99_latency": float(np.percentile(latencies, 99)),
        "min_latency": float(np.min(latencies)),
        "max_latency": float(np.max(latencies)),
        "std_latency": float(np.std(latencies))
    }


def run_benchmark(
    num_requests: int = 1000,
    scenario: str = "baseline",
    cache_hit_rate: float = 0.8,
    output_file: str = None
) -> Dict:
    """Run complete benchmark comparing with and without PSKC"""
    
    logger.info(f"Running benchmark: {num_requests} requests, scenario={scenario}")
    
    # Baseline (without PSKC)
    logger.info("Simulating without PSKC...")
    without_pskc = simulate_without_pskc(num_requests, scenario)
    
    # With PSKC
    logger.info("Simulating with PSKC...")
    with_pskc = simulate_with_pskc(
        num_requests,
        scenario,
        cache_hit_rate=cache_hit_rate
    )
    
    # Calculate improvement
    avg_improvement = (
        (without_pskc['avg_latency'] - with_pskc['avg_latency'])
        / without_pskc['avg_latency'] * 100
    )
    
    p95_improvement = (
        (without_pskc['p95_latency'] - with_pskc['p95_latency'])
        / without_pskc['p95_latency'] * 100
    )
    
    p99_improvement = (
        (without_pskc['p99_latency'] - with_pskc['p99_latency'])
        / without_pskc['p99_latency'] * 100
    )
    
    results = {
        "timestamp": datetime.now().isoformat(),
        "parameters": {
            "num_requests": num_requests,
            "scenario": scenario,
            "cache_hit_rate": cache_hit_rate
        },
        "without_pskc": without_pskc,
        "with_pskc": with_pskc,
        "improvement": {
            "avg_latency_reduction_percent": avg_improvement,
            "p95_latency_reduction_percent": p95_improvement,
            "p99_latency_reduction_percent": p99_improvement
        }
    }
    
    # Print summary
    print("\n" + "=" * 60)
    print("BENCHMARK RESULTS")
    print("=" * 60)
    print(f"\nScenario: {scenario}")
    print(f"Requests: {num_requests}")
    print(f"Cache Hit Rate: {cache_hit_rate:.1%}")
    
    print("\n--- Without PSKC (Direct KMS) ---")
    print(f"  Average: {without_pskc['avg_latency']:.2f} ms")
    print(f"  P95:     {without_pskc['p95_latency']:.2f} ms")
    print(f"  P99:     {without_pskc['p99_latency']:.2f} ms")
    
    print("\n--- With PSKC ---")
    print(f"  Average: {with_pskc['avg_latency']:.2f} ms")
    print(f"  P95:     {with_pskc['p95_latency']:.2f} ms")
    print(f"  P99:     {with_pskc['p99_latency']:.2f} ms")
    
    print("\n--- Improvement ---")
    print(f"  Average: {avg_improvement:.1f}% reduction")
    print(f"  P95:     {p95_improvement:.1f}% reduction")
    print(f"  P99:     {p99_improvement:.1f}% reduction")
    print("=" * 60 + "\n")
    
    # Save to file
    if output_file:
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)
        logger.info(f"Results saved to {output_file}")
    
    return results


def run_all_scenarios(num_requests: int = 1000) -> Dict:
    """Run benchmark for all scenarios"""
    
    scenarios = {
        "spotify_padlock": {"scenario": "spotify_padlock_no_cache", "cache_hit": 0.85},
        "aws_kms": {"scenario": "aws_kms", "cache_hit": 0.80},
        "netflix_zuul": {"scenario": "netflix_zuul", "cache_hit": 0.75}
    }
    
    results = {}
    
    for name, params in scenarios.items():
        logger.info(f"Running scenario: {name}")
        
        result = run_benchmark(
            num_requests=num_requests,
            scenario=params["scenario"],
            cache_hit_rate=params["cache_hit"],
            output_file=None
        )
        
        results[name] = result
    
    return results


def main():
    parser = argparse.ArgumentParser(description="PSKC Benchmark")
    
    parser.add_argument(
        "--requests", "-n",
        type=int,
        default=1000,
        help="Number of requests to simulate"
    )
    
    parser.add_argument(
        "--scenario", "-s",
        type=str,
        default="baseline",
        choices=["baseline", "spotify_padlock", "aws_kms", "netflix_zuul"],
        help="Latency scenario"
    )
    
    parser.add_argument(
        "--cache-rate",
        type=float,
        default=0.8,
        help="Cache hit rate (0-1)"
    )
    
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output JSON file"
    )
    
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all scenarios"
    )
    
    args = parser.parse_args()
    
    if args.all:
        results = run_all_scenarios(args.requests)
    else:
        results = run_benchmark(
            num_requests=args.requests,
            scenario=args.scenario,
            cache_hit_rate=args.cache_rate,
            output_file=args.output
        )


if __name__ == "__main__":
    main()
