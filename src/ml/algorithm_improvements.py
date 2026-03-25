# ============================================================
# PSKC — Advanced Algorithm Improvements
# ============================================================
"""
Improvements to ML algorithms:
- EWMA (Exponential Weighted Moving Average) with short/long terms
- Advanced Drift Detection
- Dynamic Markov Chains
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict, deque
from datetime import datetime
import numpy as np

logger = logging.getLogger(__name__)


class EWMACalculator:
    """
    Exponential Weighted Moving Average calculator.
    Supports both short-term and long-term EWMAs for trend analysis.
    """
    
    def __init__(
        self,
        alpha_short: float = 0.3,
        alpha_long: float = 0.1,
        window_size: int = 50
    ):
        """
        Initialize EWMA calculator.
        
        Args:
            alpha_short: Smoothing factor for short-term EWMA (higher = more responsive)
            alpha_long: Smoothing factor for long-term EWMA (lower = more stable)
            window_size: Size of historical window to keep
        """
        self.alpha_short = alpha_short
        self.alpha_long = alpha_long
        self.window_size = window_size
        
        # Per-key tracking
        self.ewma_short = {}  # {key: last_ewma_value}
        self.ewma_long = {}   # {key: last_ewma_value}
        self.history = defaultdict(lambda: deque(maxlen=window_size))
        self.initialized = {}  # {key: bool}
    
    def update(self, key: str, value: float) -> Tuple[float, float]:
        """
        Update EWMA for a key and return both short and long EWMAs.
        
        Args:
            key: Metric key (e.g., prediction_accuracy)
            value: New value to incorporate
            
        Returns:
            Tuple of (ewma_short, ewma_long)
        """
        self.history[key].append(value)
        
        if not self.initialized.get(key, False):
            # First value: initialize both EWMAs
            self.ewma_short[key] = value
            self.ewma_long[key] = value
            self.initialized[key] = True
        else:
            # Update EWMAs using standard formula: S_t = alpha * X_t + (1-alpha) * S_(t-1)
            self.ewma_short[key] = (
                self.alpha_short * value + (1 - self.alpha_short) * self.ewma_short[key]
            )
            self.ewma_long[key] = (
                self.alpha_long * value + (1 - self.alpha_long) * self.ewma_long[key]
            )
        
        return self.ewma_short[key], self.ewma_long[key]
    
    def get(self, key: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Get current EWMA values for a key.
        
        Returns:
            Tuple of (ewma_short, ewma_long) or (None, None) if key not found
        """
        return (
            self.ewma_short.get(key),
            self.ewma_long.get(key)
        )
    
    def get_trend(self, key: str) -> str:
        """
        Determine trend direction by comparing short and long EWMAs.
        
        Args:
            key: Metric key
            
        Returns:
            "increasing", "decreasing", or "stable"
        """
        short = self.ewma_short.get(key)
        long = self.ewma_long.get(key)
        
        if short is None or long is None:
            return "unknown"
        
        diff = short - long
        threshold = 0.001  # Small threshold to avoid noise
        
        if diff > threshold:
            return "increasing"
        elif diff < -threshold:
            return "decreasing"
        else:
            return "stable"
    
    def reset(self, key: Optional[str] = None):
        """
        Reset EWMA values.
        
        Args:
            key: Specific key to reset (all if None)
        """
        if key:
            self.ewma_short.pop(key, None)
            self.ewma_long.pop(key, None)
            self.initialized.pop(key, None)
            self.history.pop(key, None)
        else:
            self.ewma_short.clear()
            self.ewma_long.clear()
            self.initialized.clear()
            self.history.clear()


class DriftDetector:
    """
    Advanced concept drift detection using multiple methods.
    Detects when data distribution changes significantly.
    """
    
    def __init__(
        self,
        short_window: int = 30,
        long_window: int = 200,
        drift_threshold: float = 0.3,
        warning_threshold: float = 0.15
    ):
        """
        Initialize drift detector.
        
        Args:
            short_window: Number of samples in short-term window
            long_window: Number of samples in long-term window
            drift_threshold: Threshold for declaring drift
            warning_threshold: Threshold for warning (before critical drift)
        """
        self.short_window = short_window
        self.long_window = long_window
        self.drift_threshold = drift_threshold
        self.warning_threshold = warning_threshold
        
        # Per-key tracking
        self.short_windows = defaultdict(lambda: deque(maxlen=short_window))
        self.long_windows = defaultdict(lambda: deque(maxlen=long_window))
        self.drift_scores = {}  # {key: score}
        self.drift_history = defaultdict(list)
    
    def update(self, key: str, value: float) -> Dict[str, Any]:
        """
        Update drift detector with new value.
        
        Args:
            key: Metric key
            value: New value (e.g., prediction correctness: 0 or 1)
            
        Returns:
            Dictionary with drift analysis results
        """
        self.short_windows[key].append(value)
        self.long_windows[key].append(value)
        
        # Calculate drift
        drift_score = self._calculate_drift(key)
        self.drift_scores[key] = drift_score
        
        # Determine drift level
        if drift_score >= self.drift_threshold:
            drift_level = "critical"
        elif drift_score >= self.warning_threshold:
            drift_level = "warning"
        else:
            drift_level = "normal"
        
        result = {
            "key": key,
            "drift_score": drift_score,
            "drift_level": drift_level,
            "timestamp": datetime.utcnow().isoformat(),
            "short_window_mean": np.mean(list(self.short_windows[key])) if self.short_windows[key] else None,
            "long_window_mean": np.mean(list(self.long_windows[key])) if self.long_windows[key] else None,
        }
        
        # Store in history
        self.drift_history[key].append(result)
        
        return result
    
    def _calculate_drift(self, key: str) -> float:
        """
        Calculate drift score using multiple indicators.
        
        Args:
            key: Metric key
            
        Returns:
            Drift score between 0 and 1
        """
        short = list(self.short_windows[key])
        long = list(self.long_windows[key])
        
        if not short or not long:
            return 0.0
        
        short_mean = np.mean(short)
        long_mean = np.mean(long)
        
        # Method 1: Mean difference (normalized)
        try:
            mean_diff = abs(short_mean - long_mean) / (abs(long_mean) + 1e-6)
        except:
            mean_diff = 0
        
        # Method 2: Variance comparison
        short_var = np.var(short) if len(short) > 1 else 0
        long_var = np.var(long) if len(long) > 1 else 0
        
        try:
            var_diff = abs(short_var - long_var) / (abs(long_var) + 1e-6)
        except:
            var_diff = 0
        
        # Method 3: EDDM-like (Early Drift Detection Method)
        # Track error rate changes
        try:
            short_error_rate = 1 - short_mean  # Assuming value is accuracy (0-1)
            long_error_rate = 1 - long_mean
            error_diff = abs(short_error_rate - long_error_rate)
        except:
            error_diff = 0
        
        # Weighted combination
        drift_score = (
            0.4 * min(mean_diff, 1.0) +
            0.3 * min(var_diff, 1.0) +
            0.3 * min(error_diff, 1.0)
        )
        
        return min(drift_score, 1.0)
    
    def get_drift_score(self, key: str) -> float:
        """Get current drift score for a key."""
        return self.drift_scores.get(key, 0.0)
    
    def get_drift_history(self, key: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get drift history for a key."""
        history = self.drift_history.get(key, [])
        return history[-limit:]
    
    def should_retrain(self, key: str) -> bool:
        """Determine if retraining should be triggered."""
        return self.get_drift_score(key) >= self.drift_threshold
    
    def reset(self, key: Optional[str] = None):
        """Reset drift detector."""
        if key:
            self.short_windows.pop(key, None)
            self.long_windows.pop(key, None)
            self.drift_scores.pop(key, None)
            self.drift_history.pop(key, None)
        else:
            self.short_windows.clear()
            self.long_windows.clear()
            self.drift_scores.clear()
            self.drift_history.clear()


class DynamicMarkovChain:
    """
    Dynamic Markov Chain that adapts transition probabilities
    based on recent observations.
    """
    
    def __init__(
        self,
        states: List[str],
        window_size: int = 100,
        decay_factor: float = 0.9
    ):
        """
        Initialize Dynamic Markov Chain.
        
        Args:
            states: List of possible states
            window_size: Size of sliding window for recent observations
            decay_factor: Factor to decay old observations (0-1)
        """
        self.states = set(states)
        self.window_size = window_size
        self.decay_factor = decay_factor
        
        # Per-key tracking
        self.transitions = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
        self.observation_windows = defaultdict(lambda: deque(maxlen=window_size))
        self.state_counts = defaultdict(lambda: defaultdict(float))
    
    def observe(self, key: str, from_state: str, to_state: str):
        """
        Record a state transition.
        
        Args:
            key: Identifier for the chain
            from_state: Current state
            to_state: Next state
        """
        if from_state not in self.states or to_state not in self.states:
            logger.warning(f"Invalid states: {from_state} -> {to_state}")
            return
        
        # Record observation
        self.observation_windows[key].append((from_state, to_state))
        
        # Update recent transition counts
        self.transitions[key][from_state][to_state] += 1
        self.state_counts[key][from_state] += 1
        
        # Decay old transition counts (forgetting mechanism)
        self._apply_decay(key)
    
    def _apply_decay(self, key: str):
        """Apply exponential decay to old observations."""
        for from_state in self.transitions[key]:
            for to_state in self.transitions[key][from_state]:
                self.transitions[key][from_state][to_state] *= self.decay_factor
            self.state_counts[key][from_state] *= self.decay_factor
    
    def get_transition_probability(
        self,
        key: str,
        from_state: str
    ) -> Dict[str, float]:
        """
        Get transition probabilities from a state.
        
        Args:
            key: Identifier for the chain
            from_state: Current state
            
        Returns:
            Dictionary of to_state: probability
        """
        if from_state not in self.transitions[key]:
            return {}
        
        total = self.state_counts[key].get(from_state, 0)
        if total == 0:
            return {}
        
        probabilities = {}
        for to_state, count in self.transitions[key][from_state].items():
            probabilities[to_state] = count / total
        
        return probabilities
    
    def predict_next_state(self, key: str, current_state: str) -> Optional[str]:
        """
        Predict the most likely next state.
        
        Args:
            key: Identifier for the chain
            current_state: Current state
            
        Returns:
            Most probable next state or None
        """
        probs = self.get_transition_probability(key, current_state)
        if not probs:
            return None
        
        return max(probs.items(), key=lambda x: x[1])[0]
    
    def get_chain_state(self, key: str) -> Dict[str, Any]:
        """
        Get current state of the Markov chain.
        
        Args:
            key: Identifier for the chain
            
        Returns:
            Dictionary with chain statistics
        """
        return {
            "states": list(self.states),
            "transitions": {
                from_state: dict(to_states)
                for from_state, to_states in self.transitions[key].items()
            },
            "state_counts": dict(self.state_counts[key]),
            "recent_observations": list(self.observation_windows[key])[-10:],
        }
    
    def reset(self, key: Optional[str] = None):
        """Reset Markov chain."""
        if key:
            self.transitions.pop(key, None)
            self.observation_windows.pop(key, None)
            self.state_counts.pop(key, None)
        else:
            self.transitions.clear()
            self.observation_windows.clear()
            self.state_counts.clear()
