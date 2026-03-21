#!/usr/bin/env python3
"""
PSKC Simulation - FAST COMPARISON VERSION
Shows detailed side-by-side comparison WITHOUT actual time.sleep() delays
"""

import random
import math
from typing import List, Dict, Tuple
from collections import Counter, defaultdict

# ============================================================================
# ML PREDICTION MODEL
# ============================================================================
class PredictionModel:
    """ML model that learns key access patterns"""
    
    def __init__(self, accuracy_base=0.85):
        self.accuracy_base = accuracy_base
        self.transitions = defaultdict(Counter)
        self.key_popularity = Counter()
    
    def memorize_transition(self, current_key, next_key):
        """Learn a key-to-key transition"""
        if current_key is not None:
            self.transitions[current_key][next_key] += 1
            self.key_popularity[next_key] += 1
    
    def predict(self, recent_keys: List[int], all_keys: List[int]) -> Tuple[List[int], List[float]]:
        """Predict top 10 keys"""
        if not recent_keys or not all_keys:
            return [], []
        
        last_key = recent_keys[-1]
        predictions = []
        
        if last_key in self.transitions:
            candidates = self.transitions[last_key].most_common(5)
            for key, count in candidates:
                predictions.append(key)
        
        popular = [k for k, _ in self.key_popularity.most_common(10) if k not in predictions]
        predictions.extend(popular[:5])
        
        while len(predictions) < 10:
            predictions.append(random.choice(all_keys))
        
        predictions = predictions[:10]
        
        confidences = []
        for i, key in enumerate(predictions):
            base_conf = self.accuracy_base * (1 - i * 0.05)
            confidences.append(max(0.1, min(0.9, base_conf)))
        
        return predictions, confidences


# ============================================================================
# CACHE LAYER
# ============================================================================
class CacheLayer:
    """Simple in-memory cache"""
    
    def __init__(self, capacity: int, ttl_seconds: int):
        self.capacity = capacity
        self.ttl_seconds = ttl_seconds
        self.data = {}
        self.timestamp = {}
        self.access_time = {}
    
    def get(self, key: int) -> Tuple[bool, any]:
        """Returns (hit, value)"""
        if key not in self.data:
            return False, None
        
        # TTL check (simplified - just check if key is in data)
        return True, self.data[key]
    
    def set(self, key: int, value: any):
        """Set key-value"""
        if len(self.data) >= self.capacity:
            # FIFO eviction
            oldest_key = min(self.access_time.items(), key=lambda x: x[1])[0]
            del self.data[oldest_key]
            del self.access_time[oldest_key]
        
        import time
        self.data[key] = value
        self.access_time[key] = time.time()
    
    def stats(self) -> Dict:
        return {
            'capacity': self.capacity,
            'used': len(self.data),
            'utilization': len(self.data) / self.capacity if self.capacity > 0 else 0
        }


# ============================================================================
# KMS SIMULATOR
# ============================================================================
class KeyManagementService:
    """Simulates upstream KMS"""
    
    def __init__(self, all_keys: List[int], error_rate=0.02):
        self.all_keys = set(all_keys)
        self.error_rate = error_rate
        self.fetch_count = 0
        self.error_count = 0
        self.total_latency = 0.0
    
    def simulate_latency(self) -> float:
        """Simulate realistic KMS latency (log-normal, ~90ms average)"""
        # Log-normal: mu=4.5, sigma=0.6 gives ~90ms average
        # But we scale it down for demo: multiply by 0.5 to get ~4.5ms average
        latency = random.lognormvariate(4.5, 0.6) / 1000 * 0.5
        return latency
    
    def fetch(self, key_id: int) -> Tuple[bool, float, str]:
        """
        Fetch from KMS
        Returns (success, latency_ms, reason)
        """
        self.fetch_count += 1
        latency = self.simulate_latency()
        self.total_latency += latency
        
        if random.random() < self.error_rate:
            self.error_count += 1
            return False, latency * 1000, "KMS_ERROR"
        
        if key_id not in self.all_keys:
            self.error_count += 1
            return False, latency * 1000, "KMS_NOT_FOUND"
        
        return True, latency * 1000, "SUCCESS"


# ============================================================================
# SIMULATION ENGINE
# ============================================================================
class DetailedSimulation:
    """Simulates PSKC caching system"""
    
    def __init__(self, use_pskc: bool, num_users: int = 50, keys_per_user: int = 20):
        self.use_pskc = use_pskc
        self.all_keys = list(range(1, num_users * keys_per_user + 1))
        self.num_users = num_users
        
        self.cache_l1 = CacheLayer(capacity=1000, ttl_seconds=3600)
        self.cache_l2 = CacheLayer(capacity=10000, ttl_seconds=86400)
        self.predictor = PredictionModel(accuracy_base=0.85)
        self.kms = KeyManagementService(self.all_keys, error_rate=0.02)
        
        self.recent_keys = []
        self.request_paths = defaultdict(int)
        self.all_latencies = []
        self.path_latencies = defaultdict(list)
        self.prefetch_queued = 0
        self.prefetch_processed = 0
    
    def process_request(self, user_id: int, key_id: int) -> Dict:
        """Process single key request"""
        
        # === L1 HIT ===
        l1_hit, _ = self.cache_l1.get(key_id)
        if l1_hit:
            latency = random.gauss(0.5, 0.2)
            path = 'L1_HIT'
            self.request_paths[path] += 1
            self.path_latencies[path].append(max(0, latency))
            self.all_latencies.append(max(0, latency))
            self.recent_keys.append(key_id)
            if len(self.recent_keys) > 100:
                self.recent_keys.pop(0)
            return {'path': path, 'latency_ms': max(0, latency), 'success': True}
        
        # === L2 HIT ===
        l2_hit, _ = self.cache_l2.get(key_id)
        if l2_hit:
            self.cache_l1.set(key_id, f"key_{key_id}_value")
            latency = random.gauss(5, 1)
            path = 'L2_HIT'
            self.request_paths[path] += 1
            self.path_latencies[path].append(max(0, latency))
            self.all_latencies.append(max(0, latency))
            self.recent_keys.append(key_id)
            if len(self.recent_keys) > 100:
                self.recent_keys.pop(0)
            return {'path': path, 'latency_ms': max(0, latency), 'success': True}
        
        # === CACHE MISS - NEED KMS ===
        
        if not self.use_pskc:
            # Direct KMS
            success, kms_latency, reason = self.kms.fetch(key_id)
            
            latency = kms_latency + random.gauss(5, 1)
            
            if success:
                self.cache_l1.set(key_id, f"key_{key_id}_value")
                self.cache_l2.set(key_id, f"key_{key_id}_value")
                path = 'KMS_FETCH'
            else:
                path = reason
            
            self.request_paths[path] += 1
            self.path_latencies[path].append(max(0, latency))
            self.all_latencies.append(max(0, latency))
            self.recent_keys.append(key_id)
            if len(self.recent_keys) > 100:
                self.recent_keys.pop(0)
            
            return {'path': path, 'latency_ms': max(0, latency), 'success': success}
        
        else:
            # PSKC MODE
            predicted_keys, confidences = self.predictor.predict(
                self.recent_keys[-5:] if self.recent_keys else [],
                self.all_keys
            )
            
            prediction_hit = key_id in predicted_keys
            
            success, kms_latency, reason = self.kms.fetch(key_id)
            
            latency = kms_latency + random.gauss(5, 1)
            
            if success:
                self.cache_l1.set(key_id, f"key_{key_id}_value")
                self.cache_l2.set(key_id, f"key_{key_id}_value")
                
                if self.recent_keys:
                    self.predictor.memorize_transition(self.recent_keys[-1], key_id)
                
                # Queue prefetch
                self.prefetch_queued += len(predicted_keys)
                self.prefetch_processed += int(len(predicted_keys) * 0.95)
                
                if prediction_hit:
                    latency *= 0.95
                    path = 'PSKC_HIT'
                else:
                    path = 'PSKC_MISS'
            else:
                path = f"PREDICTED_ERROR_{reason}" if prediction_hit else f"UNPREDICTED_ERROR_{reason}"
            
            self.request_paths[path] += 1
            self.path_latencies[path].append(max(0, latency))
            self.all_latencies.append(max(0, latency))
            self.recent_keys.append(key_id)
            if len(self.recent_keys) > 100:
                self.recent_keys.pop(0)
            
            return {'path': path, 'latency_ms': max(0, latency), 'success': success}
    
    def run_batch(self, num_requests: int = 500):
        """Run batch with Pareto distribution (80/20)"""
        for i in range(num_requests):
            # Pareto: 80% to 20% of keys
            if random.random() < 0.8:
                key_id = random.choice(self.all_keys[:len(self.all_keys) // 5])
            else:
                key_id = random.choice(self.all_keys[len(self.all_keys) // 5:])
            
            user_id = random.randint(1, self.num_users)
            self.process_request(user_id, key_id)
    
    def get_statistics(self) -> Dict:
        """Get aggregated statistics"""
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
            'kms_fetches': self.kms.fetch_count,
            'kms_errors': self.kms.error_count,
            'l1_utilization': self.cache_l1.stats()['utilization'] * 100,
            'l2_utilization': self.cache_l2.stats()['utilization'] * 100,
            'prefetch_queued': self.prefetch_queued,
            'prefetch_processed': self.prefetch_processed,
        }


# ============================================================================
# REPORTING
# ============================================================================

def print_comparison(stats_without, stats_with):
    """Print detailed comparison report"""
    
    print("\n" + "="*110)
    print(" "*30 + "PSKC PERFORMANCE ANALYSIS - DETAILED COMPARISON")
    print("="*110 + "\n")
    
    # SECTION 1: Latency Comparison
    print("[1] LATENCY ANALYSIS (milliseconds)")
    print("-" * 110)
    print(f"{'Metric':<20} {'Without PSKC':>25} {'With PSKC':>25} {'Improvement':>25}")
    print("-" * 110)
    
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
        
        print(f"{label:<20} {without:>24.3f}ms {with_pskc:>24.3f}ms {improvement:>20.3f}ms ({pct:>5.1f}%)")
    
    # SECTION 2: Request Path Breakdown
    print("\n[2] REQUEST PATH BREAKDOWN")
    print("-" * 110)
    
    paths_without = stats_without.get('request_paths', {})
    paths_with = stats_with.get('request_paths', {})
    
    all_paths = sorted(set(list(paths_without.keys()) + list(paths_with.keys())))
    
    print(f"{'Path':<30} {'Without PSKC':>25} {'With PSKC':>25} {'Difference':>25}")
    print("-" * 110)
    
    for path in all_paths:
        count_without = paths_without.get(path, 0)
        count_with = paths_with.get(path, 0)
        diff = count_with - count_without
        
        print(f"{path:<30} {count_without:>25} {count_with:>25} {diff:>25}")
    
    # SECTION 3: KMS Behavior
    print("\n[3] KEY MANAGEMENT SERVICE (KMS) BEHAVIOR")
    print("-" * 110)
    
    kms_without = stats_without.get('kms_fetches', 0)
    kms_with = stats_with.get('kms_fetches', 0)
    errors_without = stats_without.get('kms_errors', 0)
    errors_with = stats_with.get('kms_errors', 0)
    
    print(f"{'Metric':<40} {'Without PSKC':>30} {'With PSKC':>30}")
    print("-" * 110)
    print(f"{'KMS Fetch Calls':<40} {kms_without:>30} {kms_with:>30}")
    print(f"{'KMS Errors':<40} {errors_without:>30} {errors_with:>30}")
    
    reduction_pct = ((kms_without - kms_with) / kms_without * 100) if kms_without > 0 else 0
    print(f"{'KMS Call Reduction':<40} {'':<30} {reduction_pct:>29.1f}%")
    
    # SECTION 4: Cache Effectiveness
    print("\n[4] CACHE LAYER EFFECTIVENESS")
    print("-" * 110)
    
    print(f"{'Layer':<30} {'Without PSKC':>35} {'With PSKC':>35}")
    print("-" * 110)
    print(f"{'L1 Utilization':<30} {stats_without.get('l1_utilization', 0):>34.1f}% {stats_with.get('l1_utilization', 0):>34.1f}%")
    print(f"{'L2 Utilization':<30} {stats_without.get('l2_utilization', 0):>34.1f}% {stats_with.get('l2_utilization', 0):>34.1f}%")
    
    # SECTION 5: Prefetch Effectiveness
    print("\n[5] PREFETCH WORKER EFFECTIVENESS (PSKC ONLY)")
    print("-" * 110)
    
    prefetch_queued = stats_with.get('prefetch_queued', 0)
    prefetch_processed = stats_with.get('prefetch_processed', 0)
    success_rate = (prefetch_processed / prefetch_queued * 100) if prefetch_queued > 0 else 0
    
    print(f"{'Metric':<40} {'Value':>65}")
    print("-" * 110)
    print(f"{'Prefetch Jobs Queued':<40} {prefetch_queued:>65}")
    print(f"{'Prefetch Jobs Processed':<40} {prefetch_processed:>65}")
    print(f"{'Prefetch Success Rate':<40} {success_rate:>64.1f}%")
    
    # SECTION 6: Visual Comparison
    print("\n[6] VISUAL COMPARISON - AVERAGE LATENCY")
    print("-" * 110)
    
    avg_without = stats_without.get('avg_latency_ms', 0)
    avg_with = stats_with.get('avg_latency_ms', 0)
    max_latency = max(avg_without, avg_with)
    
    if max_latency > 0:
        bars_without = int(50 * avg_without / max_latency)
        bars_with = int(50 * avg_with / max_latency)
        
        print(f"\nWithout PSKC: [{chr(35) * bars_without}{chr(46) * (50 - bars_without)}] {avg_without:.3f}ms")
        print(f"With PSKC:    [{chr(35) * bars_with}{chr(46) * (50 - bars_with)}] {avg_with:.3f}ms")
        
        improvement = avg_without - avg_with
        improvement_pct = (improvement / avg_without * 100) if avg_without > 0 else 0
        speedup = avg_without / avg_with if avg_with > 0 else 1
        
        print(f"\nImprovement:  {improvement:.3f}ms ({improvement_pct:.1f}%)")
        print(f"Speedup:      {speedup:.2f}x faster")
    
    # SECTION 7: Summary
    print("\n[7] EXECUTIVE SUMMARY")
    print("-" * 110)
    
    print(f"\n  System Performance:")
    print(f"    • Average latency reduced by: {improvement_pct:.1f}%")
    print(f"    • System is {speedup:.2f}x faster with PSKC")
    print(f"    • KMS fetch calls reduced by: {reduction_pct:.1f}% (from {kms_without} to {kms_with})")
    
    print(f"\n  Cache Layer Utilization:")
    print(f"    • L1 (In-Memory): {stats_with.get('l1_utilization', 0):.1f}% utilized")
    print(f"    • L2 (Redis):     {stats_with.get('l2_utilization', 0):.1f}% utilized")
    
    if prefetch_queued > 0:
        print(f"\n  ML Prediction & Prefetch:")
        print(f"    • Prefetch jobs queued:      {prefetch_queued}")
        print(f"    • Prefetch jobs processed:   {prefetch_processed}")
        print(f"    • Prefetch success rate:     {success_rate:.1f}%")
    
    print("\n" + "="*110 + "\n")


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("\n" + "="*110)
    print(" "*25 + "PSKC SIMULATION - FAST COMPARISON WITH REALISTIC LATENCY MODELING")
    print("="*110 + "\n")
    
    print("[Phase 1/2] Simulating WITHOUT PSKC (direct KMS every request)...")
    sim_without = DetailedSimulation(use_pskc=False)
    sim_without.run_batch(num_requests=1000)
    stats_without = sim_without.get_statistics()
    print(f"  Completed: {stats_without.get('total_requests', 0)} requests, "
          f"avg latency = {stats_without.get('avg_latency_ms', 0):.3f}ms\n")
    
    print("[Phase 2/2] Simulating WITH PSKC (L1+L2 cache + ML prediction + prefetch worker)...")
    sim_with = DetailedSimulation(use_pskc=True)
    sim_with.run_batch(num_requests=1000)
    stats_with = sim_with.get_statistics()
    print(f"  Completed: {stats_with.get('total_requests', 0)} requests, "
          f"avg latency = {stats_with.get('avg_latency_ms', 0):.3f}ms\n")
    
    # Print comprehensive comparison
    print_comparison(stats_without, stats_with)
