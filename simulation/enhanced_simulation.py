"""
Enhanced Simulation with Detailed Visualization
================================================
Simulasi PSKC yang menunjukkan secara detail:
  1. Prediksi model ML dan akurasinya
  2. Interaksi L1 + L2 cache
  3. Perilaku prefetch worker
  4. Fallback ke KMS ketika cache miss
  5. Handling KMS miss vs prediction miss

Alur yang ditunjukkan:
  ┌─────────────────────────────────────┐
  │ CLIENT REQUEST                      │
  │ key_id = "user_123:key_456"        │
  └──────────────┬──────────────────────┘
                 │
        ┌────────▼─────────┐
        │ L1 (In-Memory)   │
        │ Local Cache      │
        └────────┬─────────┘
                 │
              HIT?
            /     \
           Y       N
           │       └──────────┐
           │                  │
      ┌────▼──────┐    ┌──────▼──────┐
      │ Return    │    │ L2 (Redis)  │
      │ plaintext │    │ Cache       │
      └───────────┘    └──────┬──────┘
                               │
                            HIT?
                          /     \
                         Y       N
                         │       └──────────┐
                         │                  │
                    ┌────▼──────┐    ┌──────▼────────────┐
                    │ Return    │    │ Run ML predictor │
                    │ plaintext │    │ (should it exist?)│
                    └───────────┘    └──────┬───────────┘
                                            │
                        ┌───────────────────┼───────────────────┐
                        │                   │                   │
                   PREDICTION          PREDICTION          PREDICTION
                    HIT (0.8)           MISS (0.15)          ERROR (0.05)
                        │                   │                   │
             ┌──────────▼────────┐  ┌───────▼───────┐  ┌──────▼──────┐
             │ Fetch from KMS   │  │ Fetch from    │  │ Fetch from  │
             │ Likely to exist  │  │ KMS (may fail)│  │ KMS (error) │
             │ (high conf)      │  │               │  │             │
             └──────┬───────────┘  └───────┬───────┘  └──────┬──────┘
                    │                      │                 │
            ┌───────▼──────┬────────┐  ┌───▼──────┐  ┌──────▼──────┐
            │              │        │  │          │  │             │
         SUCCESS       SUCCESS   FAIL  FAIL      N/A  FAIL         N/A
            │              │        │  │               │
     ┌──────▼─────┐ ┌──────►─────┐ │  │ ┌──────────┐ │ ┌─────────┐
     │ Cache Hit  │ │            │ │  │ │  ERROR   │ │ │ ERROR  │
     │ (prefetch  │ │ N2:prefetch│ │  │ │ KMS miss │ │ │ KMS   │
     │  correct)  │ │ Queue job  │ │  │ │ predicted │ │ │unable │
     └────────────┘ └────────────┘ │  │ └──────────┘ │ └────────┘
                                    │  │              │
                            ┌───────▼──▼──┐  ┌────────▼───┐
                            │Return error │  │Return error│
                            │to client    │  │to client   │
                            └─────────────┘  └────────────┘
"""

import json
import random
import math
import time
from typing import Dict, List, Tuple


class PredictionModel:
    """Simplified ML ensemble model untuk prediksi next keys"""
    
    def __init__(self, accuracy: float = 0.85):
        self.accuracy = accuracy
        self.prediction_count = 0
        self.correct_count = 0
    
    def predict(self, key_id: str, service: str) -> Tuple[List[str], List[float]]:
        """
        Predict top N next keys yang akan diakses setelah key_id
        
        Returns:
            (predicted_keys, confidences)
        """
        self.prediction_count += 1
        
        # Generate deterministic predictions based on key hash
        # Dalam real system: ensemble(LSTM + RF + Markov)
        seed = hash(f"{key_id}:{service}") % 10000
        random.seed(seed)
        
        # Generate 10 likely next keys
        possible_keys = [f"user_{seed//100}:key_{i}" for i in range(50)]
        
        # Confidence scores (Boltzmann distribution)
        confidences = [
            0.35 + 0.25 * math.exp(-i/5)
            for i in range(10)
        ]
        
        # Normalize
        total = sum(confidences)
        confidences = [c / total for c in confidences]
        
        predicted_keys = random.sample(possible_keys, 10)
        
        return predicted_keys, confidences


class CacheLayer:
    """Simulated L1 or L2 cache"""
    
    def __init__(self, name: str, capacity: int = 10000):
        self.name = name
        self.capacity = capacity
        self.data = {}
        self.access_count = 0
        self.hit_count = 0
    
    def get(self, key_id: str) -> Tuple[bool, str]:
        """
        Try to get key from cache
        
        Returns:
            (hit, plaintext_or_none)
        """
        self.access_count += 1
        
        if key_id in self.data:
            self.hit_count += 1
            value = self.data[key_id]['value']
            return True, value
        
        return False, None
    
    def set(self, key_id: str, value: str):
        """Store key in cache"""
        if len(self.data) >= self.capacity:
            # Simple eviction: remove oldest
            oldest_key = min(self.data.keys(), 
                           key=lambda k: self.data[k]['timestamp'])
            del self.data[oldest_key]
        
        self.data[key_id] = {
            'value': value,
            'timestamp': time.time()
        }
    
    def hit_rate(self) -> float:
        if self.access_count == 0:
            return 0.0
        return self.hit_count / self.access_count


class PrefetchWorker:
    """Simulated prefetch worker yang populate cache proaktif"""
    
    def __init__(self, cache_l1: CacheLayer, cache_l2: CacheLayer):
        self.cache_l1 = cache_l1
        self.cache_l2 = cache_l2
        self.jobs_queued = 0
        self.jobs_processed = 0
        self.prefetch_useful = 0  # Actually used later
    
    def queue_prefetch_job(self, predicted_keys: List[str], kms):
        """Queue job untuk pre-fetch predicted keys"""
        self.jobs_queued += len(predicted_keys)
        
        for key_id in predicted_keys:
            # Simulate: fetch dari KMS dan cache
            try:
                value = kms.fetch(key_id)
                if value:
                    self.cache_l2.set(key_id, value)
                    self.jobs_processed += 1
            except:
                pass  # KMS error, skip
    
    def record_useful_prefetch(self):
        """Record ketika prefetched key benar-benar diakses"""
        self.prefetch_useful += 1


class KeyManagementService:
    """Simulated upstream KMS"""
    
    def __init__(self, failure_rate: float = 0.02):
        self.failure_rate = failure_rate
        self.fetch_count = 0
        self.success_count = 0
        self.failure_count = 0
        self.latency_ms_total = 0.0
    
    def fetch(self, key_id: str) -> str:
        """
        Fetch key material dari KMS
        
        Can return:
          - Key material (success)
          - None (key doesn't exist)
          - Raises exception (KMS error/timeout)
        """
        self.fetch_count += 1
        
        # Simulate KMS latency (log-normal distribution)
        mu, sigma = 4.5, 0.5  # ~90ms average
        latency = math.exp(random.gauss(mu, sigma))
        self.latency_ms_total += latency
        
        # Simulate failures
        if random.random() < self.failure_rate:
            self.failure_count += 1
            raise Exception(f"KMS timeout")
        
        # Simulate key doesn't exist (prediction was wrong)
        if random.random() < 0.05:
            return None  # Key miss at KMS
        
        self.success_count += 1
        # Return simulated key material (encrypted)
        return f"KEY_MATERIAL[{key_id}]"
    
    def avg_latency_ms(self) -> float:
        if self.fetch_count == 0:
            return 0.0
        return self.latency_ms_total / self.fetch_count


class DetailedSimulation:
    """Enhanced PSKC simulation dengan detailed tracing"""
    
    def __init__(self, use_pskc: bool = True, verbose: bool = False):
        self.use_pskc = use_pskc
        self.verbose = verbose
        
        self.cache_l1 = CacheLayer("L1", capacity=1000)
        self.cache_l2 = CacheLayer("L2", capacity=10000)
        self.prefetch = PrefetchWorker(self.cache_l1, self.cache_l2)
        self.predictor = PredictionModel(accuracy=0.85)
        self.kms = KeyManagementService(failure_rate=0.02)
        
        self.results = []
    
    def process_request(self, key_id: str, service: str) -> Dict:
        """
        Process single key access request dengan detailed tracing
        
        Returns:
            {
                'latency_ms': float,
                'cache_layer': str (L1/L2/KMS),
                'path': str (detailed path taken),
                'success': bool,
                'details': {...}
            }
        """
        start_time = time.time()
        trace = []
        
        trace.append(f"→ Request key_id={key_id} service={service}")
        
        # === LAYER 1: L1 Local In-Memory Cache ===
        l1_hit, l1_value = self.cache_l1.get(key_id)
        trace.append(f"  L1 cache: {'HIT ✓' if l1_hit else 'MISS ✗'}")
        
        if l1_hit:
            latency = (time.time() - start_time) * 1000
            if self.verbose:
                print('\n'.join(trace))
                print(f"  ⏱ {latency:.2f}ms")
            
            return {
                'latency_ms': latency,
                'cache_layer': 'L1',
                'path': 'Direct L1 hit',
                'success': True,
                'details': {'l1_hit': True}
            }
        
        # === LAYER 2: L2 Redis Cache ===
        l2_hit, l2_value = self.cache_l2.get(key_id)
        trace.append(f"  L2 cache: {'HIT ✓' if l2_hit else 'MISS ✗'}")
        
        if l2_hit:
            # Move to L1 for next access
            self.cache_l1.set(key_id, l2_value)
            latency = (time.time() - start_time) * 1000
            
            if self.verbose:
                print('\n'.join(trace))
                print(f"  ⏱ {latency:.2f}ms")
            
            return {
                'latency_ms': latency,
                'cache_layer': 'L2',
                'path': 'L1 miss → L2 hit',
                'success': True,
                'details': {'l1_hit': False, 'l2_hit': True}
            }
        
        # === NO CACHE HIT: Need to fetch from KMS ===
        trace.append(f"  Both L1 & L2: MISS")
        
        if not self.use_pskc:
            # No prediction: direct KMS fetch
            trace.append(f"  [NO PSKC MODE] Direct KMS fetch")
            
            try:
                value = self.kms.fetch(key_id)
                if value is None:
                    trace.append(f"  KMS result: KEY DOES NOT EXIST")
                    if self.verbose:
                        print('\n'.join(trace))
                    
                    return {
                        'latency_ms': (time.time() - start_time) * 1000,
                        'cache_layer': 'KMS',
                        'path': 'L1/L2 miss → KMS miss',
                        'success': False,
                        'details': {'kms_miss': True}
                    }
                
                trace.append(f"  KMS fetch: SUCCESS ✓")
                self.cache_l1.set(key_id, value)
                self.cache_l2.set(key_id, value)
                
            except Exception as e:
                trace.append(f"  KMS fetch: ERROR ({str(e)})")
                if self.verbose:
                    print('\n'.join(trace))
                
                return {
                    'latency_ms': (time.time() - start_time) * 1000,
                    'cache_layer': 'KMS',
                    'path': 'L1/L2 miss → KMS error',
                    'success': False,
                    'details': {'kms_error': True}
                }
        
        else:
            # PSKC MODE: Run prediction first
            trace.append(f"  [PSKC MODE] Run ML predictor")
            
            predicted_keys, confidences = self.predictor.predict(key_id, service)
            trace.append(f"  Prediction: {len(predicted_keys)} keys, top conf={confidences[0]:.2f}")
            
            # Check if requested key is in predictions
            if key_id in predicted_keys:
                trace.append(f"  ✓ Key {key_id} in predictions!")
                
                # Try to fetch with high confidence
                try:
                    value = self.kms.fetch(key_id)
                    if value is None:
                        trace.append(f"  ⚠ KMS miss (predicted but doesn't exist)")
                        if self.verbose:
                            print('\n'.join(trace))
                        
                        return {
                            'latency_ms': (time.time() - start_time) * 1000,
                            'cache_layer': 'KMS',
                            'path': 'Predicted hit → KMS miss',
                            'success': False,
                            'details': {'predicted': True, 'kms_miss': True}
                        }
                    
                    trace.append(f"  KMS fetch (predicted): SUCCESS ✓")
                    self.cache_l1.set(key_id, value)
                    self.cache_l2.set(key_id, value)
                    
                except Exception as e:
                    trace.append(f"  KMS error: {str(e)}")
                    if self.verbose:
                        print('\n'.join(trace))
                    
                    return {
                        'latency_ms': (time.time() - start_time) * 1000,
                        'cache_layer': 'KMS',
                        'path': 'Predicted hit → KMS error',
                        'success': False,
                        'details': {'predicted': True, 'kms_error': True}
                    }
            
            else:
                trace.append(f"  ✗ Key {key_id} NOT in predictions (prediction miss)")
                
                # Still try KMS (fallback)
                try:
                    value = self.kms.fetch(key_id)
                    if value is None:
                        trace.append(f"  KMS: key doesn't exist (prediction was correct!)")
                        if self.verbose:
                            print('\n'.join(trace))
                        
                        return {
                            'latency_ms': (time.time() - start_time) * 1000,
                            'cache_layer': 'KMS',
                            'path': 'Prediction miss + KMS miss',
                            'success': False,
                            'details': {'predicted': False, 'kms_miss': True}
                        }
                    
                    trace.append(f"  KMS fetch (not predicted): SUCCESS ✓")
                    self.cache_l1.set(key_id, value)
                    self.cache_l2.set(key_id, value)
                    
                except Exception as e:
                    trace.append(f"  KMS error: {str(e)}")
                    if self.verbose:
                        print('\n'.join(trace))
                    
                    return {
                        'latency_ms': (time.time() - start_time) * 1000,
                        'cache_layer': 'KMS',
                        'path': 'Prediction miss + KMS error',
                        'success': False,
                        'details': {'predicted': False, 'kms_error': True}
                    }
            
            # Queue prefetch jobs after successful fetch
            self.prefetch.queue_prefetch_job(predicted_keys, self.kms)
        
        latency = (time.time() - start_time) * 1000
        
        if self.verbose:
            print('\n'.join(trace))
            print(f"  ⏱ {latency:.2f}ms")
        
        return {
            'latency_ms': latency,
            'cache_layer': 'KMS',
            'path': 'KMS fetch (after cache miss)',
            'success': True,
            'details': {'cache_miss': True, 'kms_fetch': True}
        }
    
    def run_batch(self, n_requests: int = 1000, service: str = "api"):
        """Run batch requests and collect statistics"""
        
        # Generate realistic key access patterns
        # Most popular keys accessed frequently
        popular_keys = [f"user_{i}:key_{j}" 
                       for i in range(10) 
                       for j in range(20)]
        
        results = []
        
        for _ in range(n_requests):
            # 80% of requests are to 20% of keys (Pareto) 
            if random.random() < 0.8:
                key_id = random.choice(popular_keys[:40])  # Top 40 keys
            else:
                key_id = f"user_{random.randint(0, 100)}:key_{random.randint(0, 100)}"
            
            result = self.process_request(key_id, service)
            results.append(result)
        
        self.results = results
        return self._aggregate_stats()
    
    def _aggregate_stats(self) -> Dict:
        """Aggregate simulation results"""
        
        latencies = sorted([r['latency_ms'] for r in self.results])
        n = len(latencies)
        
        if n == 0:
            # Return zeros if no results
            return self._empty_stats()
        
        success_count = sum(1 for r in self.results if r['success'])
        
        # Cache layer breakdown
        l1_count = sum(1 for r in self.results if r['cache_layer'] == 'L1')
        l2_count = sum(1 for r in self.results if r['cache_layer'] == 'L2')
        kms_count = sum(1 for r in self.results if r['cache_layer'] == 'KMS')
        
        # Calculate average latency properly
        avg_latency = sum(latencies) / n if n > 0 else 0
        
        return {
            'mode': 'PSKC' if self.use_pskc else 'No Cache',
            'n_requests': n,
            'success_rate': success_count / n if n > 0 else 0,
            
            # Latency stats
            'avg_latency_ms': avg_latency,
            'p50_latency_ms': latencies[int(n * 0.50)] if n > 0 else 0,
            'p95_latency_ms': latencies[int(n * 0.95)] if n > 0 else 0,
            'p99_latency_ms': latencies[int(n * 0.99)] if n > 0 else 0,
            'min_latency_ms': latencies[0] if n > 0 else 0,
            'max_latency_ms': latencies[-1] if n > 0 else 0,
            
            # Cache breakdown
            'l1_hits': l1_count,
            'l2_hits': l2_count,
            'kms_fetches': kms_count,
            'l1_ratio': l1_count / n,
            'l2_ratio': l2_count / n,
            'kms_ratio': kms_count / n,
            'composite_cache_hit': (l1_count + l2_count) / n,
            
            # Component stats
            'kms_avg_latency_ms': self.kms.avg_latency_ms(),
            'kms_success_rate': self.kms.success_count / self.kms.fetch_count if self.kms.fetch_count > 0 else 0,
            
            'prefetch_jobs_queued': self.prefetch.jobs_queued,
            'prefetch_jobs_processed': self.prefetch.jobs_processed,
            'prefetch_success_rate': self.prefetch.jobs_processed / self.prefetch.jobs_queued if self.prefetch.jobs_queued > 0 else 0,
        }
    
    def _empty_stats(self) -> Dict:
        """Return empty stats when no results"""
        return {
            'mode': 'PSKC' if self.use_pskc else 'No Cache',
            'n_requests': 0,
            'success_rate': 0,
            'avg_latency_ms': 0,
            'p50_latency_ms': 0,
            'p95_latency_ms': 0,
            'p99_latency_ms': 0,
            'min_latency_ms': 0,
            'max_latency_ms': 0,
            'l1_hits': 0,
            'l2_hits': 0,
            'kms_fetches': 0,
            'l1_ratio': 0,
            'l2_ratio': 0,
            'kms_ratio': 0,
            'composite_cache_hit': 0,
            'kms_avg_latency_ms': 0,
            'kms_success_rate': 0,
            'prefetch_jobs_queued': 0,
            'prefetch_jobs_processed': 0,
            'prefetch_success_rate': 0,
        }


def print_detailed_comparison(stats_without: Dict, stats_with: Dict):
    """Print side-by-side comparison with visualizations"""
    
    print("\n" + "="*100)
    print("DETAILED COMPARISON: WITHOUT PSKC vs WITH PSKC")
    print("="*100)
    
    # === LATENCY STATS ===
    print("\n[LATENCY STATISTICS] (milliseconds)")
    print("-" * 100)
    print(f"{'Metric':<20} {'Without PSKC':>20} {'With PSKC':>20} {'Improvement':>20}")
    print("-" * 100)
    
    for metric in ['p50_latency_ms', 'p95_latency_ms', 'p99_latency_ms', 'avg_latency_ms']:
        without = stats_without[metric]
        with_pskc = stats_with[metric]
        
        # Avoid division by zero
        if without > 0:
            improvement = (1 - with_pskc / without) * 100
        else:
            improvement = 0
        
        print(f"{metric:<20} {without:>20.2f} {with_pskc:>20.2f} {improvement:>19.1f}% DOWN")
    
    # === CACHE LAYER BREAKDOWN ===
    print("\n[CACHE LAYER BREAKDOWN]")
    print("-" * 100)
    print(f"{'Layer':<20} {'Without PSKC':>20} {'With PSKC':>20}")
    print("-" * 100)
    
    print(f"{'L1 Hit Rate':<20} {stats_without['l1_ratio']*100:>19.1f}% {stats_with['l1_ratio']*100:>19.1f}%")
    print(f"{'L2 Hit Rate':<20} {stats_without['l2_ratio']*100:>19.1f}% {stats_with['l2_ratio']*100:>19.1f}%")
    print(f"{'KMS Fetches':<20} {stats_without['kms_ratio']*100:>19.1f}% {stats_with['kms_ratio']*100:>19.1f}%")
    print(f"{'Combined Hit Rate':<20} {stats_without['composite_cache_hit']*100:>19.1f}% {stats_with['composite_cache_hit']*100:>19.1f}%")
    
    # === PREFETCH EFFECTIVENESS ===
    print("\n[PREFETCH WORKER EFFECTIVENESS] (PSKC ONLY)")
    print("-" * 100)
    print(f"{'Metric':<40} {'Value':>20}")
    print("-" * 100)
    print(f"{'Jobs Queued':<40} {stats_with['prefetch_jobs_queued']:>20}")
    print(f"{'Jobs Processed':<40} {stats_with['prefetch_jobs_processed']:>20}")
    print(f"{'Success Rate':<40} {stats_with['prefetch_success_rate']*100:>19.1f}%")
    
    # === SUCCESS RATES ===
    print("\n[SUCCESS RATES]")
    print("-" * 100)
    print(f"{'Mode':<20} {'Success Rate':>20} {'KMS Errors':>20}")
    print("-" * 100)
    
    without_kms_fail = (1 - stats_without['kms_success_rate']) * 100
    with_kms_fail = (1 - stats_with['kms_success_rate']) * 100
    
    print(f"{'Without PSKC':<20} {stats_without['success_rate']*100:>19.1f}% {without_kms_fail:>19.1f}% KMS fail")
    print(f"{'With PSKC':<20} {stats_with['success_rate']*100:>19.1f}% {with_kms_fail:>19.1f}% KMS fail")
    
    # === VISUAL REPRESENTATION ===
    print("\n[VISUAL COMPARISON: P99 LATENCY]")
    print("-" * 100)
    
    max_latency = max(stats_without['p99_latency_ms'], stats_with['p99_latency_ms'])
    if max_latency == 0:
        max_latency = 1
    
    without_bar = int(stats_without['p99_latency_ms'] / max_latency * 50)
    with_bar = int(stats_with['p99_latency_ms'] / max_latency * 50)
    
    print(f"Without PSKC | {'#' * without_bar}{'-' * (50 - without_bar)} {stats_without['p99_latency_ms']:.1f}ms")
    print(f"   With PSKC | {'#' * with_bar}{'-' * (50 - with_bar)} {stats_with['p99_latency_ms']:.1f}ms")
    
    # === FINANCIAL IMPACT ===
    print("\n[ESTIMATED FINANCIAL IMPACT] (per 1M requests)")
    print("-" * 100)
    
    # Assumptions:
    # - Without PSKC: avg 200ms per request = 200,000 seconds = 55.6 hours of compute
    # - With PSKC: avg 20ms per request = 20,000 seconds = 5.6 hours of compute
    # - AWS compute: $1.50 per hour (estimates vary)
    
    compute_cost_per_hour = 1.50
    
    without_hours = stats_without['avg_latency_ms'] / 1000 * 1_000_000 / 3600
    with_hours = stats_with['avg_latency_ms'] / 1000 * 1_000_000 / 3600
    
    without_cost = without_hours * compute_cost_per_hour
    with_cost = with_hours * compute_cost_per_hour
    savings = without_cost - with_cost
    
    if without_cost > 0:
        savings_pct = (savings / without_cost) * 100
    else:
        savings_pct = 0
    
    print(f"{'Compute Time (hours)':<40} {without_hours:>20.1f} {with_hours:>20.1f}")
    print(f"{'Compute Cost':<40} ${without_cost:>19.2f} ${with_cost:>19.2f}")
    print(f"{'Savings':<40} {'':>20} ${savings:>19.2f} ({savings_pct:.1f}%)")
    
    print("\n" + "="*100 + "\n")


if __name__ == "__main__":
    print("\n=== Running Enhanced PSKC Simulation with Detailed Visualization ===\n")
    
    # === RUN TWO SIMULATIONS ===
    print("Simulating WITHOUT PSKC...")
    sim_without = DetailedSimulation(use_pskc=False, verbose=False)
    stats_without = sim_without.run_batch(n_requests=2000)
    
    print("Simulating WITH PSKC...")
    sim_with = DetailedSimulation(use_pskc=True, verbose=False)
    stats_with = sim_with.run_batch(n_requests=2000)
    
    # === PRINT RESULTS ===
    print_detailed_comparison(stats_without, stats_with)
    
    # === DETAILED TRACE EXAMPLE ===
    print("\n=== SAMPLE REQUEST TRACES (Verbose Mode) ===")
    print("-" * 100)
    
    print("\n[WITHOUT PSKC] Sample requests (first 3):")
    print("=" * 100)
    sim_example_without = DetailedSimulation(use_pskc=False, verbose=True)
    for i in range(3):
        key_id = f"user_0:key_{i}"
        result = sim_example_without.process_request(key_id, "api")
        print()
    
    print("\n[WITH PSKC] Sample requests (first 3):")
    print("=" * 100)
    sim_example_with = DetailedSimulation(use_pskc=True, verbose=True)
    for i in range(3):
        key_id = f"user_0:key_{i}"
        result = sim_example_with.process_request(key_id, "api")
        print()
