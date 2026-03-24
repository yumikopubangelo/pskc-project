# ============================================================
# PSKC — Pattern Analyzer Module
# Detect drift and compare simulation patterns vs training data
# ============================================================
import logging
import math
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class DriftReport:
    """Result of drift analysis between simulation and training patterns"""
    drift_score: float                  # 0-1, higher = more drift
    frequency_divergence: float         # Component scores
    temporal_divergence: float
    sequence_divergence: float
    major_changes: List[str]            # What changed significantly
    recommendations: List[str]          # What to do about it
    details: Dict[str, Any]             # Detailed metrics
    timestamp: float                    # When calculated
    should_retrain: bool                # Quick check: drift > threshold
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses"""
        return {
            'drift_score': round(self.drift_score, 3),
            'frequency_divergence': round(self.frequency_divergence, 3),
            'temporal_divergence': round(self.temporal_divergence, 3),
            'sequence_divergence': round(self.sequence_divergence, 3),
            'major_changes': self.major_changes,
            'recommendations': self.recommendations,
            'timestamp': self.timestamp,
            'should_retrain': self.should_retrain,
        }


class DistributionAnalyzer:
    """Low-level statistical comparison of distributions"""
    
    @staticmethod
    def jensen_shannon_divergence(p_dict: Dict[str, float], 
                                   q_dict: Dict[str, float]) -> float:
        """
        Calculate Jensen-Shannon divergence between two probability distributions.
        
        JS divergence ranges from 0 to 1:
        - 0 = identical distributions
        - 1 = completely different distributions
        
        Args:
            p_dict: First distribution (keys -> probabilities)
            q_dict: Second distribution (keys -> probabilities)
        
        Returns:
            JS divergence score (0-1)
        """
        # Normalize distributions
        p = DistributionAnalyzer._normalize_dict(p_dict)
        q = DistributionAnalyzer._normalize_dict(q_dict)
        
        # Get all keys
        all_keys = set(p.keys()) | set(q.keys())
        
        if not all_keys:
            return 0.0
        
        # Ensure all keys exist in both distributions
        for key in all_keys:
            p[key] = p.get(key, 1e-10)  # Add small epsilon to avoid log(0)
            q[key] = q.get(key, 1e-10)
        
        # Calculate KL divergence both ways
        kl_pq = DistributionAnalyzer._kl_divergence(p, q)
        kl_qp = DistributionAnalyzer._kl_divergence(q, p)
        
        # JS divergence = average of two KL divergences
        js_div = 0.5 * (kl_pq + kl_qp)
        
        # Clamp to 0-1
        return min(max(js_div, 0.0), 1.0)
    
    @staticmethod
    def _kl_divergence(p: Dict[str, float], q: Dict[str, float]) -> float:
        """Calculate KL divergence from p to q"""
        divergence = 0.0
        for key in p.keys():
            p_val = p.get(key, 1e-10)
            q_val = q.get(key, 1e-10)
            if p_val > 0:
                divergence += p_val * math.log(p_val / q_val)
        return max(divergence, 0.0)
    
    @staticmethod
    def _normalize_dict(d: Dict[str, float]) -> Dict[str, float]:
        """Normalize dictionary values to sum to 1"""
        total = sum(d.values())
        if total <= 0:
            return {}
        return {k: v / total for k, v in d.items()}
    
    @staticmethod
    def compare_frequency_distributions(sim_dist: Dict[str, int], 
                                        train_dist: Dict[str, int]) -> Tuple[float, Dict[str, float]]:
        """
        Compare key access frequency distributions.
        
        Returns:
            (divergence_score, changes_dict)
            changes_dict shows which keys have biggest frequency changes
        """
        if not sim_dist or not train_dist:
            return 0.0, {}
        
        # Normalize to probabilities
        sim_prob = DistributionAnalyzer._normalize_dict({k: float(v) for k, v in sim_dist.items()})
        train_prob = DistributionAnalyzer._normalize_dict({k: float(v) for k, v in train_dist.items()})
        
        # Calculate JS divergence
        divergence = DistributionAnalyzer.jensen_shannon_divergence(sim_prob, train_prob)
        
        # Calculate per-key changes
        changes = {}
        all_keys = set(sim_dist.keys()) | set(train_dist.keys())
        
        for key in all_keys:
            sim_freq = sim_dist.get(key, 0)
            train_freq = train_dist.get(key, 1)  # Avoid division by zero
            
            # Percentage change
            pct_change = (sim_freq - train_freq) / train_freq * 100 if train_freq > 0 else 0
            changes[key] = pct_change
        
        return divergence, changes
    
    @staticmethod
    def compare_latency_distributions(sim_latencies: List[float], 
                                      train_latencies: List[float]) -> float:
        """
        Compare latency distributions using Kolmogorov-Smirnov test.
        
        Returns KS statistic (0-1), where:
        - 0 = similar distributions
        - 1 = very different distributions
        """
        if not sim_latencies or not train_latencies:
            return 0.0
        
        # Sort both
        sim_sorted = sorted(sim_latencies)
        train_sorted = sorted(train_latencies)
        
        # Build CDFs
        sim_cdf = [i / len(sim_sorted) for i in range(len(sim_sorted))]
        train_cdf = [i / len(train_sorted) for i in range(len(train_sorted))]
        
        # KS statistic is max absolute difference
        max_diff = 0.0
        for sim_val, sim_cumulative in zip(sim_sorted, sim_cdf):
            # Find corresponding position in train CDF
            train_cumulative = len([x for x in train_sorted if x <= sim_val]) / len(train_sorted)
            diff = abs(sim_cumulative - train_cumulative)
            max_diff = max(max_diff, diff)
        
        return min(max_diff, 1.0)


class PatternAnalyzer:
    """Analyze patterns and detect drift in simulation vs training data"""
    
    def __init__(self, training_patterns: Dict[str, Any]):
        """
        Initialize with training data patterns.
        
        Args:
            training_patterns: Pattern dict from SimulationPatternExtractor
                              extracted from training data
        """
        self.training_patterns = training_patterns
        logger.info("PatternAnalyzer: Initialized with training patterns")
    
    def analyze_drift(self, simulation_patterns: Dict[str, Any],
                      drift_threshold: float = 0.3) -> DriftReport:
        """
        Analyze drift between simulation patterns and training patterns.
        
        Args:
            simulation_patterns: Pattern dict from simulations
            drift_threshold: Score above which we recommend retraining
        
        Returns:
            DriftReport with detailed analysis
        """
        import time
        
        # Calculate component divergences
        freq_div = self._compare_key_frequencies(simulation_patterns)
        temp_div = self._compare_temporal_patterns(simulation_patterns)
        seq_div = self._compare_sequence_patterns(simulation_patterns)
        
        # Weighted average for overall drift score
        drift_score = 0.4 * freq_div + 0.3 * temp_div + 0.3 * seq_div
        drift_score = min(max(drift_score, 0.0), 1.0)  # Clamp to 0-1
        
        # Detect major changes
        major_changes = self._detect_major_changes(
            simulation_patterns, 
            freq_div, temp_div, seq_div
        )
        
        # Generate recommendations
        recommendations = self._generate_recommendations(
            drift_score, major_changes, drift_threshold
        )
        
        # Detailed metrics
        details = {
            'key_frequency_changes': self._get_frequency_changes(simulation_patterns),
            'latency_changes': self._get_latency_changes(simulation_patterns),
            'cache_hit_changes': self._get_cache_hit_changes(simulation_patterns),
        }
        
        return DriftReport(
            drift_score=drift_score,
            frequency_divergence=freq_div,
            temporal_divergence=temp_div,
            sequence_divergence=seq_div,
            major_changes=major_changes,
            recommendations=recommendations,
            details=details,
            timestamp=time.time(),
            should_retrain=drift_score > drift_threshold,
        )
    
    def _compare_key_frequencies(self, sim_patterns: Dict[str, Any]) -> float:
        """Compare key access frequency distributions"""
        sim_freq = sim_patterns.get('key_frequency_distribution', {})
        train_freq = self.training_patterns.get('key_frequency_distribution', {})
        
        divergence, _ = DistributionAnalyzer.compare_frequency_distributions(
            sim_freq, train_freq
        )
        return divergence
    
    def _compare_temporal_patterns(self, sim_patterns: Dict[str, Any]) -> float:
        """Compare temporal patterns (latency, inter-arrivals)"""
        sim_latency = sim_patterns.get('latency_stats', {})
        train_latency = self.training_patterns.get('latency_stats', {})
        
        if not sim_latency or not train_latency:
            return 0.0
        
        # Compare key latency metrics
        sim_mean = sim_latency.get('mean', 0)
        train_mean = train_latency.get('mean', 1)
        
        if train_mean <= 0:
            return 0.0
        
        # Percentage change in mean latency
        mean_change = abs(sim_mean - train_mean) / train_mean
        
        # Percentage change in variability (stdev)
        sim_stdev = sim_latency.get('stdev', 0)
        train_stdev = train_latency.get('stdev', 1)
        stdev_change = abs(sim_stdev - train_stdev) / max(train_stdev, 1)
        
        # Divergence as average of changes
        divergence = min(0.5 * (mean_change + stdev_change), 1.0)
        
        return divergence
    
    def _compare_sequence_patterns(self, sim_patterns: Dict[str, Any]) -> float:
        """Compare sequence patterns (bigrams, trigrams)"""
        sim_seq = sim_patterns.get('sequence_patterns', {})
        train_seq = self.training_patterns.get('sequence_patterns', {})
        
        sim_bigrams = sim_seq.get('top_bigrams', {})
        train_bigrams = train_seq.get('top_bigrams', {})
        
        if not sim_bigrams and not train_bigrams:
            return 0.0
        
        # Compare set of top bigrams
        sim_keys = set(sim_bigrams.keys())
        train_keys = set(train_bigrams.keys())
        
        if not (sim_keys or train_keys):
            return 0.0
        
        # Jaccard distance
        intersection = len(sim_keys & train_keys)
        union = len(sim_keys | train_keys)
        
        jaccard_similarity = intersection / union if union > 0 else 0
        jaccard_distance = 1.0 - jaccard_similarity
        
        return jaccard_distance
    
    def _detect_major_changes(self, sim_patterns: Dict[str, Any],
                             freq_div: float, temp_div: float, 
                             seq_div: float) -> List[str]:
        """Detect what changed significantly"""
        changes = []
        
        # Frequency changes
        if freq_div > 0.25:
            changes.append(f"Key access frequencies diverged (+{freq_div*100:.1f}%)")
        
        # Temporal changes
        if temp_div > 0.25:
            sim_lat = sim_patterns.get('latency_stats', {}).get('mean', 0)
            train_lat = self.training_patterns.get('latency_stats', {}).get('mean', 1)
            if train_lat > 0:
                pct = abs(sim_lat - train_lat) / train_lat * 100
                changes.append(f"Latency changed by {pct:.1f}%")
        
        # Sequence changes
        if seq_div > 0.25:
            changes.append("Access sequence patterns changed")
        
        # Cache hit rate changes
        sim_cache = sim_patterns.get('cache_hit_stats', {}).get('hit_rate', 0)
        train_cache = self.training_patterns.get('cache_hit_stats', {}).get('hit_rate', 0)
        if abs(sim_cache - train_cache) > 0.1:
            changes.append(f"Cache hit rate shifted ({(sim_cache-train_cache)*100:.1f}%)")
        
        return changes if changes else ["Minor pattern changes detected"]
    
    def _generate_recommendations(self, drift_score: float, 
                                 major_changes: List[str],
                                 threshold: float = 0.3) -> List[str]:
        """Generate recommendations based on drift analysis"""
        recommendations = []
        
        if drift_score > threshold:
            recommendations.append("✓ RETRAIN RECOMMENDED - Significant drift detected")
        
        if drift_score > 0.5:
            recommendations.append("Critical: Major pattern divergence detected")
        
        if drift_score <= threshold and drift_score > 0.2:
            recommendations.append("Monitor: Patterns changing gradually")
        
        if drift_score <= 0.2:
            recommendations.append("✓ No action needed - patterns stable")
        
        return recommendations
    
    def _get_frequency_changes(self, sim_patterns: Dict[str, Any]) -> Dict[str, float]:
        """Get per-key frequency changes"""
        sim_freq = sim_patterns.get('key_frequency_distribution', {})
        train_freq = self.training_patterns.get('key_frequency_distribution', {})
        
        _, changes = DistributionAnalyzer.compare_frequency_distributions(
            sim_freq, train_freq
        )
        
        # Return top 10 changes
        sorted_changes = sorted(
            changes.items(), 
            key=lambda x: abs(x[1]), 
            reverse=True
        )
        return dict(sorted_changes[:10])
    
    def _get_latency_changes(self, sim_patterns: Dict[str, Any]) -> Dict[str, float]:
        """Get latency metric changes"""
        sim_lat = sim_patterns.get('latency_stats', {})
        train_lat = self.training_patterns.get('latency_stats', {})
        
        changes = {}
        metrics = ['mean', 'median', 'p95', 'p99']
        
        for metric in metrics:
            sim_val = sim_lat.get(metric, 0)
            train_val = train_lat.get(metric, 1)
            
            if train_val > 0:
                pct_change = (sim_val - train_val) / train_val * 100
                changes[metric] = pct_change
        
        return changes
    
    def _get_cache_hit_changes(self, sim_patterns: Dict[str, Any]) -> Dict[str, float]:
        """Get cache hit rate changes"""
        sim_hit = sim_patterns.get('cache_hit_stats', {}).get('hit_rate', 0)
        train_hit = self.training_patterns.get('cache_hit_stats', {}).get('hit_rate', 0)
        
        return {
            'simulation_hit_rate': round(sim_hit, 3),
            'training_hit_rate': round(train_hit, 3),
            'change': round(sim_hit - train_hit, 3),
        }
    
    def get_detailed_comparison(self) -> Dict[str, Any]:
        """Get detailed comparison of all patterns"""
        return {
            'training_event_count': self.training_patterns.get('event_count', 0),
            'training_duration': self.training_patterns.get('duration_seconds', 0),
            'training_cache_hit_rate': self.training_patterns.get('cache_hit_stats', {}).get('hit_rate', 0),
            'training_avg_latency': self.training_patterns.get('latency_stats', {}).get('mean', 0),
            'training_key_count': len(self.training_patterns.get('key_frequency_distribution', {})),
            'training_service_count': len(self.training_patterns.get('service_distribution', {})),
        }
