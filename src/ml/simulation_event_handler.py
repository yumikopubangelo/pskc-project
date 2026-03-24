# ============================================================
# PSKC — Simulation Event Handler Module
# Capture and process events from simulations for model learning
# ============================================================
import time
import logging
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from collections import defaultdict, Counter
from datetime import datetime
import statistics

logger = logging.getLogger(__name__)


@dataclass
class SimulationEvent:
    """Single event from a simulation"""
    simulation_id: str          # Which simulation this came from
    timestamp: float            # When it happened (Unix timestamp)
    key_id: str                 # Which key was accessed
    service_id: str             # Which service accessed it
    access_type: str = "read"   # 'read', 'write', 'delete'
    latency_ms: float = 0.0     # Latency in milliseconds
    cache_hit: bool = False     # Cache hit or miss
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return asdict(self)


class SimulationEventCollector:
    """
    Collect events from simulations during execution.
    Provides start_collection() and finish_collection() API.
    """
    
    def __init__(self):
        self.events: List[SimulationEvent] = []
        self.simulation_id: Optional[str] = None
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self._is_collecting = False
    
    def start_collection(self, simulation_id: str):
        """Begin collecting events for a simulation"""
        self.simulation_id = simulation_id
        self.events = []
        self.start_time = time.time()
        self._is_collecting = True
        logger.info(f"SimulationEventCollector: Started collection for {simulation_id}")
    
    def add_event(self, event: SimulationEvent):
        """Add a single event during simulation"""
        if not self._is_collecting:
            logger.warning("SimulationEventCollector: Attempted to add event while not collecting")
            return
        
        # Ensure simulation_id matches
        if event.simulation_id != self.simulation_id:
            logger.warning(f"SimulationEventCollector: Event simulation_id mismatch")
            event.simulation_id = self.simulation_id
        
        self.events.append(event)
    
    def add_events(self, events: List[SimulationEvent]):
        """Add multiple events"""
        for event in events:
            self.add_event(event)
    
    def finish_collection(self) -> List[SimulationEvent]:
        """Finish collection and return all collected events"""
        self.end_time = time.time()
        self._is_collecting = False
        
        collection_duration = self.end_time - self.start_time
        logger.info(
            f"SimulationEventCollector: Finished collection for {self.simulation_id} "
            f"({len(self.events)} events, {collection_duration:.2f}s)"
        )
        
        return self.events.copy()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get collection statistics"""
        if not self.start_time:
            return {}
        
        duration = (self.end_time or time.time()) - self.start_time
        
        # Calculate event statistics
        if self.events:
            latencies = [e.latency_ms for e in self.events]
            cache_hits = sum(1 for e in self.events if e.cache_hit)
        else:
            latencies = []
            cache_hits = 0
        
        return {
            "simulation_id": self.simulation_id,
            "event_count": len(self.events),
            "duration_seconds": duration,
            "events_per_second": len(self.events) / max(duration, 0.1),
            "avg_latency_ms": statistics.mean(latencies) if latencies else 0.0,
            "p95_latency_ms": self._percentile(latencies, 0.95),
            "p99_latency_ms": self._percentile(latencies, 0.99),
            "cache_hit_rate": cache_hits / len(self.events) if self.events else 0.0,
            "is_collecting": self._is_collecting,
        }
    
    @staticmethod
    def _percentile(values: List[float], percentile: float) -> float:
        """Calculate percentile of values"""
        if not values:
            return 0.0
        sorted_values = sorted(values)
        index = int(len(sorted_values) * percentile)
        index = min(index, len(sorted_values) - 1)
        return sorted_values[index]


class SimulationEventNormalizer:
    """
    Convert simulation events to training data feature vectors.
    Matches the feature format used in training data generation.
    """
    
    # Feature scaling parameters - adjust based on your data
    LATENCY_SCALE = 100.0      # Scale latency to 0-1 range
    FREQUENCY_SCALE = 1000.0    # Scale frequency
    
    def __init__(self, context_window: int = 100):
        """
        Initialize normalizer.
        
        Args:
            context_window: Number of events to look back for features
        """
        self.context_window = context_window
        self._event_history: List[SimulationEvent] = []
    
    def normalize(self, event: SimulationEvent, 
                  context_events: Optional[List[SimulationEvent]] = None) -> Dict[str, float]:
        """
        Convert single event to feature vector matching training format.
        
        Returns dict with normalized features:
        - frequency: How often this key appears (0-1)
        - recency: How recently accessed (0-1, 1=just now)
        - temporal_entropy: Variability in access timing (0-1)
        - locality_score: Co-access with other keys (0-1)
        - cache_hit_rate: Historical cache hit rate (0-1)
        - latency_normalized: Normalized latency (0-1)
        - service_concentration: Fraction of accesses by this service (0-1)
        """
        
        if context_events is None:
            context_events = []
        
        # Build context from recent events
        all_events = context_events + [event]
        all_events = all_events[-self.context_window:]
        
        features = {}
        
        # 1. Frequency: How often does this key appear in context
        key_count = sum(1 for e in all_events if e.key_id == event.key_id)
        features['frequency'] = min(key_count / len(all_events), 1.0) if all_events else 0.0
        
        # 2. Recency: Time since last access of this key
        key_events = [e for e in reversed(all_events) if e.key_id == event.key_id]
        if len(key_events) > 1:
            # Multiple accesses - calculate recency
            time_diff = all_events[-1].timestamp - key_events[1].timestamp
            max_time_diff = all_events[-1].timestamp - all_events[0].timestamp
            recency = 1.0 - min(time_diff / max(max_time_diff, 1.0), 1.0)
        else:
            recency = 1.0  # First access, very recent
        features['recency'] = recency
        
        # 3. Temporal Entropy: Variability in inter-arrival times
        key_timestamps = [e.timestamp for e in all_events if e.key_id == event.key_id]
        if len(key_timestamps) > 2:
            inter_arrivals = [
                key_timestamps[i+1] - key_timestamps[i]
                for i in range(len(key_timestamps) - 1)
            ]
            if inter_arrivals:
                mean_iat = statistics.mean(inter_arrivals)
                stdev_iat = statistics.stdev(inter_arrivals) if len(inter_arrivals) > 1 else 0.0
                # Normalize entropy to 0-1
                temporal_entropy = min(stdev_iat / max(mean_iat, 0.001), 1.0)
            else:
                temporal_entropy = 0.0
        else:
            temporal_entropy = 0.0
        features['temporal_entropy'] = temporal_entropy
        
        # 4. Locality Score: Co-access with other keys
        # Calculate Jaccard similarity with other recent keys
        event_keys = set(e.key_id for e in all_events[-20:])  # Last 20 events
        event_local_keys = set(e.key_id for e in all_events 
                               if e.key_id == event.key_id)
        
        if len(event_keys) > 1:
            # Find keys accessed near this key
            locality_keys = set()
            for idx, e in enumerate(all_events):
                if e.key_id == event.key_id:
                    # Look at nearby events (±5)
                    start = max(0, idx - 5)
                    end = min(len(all_events), idx + 6)
                    locality_keys.update(e2.key_id for e2 in all_events[start:end])
            
            if locality_keys:
                locality_score = len(locality_keys) / len(event_keys)
            else:
                locality_score = 0.0
        else:
            locality_score = 0.5
        features['locality_score'] = min(locality_score, 1.0)
        
        # 5. Cache Hit Rate: Historical cache hits for this key
        key_accesses = [e for e in all_events if e.key_id == event.key_id]
        if key_accesses:
            cache_hits = sum(1 for e in key_accesses if e.cache_hit)
            features['cache_hit_rate'] = cache_hits / len(key_accesses)
        else:
            features['cache_hit_rate'] = 0.5
        
        # 6. Latency Normalized: Normalize latency to 0-1
        features['latency_normalized'] = min(event.latency_ms / self.LATENCY_SCALE, 1.0)
        
        # 7. Service Concentration: Fraction of recent accesses by this service
        service_count = sum(1 for e in all_events if e.service_id == event.service_id)
        features['service_concentration'] = service_count / len(all_events) if all_events else 0.0
        
        # 8. Access Type (one-hot encoded as separate features)
        access_types = {'read': 0, 'write': 1, 'delete': 2}
        access_type_id = access_types.get(event.access_type, 0)
        features['access_type_read'] = float(access_type_id == 0)
        features['access_type_write'] = float(access_type_id == 1)
        features['access_type_delete'] = float(access_type_id == 2)
        
        return features
    
    def normalize_batch(self, events: List[SimulationEvent]) -> List[Dict[str, float]]:
        """
        Normalize multiple events using sliding context window.
        
        Returns list of feature dicts in same order as input events.
        """
        normalized = []
        context = []
        
        for event in events:
            features = self.normalize(event, context)
            normalized.append(features)
            context.append(event)
            
            # Keep context window size reasonable
            if len(context) > self.context_window:
                context = context[-self.context_window:]
        
        return normalized


class SimulationPatternExtractor:
    """
    Extract high-level patterns from simulation events.
    Patterns are used for drift detection against training data.
    """
    
    def __init__(self):
        self.events: List[SimulationEvent] = []
    
    def extract_patterns(self, events: List[SimulationEvent]) -> Dict[str, Any]:
        """
        Extract comprehensive patterns from simulation events.
        
        Returns dict containing:
        - key_frequency_distribution: Counter of key accesses
        - service_distribution: Counter of service accesses
        - access_type_distribution: Counter of access types
        - latency_stats: Mean, median, p95, p99 latencies
        - cache_hit_statistics: Hit rate and distribution
        - temporal_patterns: Inter-arrival times and entropy
        - sequence_patterns: Bigrams and trigrams of key accesses
        - burst_patterns: Bursty access detection
        """
        self.events = events
        
        if not events:
            return self._empty_patterns()
        
        patterns = {
            'event_count': len(events),
            'duration_seconds': events[-1].timestamp - events[0].timestamp if events else 0,
            'time_range': {
                'start': datetime.fromtimestamp(events[0].timestamp).isoformat() if events else None,
                'end': datetime.fromtimestamp(events[-1].timestamp).isoformat() if events else None,
            },
        }
        
        # 1. Key Frequency Distribution
        patterns['key_frequency_distribution'] = dict(
            Counter(e.key_id for e in events).most_common(50)  # Top 50 keys
        )
        
        # 2. Service Distribution
        patterns['service_distribution'] = dict(
            Counter(e.service_id for e in events)
        )
        
        # 3. Access Type Distribution
        patterns['access_type_distribution'] = dict(
            Counter(e.access_type for e in events)
        )
        
        # 4. Latency Statistics
        latencies = [e.latency_ms for e in events]
        patterns['latency_stats'] = {
            'mean': statistics.mean(latencies) if latencies else 0.0,
            'median': statistics.median(latencies) if latencies else 0.0,
            'stdev': statistics.stdev(latencies) if len(latencies) > 1 else 0.0,
            'p95': self._percentile(latencies, 0.95),
            'p99': self._percentile(latencies, 0.99),
            'min': min(latencies) if latencies else 0.0,
            'max': max(latencies) if latencies else 0.0,
        }
        
        # 5. Cache Hit Statistics
        cache_hits = sum(1 for e in events if e.cache_hit)
        patterns['cache_hit_stats'] = {
            'hit_count': cache_hits,
            'miss_count': len(events) - cache_hits,
            'hit_rate': cache_hits / len(events) if events else 0.0,
        }
        
        # 6. Temporal Patterns (inter-arrival times)
        patterns['temporal_patterns'] = self._extract_temporal_patterns(events)
        
        # 7. Sequence Patterns (bigrams, trigrams)
        patterns['sequence_patterns'] = self._extract_sequence_patterns(events)
        
        # 8. Burst Patterns
        patterns['burst_patterns'] = self._detect_bursts(events)
        
        # 9. Key Co-access Patterns (which keys are accessed together)
        patterns['coAccess_patterns'] = self._extract_coAccess_patterns(events)
        
        return patterns
    
    def _extract_temporal_patterns(self, events: List[SimulationEvent]) -> Dict[str, Any]:
        """Extract inter-arrival time patterns"""
        if len(events) < 2:
            return {'inter_arrival_times': [], 'entropy': 0.0}
        
        iats = [
            events[i+1].timestamp - events[i].timestamp
            for i in range(len(events) - 1)
        ]
        
        return {
            'inter_arrival_mean': statistics.mean(iats) if iats else 0.0,
            'inter_arrival_stdev': statistics.stdev(iats) if len(iats) > 1 else 0.0,
            'inter_arrival_entropy': self._calculate_entropy(iats),
            'spike_count': sum(1 for iat in iats if iat > statistics.mean(iats) * 2),
        }
    
    def _extract_sequence_patterns(self, events: List[SimulationEvent]) -> Dict[str, Any]:
        """Extract key sequence patterns (bigrams, trigrams)"""
        key_sequence = [e.key_id for e in events]
        
        # Bigrams (2-grams)
        bigrams = [
            (key_sequence[i], key_sequence[i+1])
            for i in range(len(key_sequence) - 1)
        ]
        
        # Trigrams (3-grams)
        trigrams = [
            (key_sequence[i], key_sequence[i+1], key_sequence[i+2])
            for i in range(len(key_sequence) - 2)
        ]
        
        return {
            'bigram_count': len(bigrams),
            'trigram_count': len(trigrams),
            'top_bigrams': dict(Counter(bigrams).most_common(10)),
            'top_trigrams': dict([
                (str(k), v) for k, v in Counter(trigrams).most_common(5)
            ]),
            'unique_bigrams': len(set(bigrams)),
            'unique_trigrams': len(set(trigrams)),
        }
    
    def _detect_bursts(self, events: List[SimulationEvent]) -> Dict[str, Any]:
        """Detect burst patterns in access"""
        if len(events) < 2:
            return {'burst_count': 0, 'mean_burst_size': 0, 'max_burst_size': 0}
        
        # Simple burst detection: consecutive events within short time
        burst_threshold = 0.1  # 100ms
        bursts = []
        current_burst = [events[0]]
        
        for event in events[1:]:
            if event.timestamp - current_burst[-1].timestamp < burst_threshold:
                current_burst.append(event)
            else:
                if len(current_burst) > 1:
                    bursts.append(current_burst)
                current_burst = [event]
        
        if len(current_burst) > 1:
            bursts.append(current_burst)
        
        burst_sizes = [len(b) for b in bursts]
        
        return {
            'burst_count': len(bursts),
            'mean_burst_size': statistics.mean(burst_sizes) if burst_sizes else 0.0,
            'max_burst_size': max(burst_sizes) if burst_sizes else 0,
            'total_burst_events': sum(burst_sizes),
        }
    
    def _extract_coAccess_patterns(self, events: List[SimulationEvent]) -> Dict[str, Any]:
        """Extract which keys are accessed together (co-access)"""
        window_size = 10  # Look at groups of 10 consecutive events
        coAccess_pairs = Counter()
        
        for i in range(len(events) - window_size):
            window_keys = set(e.key_id for e in events[i:i+window_size])
            # All pairs within window
            keys_list = list(window_keys)
            for j in range(len(keys_list)):
                for k in range(j+1, len(keys_list)):
                    pair = tuple(sorted([keys_list[j], keys_list[k]]))
                    coAccess_pairs[pair] += 1
        
        return {
            'coAccess_pairs': len(coAccess_pairs),
            'top_coAccess_pairs': dict(coAccess_pairs.most_common(10)),
        }
    
    @staticmethod
    def _percentile(values: List[float], percentile: float) -> float:
        """Calculate percentile"""
        if not values:
            return 0.0
        sorted_values = sorted(values)
        index = int(len(sorted_values) * percentile)
        index = min(index, len(sorted_values) - 1)
        return sorted_values[index]
    
    @staticmethod
    def _calculate_entropy(values: List[float]) -> float:
        """Calculate Shannon entropy of values (binned)"""
        if not values:
            return 0.0
        
        # Bin values into 10 bins
        min_val, max_val = min(values), max(values)
        if min_val == max_val:
            return 0.0
        
        bins = 10
        bin_width = (max_val - min_val) / bins
        bin_counts = [0] * bins
        
        for val in values:
            bin_idx = min(int((val - min_val) / bin_width), bins - 1)
            bin_counts[bin_idx] += 1
        
        # Shannon entropy
        total = len(values)
        entropy = 0.0
        for count in bin_counts:
            if count > 0:
                prob = count / total
                entropy -= prob * (prob ** 0.5)  # Simplified entropy
        
        return entropy
    
    @staticmethod
    def _empty_patterns() -> Dict[str, Any]:
        """Return empty pattern structure"""
        return {
            'event_count': 0,
            'duration_seconds': 0,
            'time_range': {'start': None, 'end': None},
            'key_frequency_distribution': {},
            'service_distribution': {},
            'access_type_distribution': {},
            'latency_stats': {},
            'cache_hit_stats': {},
            'temporal_patterns': {},
            'sequence_patterns': {},
            'burst_patterns': {},
            'coAccess_patterns': {},
        }
    
    def get_pattern_summary(self, patterns: Dict[str, Any]) -> str:
        """Generate human-readable summary of patterns"""
        summary = []
        summary.append(f"Events: {patterns.get('event_count', 0)}")
        summary.append(f"Duration: {patterns.get('duration_seconds', 0):.1f}s")
        
        latency = patterns.get('latency_stats', {})
        if latency:
            summary.append(f"Avg Latency: {latency.get('mean', 0):.1f}ms")
        
        cache = patterns.get('cache_hit_stats', {})
        if cache:
            summary.append(f"Cache Hit Rate: {cache.get('hit_rate', 0)*100:.1f}%")
        
        return " | ".join(summary)


# Singleton instance for easy access
_simulation_event_collector: Optional[SimulationEventCollector] = None


def get_simulation_event_collector() -> SimulationEventCollector:
    """Get or create singleton simulation event collector"""
    global _simulation_event_collector
    if _simulation_event_collector is None:
        _simulation_event_collector = SimulationEventCollector()
    return _simulation_event_collector
