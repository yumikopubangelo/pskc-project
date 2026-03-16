# ============================================================
# PSKC — Data Processor Module
# Processes raw data from data/raw to data/processed
# ============================================================
import json
import os
import logging
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


class DataProcessor:
    """
    Processes raw access data into processed/training-ready format.
    
    RAW DATA (data/raw/):
    - access_events.json: Raw access logs
    - keys.json: Key metadata
    - services.json: Service definitions
    
    PROCESSED DATA (data/processed/):
    - training_data.json: Processed features for ML training
    - key_features.json: Aggregated key features
    - temporal_patterns.json: Time-based patterns
    - metadata.json: Processing metadata
    
    BENEFITS:
    - Separates raw from processed (reproducibility)
    - Feature engineering done once, not per training
    - Can re-run processing with different parameters
    """
    
    def __init__(self, raw_dir: str = None, processed_dir: str = None):
        self._raw_dir = raw_dir or os.path.join(os.path.dirname(__file__), "..", "..", "data", "raw")
        self._processed_dir = processed_dir or os.path.join(os.path.dirname(__file__), "..", "..", "data", "processed")
        
        os.makedirs(self._raw_dir, exist_ok=True)
        os.makedirs(self._processed_dir, exist_ok=True)
        
        logger.info(f"DataProcessor initialized: raw={self._raw_dir}, processed={self._processed_dir}")

    def _load_raw_data(self) -> Dict[str, Any]:
        """Load all raw data files"""
        data = {}
        
        # Load access events
        events_path = os.path.join(self._raw_dir, "access_events.json")
        if os.path.exists(events_path):
            try:
                with open(events_path, 'r', encoding='utf-8') as f:
                    data["access_events"] = json.load(f)
                logger.info(f"Loaded {len(data.get('access_events', []))} access events")
            except Exception as e:
                logger.error(f"Failed to load access_events.json: {e}")
                data["access_events"] = []
        else:
            data["access_events"] = []
            logger.warning("No access_events.json found")
        
        # Load keys metadata
        keys_path = os.path.join(self._raw_dir, "keys.json")
        if os.path.exists(keys_path):
            try:
                with open(keys_path, 'r', encoding='utf-8') as f:
                    data["keys"] = json.load(f)
                logger.info(f"Loaded {len(data.get('keys', {}))} keys")
            except Exception as e:
                logger.error(f"Failed to load keys.json: {e}")
                data["keys"] = {}
        else:
            data["keys"] = {}
            logger.warning("No keys.json found")
        
        # Load services
        services_path = os.path.join(self._raw_dir, "services.json")
        if os.path.exists(services_path):
            try:
                with open(services_path, 'r', encoding='utf-8') as f:
                    data["services"] = json.load(f)
                logger.info(f"Loaded {len(data.get('services', []))} services")
            except Exception as e:
                logger.error(f"Failed to load services.json: {e}")
                data["services"] = []
        else:
            data["services"] = []
            logger.warning("No services.json found")
        
        return data

    def _compute_key_features(self, events: List[Dict]) -> Dict[str, Dict]:
        """Compute aggregated features per key"""
        key_features = defaultdict(lambda: {
            "access_count": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "total_latency_ms": 0.0,
            "services": set(),
            "access_types": defaultdict(int),
            "first_access": None,
            "last_access": None,
            "hourly_counts": defaultdict(int),
            "daily_counts": defaultdict(int),
        })
        
        for event in events:
            key_id = event.get("key_id", "unknown")
            feat = key_features[key_id]
            
            feat["access_count"] += 1
            feat["services"].add(event.get("service_id", "unknown"))
            feat["access_types"][event.get("access_type", "read")] += 1
            
            if event.get("cache_hit", False):
                feat["cache_hits"] += 1
            else:
                feat["cache_misses"] += 1
            
            feat["total_latency_ms"] += event.get("latency_ms", 0)
            
            # Track timestamps
            timestamp = event.get("timestamp", 0)
            if feat["first_access"] is None or timestamp < feat["first_access"]:
                feat["first_access"] = timestamp
            if feat["last_access"] is None or timestamp > feat["last_access"]:
                feat["last_access"] = timestamp
            
            # Time-based features
            dt = datetime.fromtimestamp(timestamp)
            feat["hourly_counts"][dt.hour] += 1
            feat["daily_counts"][dt.weekday()] += 1
        
        # Convert sets to lists and compute derived features
        result = {}
        for key_id, feat in key_features.items():
            result[key_id] = {
                "access_count": feat["access_count"],
                "cache_hits": feat["cache_hits"],
                "cache_misses": feat["cache_misses"],
                "cache_hit_rate": feat["cache_hits"] / feat["access_count"] if feat["access_count"] > 0 else 0,
                "avg_latency_ms": feat["total_latency_ms"] / feat["access_count"] if feat["access_count"] > 0 else 0,
                "unique_services": list(feat["services"]),
                "service_count": len(feat["services"]),
                "access_types": dict(feat["access_types"]),
                "first_access": feat["first_access"],
                "last_access": feat["last_access"],
                "hourly_counts": dict(feat["hourly_counts"]),
                "daily_counts": dict(feat["daily_counts"]),
                # Derived features
                "is_hot": feat["access_count"] >= 100,
                "is_persistent": feat["cache_hit_rate"] >= 0.7,
                "access_span_hours": (feat["last_access"] - feat["first_access"]) / 3600 if feat["first_access"] and feat["last_access"] else 0,
            }
        
        return result

    def _compute_temporal_patterns(self, events: List[Dict]) -> Dict[str, Any]:
        """Compute temporal access patterns"""
        hourly = defaultdict(int)
        daily = defaultdict(int)
        monthly = defaultdict(int)
        
        for event in events:
            timestamp = event.get("timestamp", 0)
            dt = datetime.fromtimestamp(timestamp)
            hourly[dt.hour] += 1
            daily[dt.weekday()] += 1
            monthly[dt.month] += 1
        
        # Find peak hours
        peak_hour = max(hourly.items(), key=lambda x: x[1])[0] if hourly else 0
        peak_day = max(daily.items(), key=lambda x: x[1])[0] if daily else 0
        
        return {
            "hourly_distribution": dict(hourly),
            "daily_distribution": dict(daily),
            "monthly_distribution": dict(monthly),
            "peak_hour": peak_hour,
            "peak_day": peak_day,
            "total_events": len(events),
        }

    def _create_training_data(
        self, 
        events: List[Dict], 
        key_features: Dict[str, Dict],
        context_window: int = 10
    ) -> List[Dict]:
        """
        Create training-ready data with context windows.
        
        Each sample includes:
        - key_id: target key to predict
        - features: extracted features from context window
        - label: next key (for sequence prediction)
        """
        training_samples = []
        
        # Sort events by timestamp
        sorted_events = sorted(events, key=lambda x: x.get("timestamp", 0))
        
        for i in range(context_window, len(sorted_events)):
            # Get context window
            context = sorted_events[i - context_window:i]
            target = sorted_events[i]
            
            # Extract features from context
            features = {
                # Context size
                "context_size": len(context),
                
                # Key diversity in context
                "unique_keys": len(set(e.get("key_id") for e in context)),
                
                # Service diversity
                "unique_services": len(set(e.get("service_id") for e in context)),
                
                # Cache performance in context
                "cache_hits_in_context": sum(1 for e in context if e.get("cache_hit", False)),
                "cache_hit_rate_context": sum(1 for e in context if e.get("cache_hit", False)) / len(context),
                
                # Latency features
                "avg_latency": sum(e.get("latency_ms", 0) for e in context) / len(context),
                "max_latency": max(e.get("latency_ms", 0) for e in context),
                
                # Time features from last event in context
                "last_hour": context[-1].get("hour", 0) if "hour" in context[-1] else datetime.fromtimestamp(context[-1].get("timestamp", 0)).hour,
                "last_dow": context[-1].get("day_of_week", 0) if "day_of_week" in context[-1] else datetime.fromtimestamp(context[-1].get("timestamp", 0)).weekday(),
                
                # Target key features
                "target_key_hot": key_features.get(target.get("key_id", ""), {}).get("is_hot", False),
                "target_key_persistent": key_features.get(target.get("key_id", ""), {}).get("is_persistent", False),
                "target_key_service_count": key_features.get(target.get("key_id", ""), {}).get("service_count", 0),
            }
            
            training_samples.append({
                "key_id": target.get("key_id"),
                "features": features,
                "timestamp": target.get("timestamp"),
                "context_keys": [e.get("key_id") for e in context],
            })
        
        return training_samples

    def process(self, context_window: int = 10, min_events: int = 10) -> Dict[str, Any]:
        """
        Process raw data into training-ready format.
        
        Args:
            context_window: Number of events to use as context
            min_events: Minimum events required for processing
            
        Returns:
            Processing result dict
        """
        logger.info("Starting data processing...")
        
        # Load raw data
        raw_data = self._load_raw_data()
        events = raw_data.get("access_events", [])
        
        if len(events) < min_events:
            logger.warning(f"Not enough events: {len(events)} < {min_events}")
            return {
                "success": False,
                "reason": "insufficient_events",
                "event_count": len(events),
                "required": min_events,
            }
        
        processed_at = datetime.now(timezone.utc).isoformat()
        
        # Compute features
        logger.info("Computing key features...")
        key_features = self._compute_key_features(events)
        
        logger.info("Computing temporal patterns...")
        temporal_patterns = self._compute_temporal_patterns(events)
        
        logger.info("Creating training data...")
        training_data = self._create_training_data(events, key_features, context_window)
        
        # Compute checksum for data integrity
        data_hash = hashlib.sha256(
            json.dumps(events, sort_keys=True).encode()
        ).hexdigest()[:16]
        
        # Prepare processed data
        processed_data = {
            "metadata": {
                "processed_at": processed_at,
                "source_files": {
                    "access_events": len(raw_data.get("access_events", [])),
                    "keys": len(raw_data.get("keys", {})),
                    "services": len(raw_data.get("services", [])),
                },
                "context_window": context_window,
                "data_hash": data_hash,
            },
            "training_data": training_data,
            "key_features": key_features,
            "temporal_patterns": temporal_patterns,
        }
        
        # Save processed data
        try:
            # Save main training data
            training_path = os.path.join(self._processed_dir, "training_data.json")
            with open(training_path, 'w', encoding='utf-8') as f:
                # Save metadata separately to avoid large file issues
                json.dump({
                    "metadata": processed_data["metadata"],
                    "training_data": training_data[:1000],  # Save first 1000 as sample
                }, f, indent=2)
            
            # Save key features
            features_path = os.path.join(self._processed_dir, "key_features.json")
            with open(features_path, 'w', encoding='utf-8') as f:
                json.dump(key_features, f, indent=2)
            
            # Save temporal patterns
            patterns_path = os.path.join(self._processed_dir, "temporal_patterns.json")
            with open(patterns_path, 'w', encoding='utf-8') as f:
                json.dump(temporal_patterns, f, indent=2)
            
            # Save metadata
            metadata_path = os.path.join(self._processed_dir, "metadata.json")
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(processed_data["metadata"], f, indent=2)
            
            logger.info(
                f"Data processing complete: "
                f"training_samples={len(training_data)}, "
                f"keys={len(key_features)}"
            )
            
            return {
                "success": True,
                "processed_at": processed_at,
                "training_samples": len(training_data),
                "unique_keys": len(key_features),
                "data_hash": data_hash,
                "files": {
                    "training_data": training_path,
                    "key_features": features_path,
                    "temporal_patterns": patterns_path,
                    "metadata": metadata_path,
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to save processed data: {e}")
            return {
                "success": False,
                "reason": f"save_failed: {str(e)}",
            }

    def get_processed_info(self) -> Dict[str, Any]:
        """Get info about processed data"""
        metadata_path = os.path.join(self._processed_dir, "metadata.json")
        
        if not os.path.exists(metadata_path):
            return {
                "exists": False,
                "processed_dir": self._processed_dir,
            }
        
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            
            return {
                "exists": True,
                "processed_at": metadata.get("processed_at"),
                "source_events": metadata.get("source_files", {}).get("access_events", 0),
                "data_hash": metadata.get("data_hash"),
                "context_window": metadata.get("context_window"),
            }
        except Exception as e:
            return {
                "exists": True,
                "error": str(e),
            }

    def load_training_data(self, limit: int = None) -> List[Dict]:
        """Load processed training data"""
        training_path = os.path.join(self._processed_dir, "training_data.json")
        
        if not os.path.exists(training_path):
            return []
        
        try:
            with open(training_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            training_data = data.get("training_data", [])
            if limit:
                training_data = training_data[:limit]
            return training_data
        except Exception as e:
            logger.error(f"Failed to load training data: {e}")
            return []


# Global instance
_processor_instance: Optional[DataProcessor] = None


def get_data_processor() -> DataProcessor:
    """Get global data processor instance"""
    global _processor_instance
    if _processor_instance is None:
        _processor_instance = DataProcessor()
    return _processor_instance
