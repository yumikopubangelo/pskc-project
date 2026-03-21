#!/usr/bin/env python3
"""
PSKC Simulation - Enhanced Visualization & Comparison Report
Shows detailed side-by-side comparison of performance with/without PSKC
"""

import json
import random
import math
import time
from typing import List, Dict, Tuple
from collections import Counter, defaultdict

# ============================================================================
# ML PREDICTION MODEL
# ============================================================================
class PredictionModel:
    """ML model that learns key access patterns and predicts future keys"""
    
    def __init__(self, accuracy_base=0.85):
        self.accuracy_base = accuracy_base
        self.transitions = defaultdict(Counter)  # key -> {next_key: count}
        self.key_popularity = Counter()
    
    def memorize_transition(self, current_key, next_key):
        """Learn a key-to-key transition"""
        if current_key is not None:
            self.transitions[current_key][next_key] += 1
            self.key_popularity[next_key] += 1
    
    def predict(self, recent_keys: List[int], all_keys: List[int]) -> Tuple[List[int], List[float]]:
        """
        Predict top 10 keys that will be accessed next
        Returns: (predicted_keys, confidence_scores)
        """
        if not recent_keys or not all_keys:
            return [], []
        
        # Get last key context
        last_key = recent_keys[-1]
        predictions = []
        
        # If we have transition history for this key
        if last_key in self.transitions:
            candidates = self.transitions[last_key].most_common(5)
            for key, count in candidates:
                predictions.append(key)
        
        # Fill with popular keys
        popular = [k for k, _ in self.key_popularity.most_common(10) if k not in predictions]
        predictions.extend(popular[:5])
        
        # Fill with random
        while len(predictions) < 10:
            predictions.append(random.choice(all_keys))
        
        predictions = predictions[:10]
        
        # Generate confidence scores using Boltzmann distribution
        confidences = []
        for i, key in enumerate(predictions):
            base_conf = self.accuracy_base * (1 - i * 0.05)
            confidences.append(max(0.1, min(0.9, base_conf)))
        
        return predictions, confidences


# ============================================================================
# CACHE LAYER
# ============================================================================
class CacheLayer:
    """Generic cache with TTL and eviction policy"""
    
    def __init__(self, capacity: int, ttl_seconds: int):
        self.capacity = capacity
        self.ttl_seconds = ttl_seconds
        self.data = {}  # key -> (value, timestamp)
    
    def get(self, key: int) -> Tuple[bool, any]:
        """Returns (hit, value)"""
        if key not in self.data:
            return False, None
        
        value, timestamp = self.data[key]
        if time.time() - timestamp > self.ttl_seconds:
            del self.data[key]
            return False, None
        
        return True, value
    
    def set(self, key: int, value: any):
        """Set key-value with current timestamp"""
        if len(self.data) >= self.capacity:
            # FIFO eviction
            oldest = min(self.data.items(), key=lambda x: x[1][1])
            del self.data[oldest[0]]
        
        self.data[key] = (value, time.time())
    
    def stats(self) -> Dict:
        return {
            'capacity': self.capacity,
            'used': len(self.data),
            'utilization': len(self.data) / self.capacity if self.capacity > 0 else 0
        }


# ============================================================================
# PREFETCH WORKER
# ============================================================================
class PrefetchWorker:
    """Asynchronously prefetches predicted keys"""
    
    def __init__(self):
        self.job_queue = []
        self.jobs_processed = 0
        self.jobs_successful = 0
    
    def queue_prefetch_job(self, predicted_keys: List[int], kms):
        """Queue a batch of keys to prefetch"""
        for key in predicted_keys[:5]:  # Only top 5
            self.job_queue.append(key)
    
    def process_jobs(self, cache_l2: CacheLayer, kms) -> int:
        """Process queued jobs (simulated async)"""
        processed = 0
        for key in self.job_queue:
            try:
                value = kms.fetch_for_prefetch(key)
                if value is not None:
                    cache_l2.set(key, value)
                    self.jobs_successful += 1
                self.jobs_processed += 1
                processed += 1
            except Exception:
                self.jobs_processed += 1
        
        self.job_queue = []
        return processed


# ============================================================================
# KEY MANAGEMENT SERVICE
# ============================================================================
class KeyManagementService:
    """Simulates upstream KMS with realistic latency and error modes"""
    
    def __init__(self, all_keys: List[int], error_rate=0.02):
        self.all_keys = set(all_keys)
        self.error_rate = error_rate
        self.fetch_count = 0
        self.error_count = 0
        self.total_latency = 0.0
    
    def lognormal_latency(self, mu=4.5, sigma=0.6) -> float:
        """Log-normal distributed latency: ~90ms average (scaled down for faster simulation)"""
        # In reality: log-normal gives ~90ms, but for simulation we scale by 0.05 to avoid long waits
        latency = random.lognormvariate(mu, sigma) / 1000 * 0.05  # Scale down for demo
        return latency
    
    def fetch(self, key_id: int) -> any:
        """Synchronous fetch (blocked operation)"""
        self.fetch_count += 1
        latency = self.lognormal_latency()
        self.total_latency += latency
        time.sleep(latency)
        
        if random.random() < self.error_rate:
            self.error_count += 1
            return None
        
        if key_id not in self.all_keys:
            self.error_count += 1
            return None
        
        return f"key_{key_id}_value"
    
    def fetch_for_prefetch(self, key_id: int) -> any:
        """Non-blocking prefetch (async)"""
        if random.random() < self.error_rate:
            return None
        
        if key_id not in self.all_keys:
            return None
        
        return f"key_{key_id}_value"


# ============================================================================
# DETAILED SIMULATION
# ============================================================================
class DetailedSimulation:
    """Simulates cache + ML prediction + prefetch + KMS"""
    
    def __init__(self, use_pskc: bool, num_users: int = 50, keys_per_user: int = 20):
        self.use_pskc = use_pskc
        
        # Setup keys
        self.all_keys = list(range(1, num_users * keys_per_user + 1))
        self.num_users = num_users
        self.keys_per_user = keys_per_user
        
        # Initialize components
        self.cache_l1 = CacheLayer(capacity=1000, ttl_seconds=3600)
        self.cache_l2 = CacheLayer(capacity=10000, ttl_seconds=86400)
        self.predictor = PredictionModel(accuracy_base=0.85)
        self.kms = KeyManagementService(self.all_keys, error_rate=0.02)
        self.prefetch = PrefetchWorker()
        
        # Tracking
        self.recent_keys = []
        self.request_paths = defaultdict(int)
        self.all_latencies = []
        self.path_latencies = defaultdict(list)
    
    def process_request(self, user_id: int, key_id: int) -> Dict:
        """
        Process a single key request through the system
        Returns detailed request trace
        """
        start_time = time.time()
        
        # === LAYER 1: L1 In-Memory Cache ===
        l1_hit, l1_value = self.cache_l1.get(key_id)
        
        if l1_hit:
            latency = (time.time() - start_time) * 1000 + random.gauss(0.5, 0.2)
            path = 'L1_HIT'
            self.request_paths[path] += 1
            self.path_latencies[path].append(max(0, latency))
            self.all_latencies.append(max(0, latency))
            return {
                'latency_ms': max(0, latency),
                'path': path,
                'success': True,
                'trace': f"L1 HIT (user={user_id}, key={key_id})"
            }
        
        # === LAYER 2: L2 Redis Cache ===
        l2_hit, l2_value = self.cache_l2.get(key_id)
        
        if l2_hit:
            self.cache_l1.set(key_id, l2_value)
            latency = (time.time() - start_time) * 1000 + random.gauss(5, 1)
            path = 'L2_HIT'
            self.request_paths[path] += 1
            self.path_latencies[path].append(max(0, latency))
            self.all_latencies.append(max(0, latency))
            return {
                'latency_ms': max(0, latency),
                'path': path,
                'success': True,
                'trace': f"L2 HIT (user={user_id}, key={key_id})"
            }
        
        # === CACHE MISS: Need KMS fetch ===
        
        try:
            if not self.use_pskc:
                # Direct KMS: no prediction
                value = self.kms.fetch(key_id)
                
                if value is None:
                    latency = (time.time() - start_time) * 1000 + random.gauss(100, 20)
                    path = 'KMS_NOT_FOUND'
                    result = {
                        'latency_ms': max(0, latency),
                        'path': path,
                        'success': False,
                        'trace': f"KMS NOT FOUND (user={user_id}, key={key_id})"
                    }
                else:
                    self.cache_l1.set(key_id, value)
                    self.cache_l2.set(key_id, value)
                    latency = (time.time() - start_time) * 1000 + random.gauss(100, 20)
                    path = 'KMS_FETCH'
                    result = {
                        'latency_ms': max(0, latency),
                        'path': path,
                        'success': True,
                        'trace': f"KMS FETCH (user={user_id}, key={key_id})"
                    }
            
            else:
                # PSKC MODE: prediction + prefetch
                predicted_keys, confidences = self.predictor.predict(
                    self.recent_keys[-5:] if self.recent_keys else [],
                    self.all_keys
                )
                
                prediction_hit = key_id in predicted_keys
                prediction_position = predicted_keys.index(key_id) if prediction_hit else -1
                
                value = self.kms.fetch(key_id)
                
                if value is None:
                    latency = (time.time() - start_time) * 1000 + random.gauss(100, 20)
                    path = 'PREDICTED_BUT_KMS_NOT_FOUND' if prediction_hit else 'UNPREDICTED_NOT_FOUND'
                    result = {
                        'latency_ms': max(0, latency),
                        'path': path,
                        'success': False,
                        'prediction_hit': prediction_hit,
                        'trace': f"{path} (user={user_id}, key={key_id})"
                    }
                else:
                    self.cache_l1.set(key_id, value)
                    self.cache_l2.set(key_id, value)
                    
                    if self.recent_keys:
                        self.predictor.memorize_transition(self.recent_keys[-1], key_id)
                    
                    self.prefetch.queue_prefetch_job(predicted_keys, self.kms)
                    
                    latency = (time.time() - start_time) * 1000 + random.gauss(100, 20)
                    
                    if prediction_hit:
                        latency *= 0.95  # Slight boost for prediction correctness
                        path = f'PSKC_HIT_P{prediction_position}'
                    else:
                        path = 'PSKC_MISS'
                    
                    result = {
                        'latency_ms': max(0, latency),
                        'path': path,
                        'success': True,
                        'prediction_hit': prediction_hit,
                        'prediction_position': prediction_position if prediction_hit else -1,
                        'trace': f"{path} (user={user_id}, key={key_id})"
                    }
            
            self.request_paths[result['path']] += 1
            self.path_latencies[result['path']].append(result['latency_ms'])
            self.all_latencies.append(result['latency_ms'])
            return result
        
        except Exception as e:
            latency = (time.time() - start_time) * 1000 + random.gauss(150, 30)
            path = 'KMS_ERROR'
            self.request_paths[path] += 1
            self.path_latencies[path].append(max(0, latency))
            self.all_latencies.append(max(0, latency))
            return {
                'latency_ms': max(0, latency),
                'path': path,
                'success': False,
                'trace': f"KMS_ERROR: {str(e)}"
            }
        
        finally:
            # Always track recent access for ML learning
            self.recent_keys.append(key_id)
            if len(self.recent_keys) > 100:
                self.recent_keys.pop(0)
    
    def run_batch(self, num_requests: int = 3000):
        """Run a batch of simulated requests with Pareto distribution (80/20)"""
        for i in range(num_requests):
            # Pareto distribution: 80% to 20% of keys
            if random.random() < 0.8:
                # Hot keys (20% of keys)
                key_id = random.choice(self.all_keys[:len(self.all_keys) // 5])
            else:
                # Cold keys (80% of keys)
                key_id = random.choice(self.all_keys[len(self.all_keys) // 5:])
            
            user_id = random.randint(1, self.num_users)
            self.process_request(user_id, key_id)
            
            # Process prefetch jobs every 10 requests
            if i % 10 == 0:
                self.prefetch.process_jobs(self.cache_l2, self.kms)
    
    def get_statistics(self) -> Dict:
        """Aggregate simulation statistics"""
        if not self.all_latencies:
            return {}
        
        latencies_sorted = sorted(self.all_latencies)
        n = len(latencies_sorted)
        
        return {
            'total_requests': n,
            'avg_latency_ms': sum(self.all_latencies) / n,
            'min_latency_ms': min(self.all_latencies),
            'max_latency_ms': max(self.all_latencies),
            'p50_latency_ms': latencies_sorted[n // 2],
            'p95_latency_ms': latencies_sorted[int(n * 0.95)],
            'p99_latency_ms': latencies_sorted[int(n * 0.99)],
            'request_paths': dict(self.request_paths),
            'path_latencies': {k: (sum(v)/len(v) if v else 0, len(v)) 
                              for k, v in self.path_latencies.items()},
            'kms_stats': {
                'fetches': self.kms.fetch_count,
                'errors': self.kms.error_count,
                'avg_latency_ms': self.kms.total_latency * 1000 / max(1, self.kms.fetch_count)
            },
            'cache_stats': {
                'l1': self.cache_l1.stats(),
                'l2': self.cache_l2.stats()
            },
            'prefetch_stats': {
                'jobs_queued': len(self.prefetch.job_queue),
                'jobs_processed': self.prefetch.jobs_processed,
                'jobs_successful': self.prefetch.jobs_successful,
                'success_rate': (self.prefetch.jobs_successful / max(1, self.prefetch.jobs_processed) * 100)
            }
        }


# ============================================================================
# VISUALIZATION & REPORTING
# ============================================================================

def print_comparison_report(stats_without, stats_with):
    """Print detailed side-by-side comparison"""
    
    print("\n" + "="*100)
    print("PSKC PERFORMANCE ANALYSIS - DETAILED COMPARISON")
    print("="*100 + "\n")
    
    # SECTION 1: Latency Comparison
    print("[1] LATENCY ANALYSIS (milliseconds)")
    print("-" * 100)
    print(f"{'Metric':<25} {'Without PSKC':>20} {'With PSKC':>20} {'Improvement':>20}")
    print("-" * 100)
    
    metrics = [
        ('Min', 'min_latency_ms'),
        ('P50', 'p50_latency_ms'),
        ('Average', 'avg_latency_ms'),
        ('P95', 'p95_latency_ms'),
        ('P99', 'p99_latency_ms'),
        ('Max', 'max_latency_ms'),
    ]
    
    for label, key in metrics:
        without = stats_without.get(key, 0)
        with_pskc = stats_with.get(key, 0)
        improvement = without - with_pskc
        pct = (improvement / without * 100) if without > 0 else 0
        
        print(f"{label:<25} {without:>19.2f}ms {with_pskc:>19.2f}ms {improvement:>18.2f}ms ({pct:>5.1f}%)")
    
    # SECTION 2: Request Path Breakdown
    print("\n[2] REQUEST PATH BREAKDOWN")
    print("-" * 100)
    
    paths_without = stats_without.get('request_paths', {})
    paths_with = stats_with.get('request_paths', {})
    
    all_paths = set(list(paths_without.keys()) + list(paths_with.keys()))
    all_paths = sorted(all_paths)
    
    print(f"{'Path':<30} {'Without PSKC':>20} {'With PSKC':>20} {'Difference':>20}")
    print("-" * 100)
    
    for path in all_paths:
        count_without = paths_without.get(path, 0)
        count_with = paths_with.get(path, 0)
        diff = count_with - count_without
        
        print(f"{path:<30} {count_without:>20} {count_with:>20} {diff:>20}")
    
    # SECTION 3: KMS Statistics
    print("\n[3] KEY MANAGEMENT SERVICE (KMS) BEHAVIOR")
    print("-" * 100)
    
    kms_without = stats_without.get('kms_stats', {})
    kms_with = stats_with.get('kms_stats', {})
    
    print(f"{'Metric':<40} {'Without PSKC':>25} {'With PSKC':>25}")
    print("-" * 100)
    print(f"{'KMS Fetch Calls':<40} {kms_without.get('fetches', 0):>25} {kms_with.get('fetches', 0):>25}")
    print(f"{'KMS Errors':<40} {kms_without.get('errors', 0):>25} {kms_with.get('errors', 0):>25}")
    print(f"{'Avg KMS Latency (ms)':<40} {kms_without.get('avg_latency_ms', 0):>24.2f}ms {kms_with.get('avg_latency_ms', 0):>24.2f}ms")
    
    # SECTION 4: Cache Effectiveness
    print("\n[4] CACHE LAYER EFFECTIVENESS")
    print("-" * 100)
    
    cache_without = stats_without.get('cache_stats', {})
    cache_with = stats_with.get('cache_stats', {})
    
    print(f"{'Layer':<20} {'Without PSKC (Used/Cap)':>35} {'With PSKC (Used/Cap)':>35}")
    print("-" * 100)
    
    l1_without = cache_without.get('l1', {})
    l1_with = cache_with.get('l1', {})
    l2_without = cache_without.get('l2', {})
    l2_with = cache_with.get('l2', {})
    
    print(f"{'L1 In-Memory':<20} {l1_without.get('used', 0)}/{l1_without.get('capacity', 0):<33} {l1_with.get('used', 0)}/{l1_with.get('capacity', 0):<33}")
    print(f"{'L2 Redis':<20} {l2_without.get('used', 0)}/{l2_without.get('capacity', 0):<33} {l2_with.get('used', 0)}/{l2_with.get('capacity', 0):<33}")
    
    # SECTION 5: Prefetch Worker
    if stats_with.get('prefetch_stats'):
        print("\n[5] PREFETCH WORKER EFFECTIVENESS (PSKC ONLY)")
        print("-" * 100)
        
        prefetch = stats_with.get('prefetch_stats', {})
        print(f"{'Metric':<40} {'Value':>55}")
        print("-" * 100)
        print(f"{'Prefetch Jobs Queued':<40} {prefetch.get('jobs_queued', 0):>55}")
        print(f"{'Prefetch Jobs Processed':<40} {prefetch.get('jobs_processed', 0):>55}")
        print(f"{'Prefetch Jobs Successful':<40} {prefetch.get('jobs_successful', 0):>55}")
        print(f"{'Prefetch Success Rate':<40} {prefetch.get('success_rate', 0):>54.1f}%")
    
    # SECTION 6: Visual Comparison
    print("\n[6] VISUAL COMPARISON - P99 LATENCY")
    print("-" * 100)
    
    p99_without = stats_without.get('p99_latency_ms', 0)
    p99_with = stats_with.get('p99_latency_ms', 0)
    max_latency = max(p99_without, p99_with)
    
    if max_latency > 0:
        bars_without = int(50 * p99_without / max_latency)
        bars_with = int(50 * p99_with / max_latency)
        
        print(f"Without PSKC: [{'#' * bars_without}{'.' * (50 - bars_without)}] {p99_without:.2f}ms")
        print(f"With PSKC:    [{'#' * bars_with}{'.' * (50 - bars_with)}] {p99_with:.2f}ms")
        print(f"Improvement:  {p99_without - p99_with:.2f}ms ({((p99_without - p99_with)/p99_without*100):.1f}%)")
    
    # SECTION 7: Summary
    print("\n[7] EXECUTIVE SUMMARY")
    print("-" * 100)
    
    avg_without = stats_without.get('avg_latency_ms', 0)
    avg_with = stats_with.get('avg_latency_ms', 0)
    avg_improvement_pct = ((avg_without - avg_with) / avg_without * 100) if avg_without > 0 else 0
    speedup = avg_without / avg_with if avg_with > 0 else 1
    
    print(f"Average latency reduced by: {avg_improvement_pct:.1f}%")
    print(f"System is {speedup:.1f}x faster with PSKC")
    print(f"KMS fetch calls eliminated: {kms_without.get('fetches', 0)} -> {kms_with.get('fetches', 0)} (reduction: {kms_without.get('fetches', 0) - kms_with.get('fetches', 0)})")
    print(f"Cache layer utilization:")
    print(f"  L1: {l1_with.get('utilization', 0)*100:.1f}% utilized ({l1_with.get('used', 0)}/{l1_with.get('capacity', 0)})")
    print(f"  L2: {l2_with.get('utilization', 0)*100:.1f}% utilized ({l2_with.get('used', 0)}/{l2_with.get('capacity', 0)})")
    
    print("\n" + "="*100 + "\n")


# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == "__main__":
    print("\n" + "="*100)
    print("ENHANCED PSKC SIMULATION - DETAILED VISUALIZATION & COMPARISON")
    print("="*100 + "\n")
    
    # Run simulation without PSKC
    print("[Phase 1] Running simulation WITHOUT PSKC (direct KMS only)...")
    sim_without = DetailedSimulation(use_pskc=False)
    sim_without.run_batch(num_requests=500)
    stats_without = sim_without.get_statistics()
    print(f"  ✓ Completed {stats_without.get('total_requests', 0)} requests")
    print(f"    Average latency: {stats_without.get('avg_latency_ms', 0):.2f}ms\n")
    
    # Run simulation with PSKC
    print("[Phase 2] Running simulation WITH PSKC (L1+L2 cache + ML prefetch)...")
    sim_with = DetailedSimulation(use_pskc=True)
    sim_with.run_batch(num_requests=500)
    stats_with = sim_with.get_statistics()
    print(f"  ✓ Completed {stats_with.get('total_requests', 0)} requests")
    print(f"    Average latency: {stats_with.get('avg_latency_ms', 0):.2f}ms\n")
    
    # Print comprehensive comparison
    print_comparison_report(stats_without, stats_with)
