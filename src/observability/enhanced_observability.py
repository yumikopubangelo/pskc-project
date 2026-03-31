# ============================================================
# PSKC — Enhanced Observability Service
# ============================================================
"""
Enhanced observability service with database persistence.
Tracks prediction accuracy per key, drift detection, latency metrics, and benchmarking.
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc
import json
from collections import defaultdict, deque

from src.database.models import (
    KeyPrediction,
    ModelMetric,
    ModelVersion,
    PerKeyMetric,
    PredictionLog,
)
from src.ml.algorithm_improvements import EWMACalculator, DriftDetector

logger = logging.getLogger(__name__)


_observability_instance: Optional["EnhancedObservabilityService"] = None


def get_observability_service() -> Optional["EnhancedObservabilityService"]:
    """Return the global observability service instance, or None if not initialized."""
    return _observability_instance


def set_observability_service(service: "EnhancedObservabilityService") -> None:
    """Set the global observability service instance."""
    global _observability_instance
    _observability_instance = service


class EnhancedObservabilityService:
    """
    Enhanced observability service that tracks:
    - Prediction accuracy per key
    - Model drift detection per key
    - Latency metrics (with breakdown)
    - Cache efficiency
    - Benchmark metrics (speedup factor, hit rate)
    """
    
    def __init__(self, db_session: Session):
        """
        Initialize observability service.
        
        Args:
            db_session: SQLAlchemy database session
        """
        self.db = db_session
        
        # In-memory metrics for real-time tracking
        self.accuracy_ewma = EWMACalculator(alpha_short=0.3, alpha_long=0.1)
        self.drift_detector = DriftDetector(
            short_window=30,
            long_window=200,
            drift_threshold=0.3
        )
        
        # Latency tracking (in milliseconds)
        self.latency_buckets = defaultdict(
            lambda: deque(maxlen=500)
        )  # {key: deque of latencies}
        
        # Cache metrics
        self.cache_stats = defaultdict(lambda: {"hits": 0, "misses": 0})
        
        # Baseline for benchmark (stored in config)
        self.baseline_latency_ms = None

    def resolve_version_id(
        self,
        version_id: Optional[int] = None,
        *,
        model_name: Optional[str] = None,
        runtime_version: Optional[str] = None,
    ) -> int:
        """
        Resolve a runtime version to a concrete ModelVersion row.

        Runtime prediction logging often only knows the active runtime label
        (for example ``v12`` or a registry timestamp). This helper maps that
        label back to the database row used by the intelligence dashboard.
        """
        try:
            if version_id and int(version_id) > 0:
                return int(version_id)
        except (TypeError, ValueError):
            pass

        query = self.db.query(ModelVersion)
        if model_name:
            query = query.filter(ModelVersion.model_name == model_name)

        versions = query.order_by(desc(ModelVersion.created_at)).limit(100).all()
        if not versions:
            return 0

        runtime_candidates = set()
        if runtime_version:
            runtime_label = str(runtime_version).strip()
            runtime_candidates.add(runtime_label)
            if runtime_label.lower().startswith("v") and runtime_label[1:].isdigit():
                runtime_candidates.add(runtime_label[1:])

        if runtime_candidates:
            for version in versions:
                metrics_json = version.metrics_json or {}
                db_candidates = {
                    str(version.version_number),
                    str(metrics_json.get("runtime_version") or ""),
                }
                if db_candidates & runtime_candidates:
                    return int(version.version_id)

        preferred_statuses = (
            "production",
            "staging",
            "development",
            "active",
            "trained",
            "accepted",
            "archived",
        )
        for desired_status in preferred_statuses:
            for version in versions:
                if str(version.status or "").lower() == desired_status:
                    return int(version.version_id)

        non_rejected = next(
            (version for version in versions if str(version.status or "").lower() != "rejected"),
            None,
        )
        if non_rejected is not None:
            return int(non_rejected.version_id)

        return int(versions[0].version_id)
    
    def record_prediction(
        self,
        version_id: int,
        key: str,
        predicted_value: str,
        actual_value: Optional[str] = None,
        confidence: Optional[float] = None,
        latency_ms: Optional[float] = None,
        record_log: bool = True,
        update_metrics: bool = True
    ) -> bool:
        """
        Record a prediction with all metrics, supporting batch operations.
        
        Args:
            version_id: Model version ID
            key: Cache key
            predicted_value: Predicted value
            actual_value: Actual value (if known)
            confidence: Model confidence (0-1)
            latency_ms: Prediction latency in milliseconds
            record_log: Whether to also record prediction log (default True)
            update_metrics: Whether to also update per-key metrics (default True)
            
        Returns:
            True if successful
        """
        try:
            is_correct = (predicted_value == actual_value) if actual_value else None
            
            # Store in database using savepoint for rollback isolation
            try:
                prediction = KeyPrediction(
                    version_id=version_id,
                    key=key,
                    predicted_value=predicted_value,
                    actual_value=actual_value,
                    is_correct=is_correct,
                    confidence=confidence,
                    timestamp=datetime.utcnow()
                )
                self.db.add(prediction)
                
                # Batch: add prediction log in same transaction if requested
                if record_log:
                    log_entry = PredictionLog(
                        version_id=version_id,
                        key=key,
                        predicted_value=predicted_value,
                        actual_value=actual_value,
                        confidence=confidence,
                        is_correct=is_correct,
                        latency_ms=latency_ms,
                        timestamp=datetime.utcnow(),
                    )
                    self.db.add(log_entry)
                
                # Commit once instead of twice - reduces lock contention
                self.db.commit()
                
            except Exception as e:
                self.db.rollback()
                logger.error(f"Failed to record prediction: {e}")
                return False
            
            # Update EWMA if correctness known
            if is_correct is not None:
                self.accuracy_ewma.update(key, 1.0 if is_correct else 0.0)
            
            # Track latency
            if latency_ms:
                self.latency_buckets[key].append(latency_ms)
            
            # Update metrics separately (if requested) to avoid lock blocking prediction records
            if update_metrics:
                self.update_per_key_metrics(version_id, key)
            
            return True
        except Exception as e:
            logger.error(f"Failed to record prediction: {e}")
            return False

    def record_prediction_log(
        self,
        *,
        version_id: int,
        key: str,
        predicted_value: str,
        actual_value: Optional[str] = None,
        confidence: Optional[float] = None,
        latency_ms: Optional[float] = None,
    ) -> bool:
        """Persist a detailed runtime prediction log for debugging and audit.
        
        Note: This is now integrated into record_prediction() for batch operations.
        This method is kept for backward compatibility.
        """
        # This is handled by record_prediction() now, but keep for compatibility
        if not version_id:
            return False
        
        try:
            log_entry = PredictionLog(
                version_id=version_id,
                key=key,
                predicted_value=predicted_value,
                actual_value=actual_value,
                confidence=confidence,
                is_correct=(predicted_value == actual_value) if actual_value is not None else None,
                latency_ms=latency_ms,
                timestamp=datetime.utcnow(),
            )
            self.db.add(log_entry)
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            logger.debug(f"Failed to record prediction log: {e}")
            return False
    
    def update_per_key_metrics(
        self,
        version_id: int,
        key: str
    ) -> bool:
        """
        Calculate and update per-key metrics from recent predictions.
        Optimized to reduce database lock contention with atomic transactions.
        
        Args:
            version_id: Model version ID
            key: Cache key
            
        Returns:
            True if successful
        """
        try:
            # Get recent predictions for this key
            recent_predictions = self.db.query(KeyPrediction).filter(
                and_(
                    KeyPrediction.version_id == version_id,
                    KeyPrediction.key == key,
                    KeyPrediction.timestamp >= (
                        datetime.utcnow() - timedelta(hours=1)
                    )
                )
            ).all()
            
            if not recent_predictions:
                return True
            
            # Calculate metrics
            correct = sum(1 for p in recent_predictions if p.is_correct)
            accuracy = correct / len(recent_predictions) if recent_predictions else 0
            error_count = sum(1 for p in recent_predictions if p.is_correct is False)
            avg_confidence = sum(
                float(p.confidence or 0.0) for p in recent_predictions
            ) / len(recent_predictions)
            
            # Get drift score
            drift_score = self.drift_detector.get_drift_score(key)
            
            # Get cache hit rate
            cache_stats = self.cache_stats.get(key, {})
            total = cache_stats.get("hits", 0) + cache_stats.get("misses", 0)
            cache_hit_rate = (
                cache_stats.get("hits", 0) / total if total > 0 else 0
            )
            
            # Update in database as single atomic transaction to reduce lock contention
            try:
                existing = self.db.query(PerKeyMetric).filter(
                    and_(
                        PerKeyMetric.version_id == version_id,
                        PerKeyMetric.key == key
                    )
                ).first()
                
                if existing:
                    existing.accuracy = accuracy
                    existing.drift_score = drift_score
                    existing.cache_hit_rate = cache_hit_rate
                    existing.hit_rate = cache_hit_rate
                    existing.total_predictions = len(recent_predictions)
                    existing.error_count = error_count
                    existing.avg_confidence = avg_confidence
                    existing.timestamp = datetime.utcnow()
                else:
                    metric = PerKeyMetric(
                        version_id=version_id,
                        key=key,
                        accuracy=accuracy,
                        drift_score=drift_score,
                        cache_hit_rate=cache_hit_rate,
                        hit_rate=cache_hit_rate,
                        total_predictions=len(recent_predictions),
                        error_count=error_count,
                        avg_confidence=avg_confidence,
                        timestamp=datetime.utcnow(),
                    )
                    self.db.add(metric)
                
                self.db.commit()
                return True
            except Exception as e:
                self.db.rollback()
                logger.debug(f"Failed to update per-key metrics for {key}: {e}")
                return False
        except Exception as e:
            logger.debug(f"Failed to query metrics for {key}: {e}")
            return False
    
    def record_cache_operation(
        self,
        key: str,
        is_hit: bool
    ):
        """
        Record a cache hit or miss.
        
        Args:
            key: Cache key
            is_hit: True if cache hit, False if miss
        """
        if is_hit:
            self.cache_stats[key]["hits"] += 1
        else:
            self.cache_stats[key]["misses"] += 1
    
    def record_drift(
        self,
        key: str,
        is_correct: bool
    ) -> Dict[str, Any]:
        """
        Record prediction correctness and update drift detection.
        
        Args:
            key: Cache key
            is_correct: Whether prediction was correct
            
        Returns:
            Drift analysis result
        """
        value = 1.0 if is_correct else 0.0
        return self.drift_detector.update(key, value)
    
    def get_per_key_metrics(
        self,
        version_id: int,
        key: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get per-key metrics from database.
        
        Args:
            version_id: Model version ID
            key: Specific key (optional)
            
        Returns:
            List of per-key metrics
        """
        try:
            query = self.db.query(PerKeyMetric).filter(
                PerKeyMetric.version_id == version_id
            )
            
            if key:
                query = query.filter(PerKeyMetric.key == key)
            
            metrics = query.order_by(desc(PerKeyMetric.timestamp)).all()
            
            return [
                {
                    "key": m.key,
                    "accuracy": m.accuracy,
                    "drift_score": m.drift_score,
                    "cache_hit_rate": m.cache_hit_rate,
                    "updated_at": m.timestamp.isoformat() if m.timestamp else None,
                }
                for m in metrics
            ]
        except Exception as e:
            logger.error(f"Failed to get per-key metrics: {e}")
            return []

    def get_recent_prediction_logs(
        self,
        *,
        limit: int = 50,
        version_id: Optional[int] = None,
        key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return recent detailed prediction logs for debugging."""
        try:
            query = self.db.query(PredictionLog)
            if version_id:
                query = query.filter(PredictionLog.version_id == version_id)
            if key:
                query = query.filter(PredictionLog.key == key)

            logs = query.order_by(desc(PredictionLog.timestamp)).limit(limit).all()
            return [
                {
                    "id": log.id,
                    "version_id": log.version_id,
                    "key": log.key,
                    "predicted_value": log.predicted_value,
                    "actual_value": log.actual_value,
                    "confidence": log.confidence,
                    "is_correct": log.is_correct,
                    "latency_ms": log.latency_ms,
                    "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                }
                for log in logs
            ]
        except Exception as e:
            logger.error(f"Failed to get recent prediction logs: {e}")
            return []
    
    def get_latency_metrics(
        self,
        key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get latency statistics.
        
        Args:
            key: Specific key (optional, all if None)
            
        Returns:
            Latency statistics dictionary
        """
        import statistics
        
        if key:
            latencies = list(self.latency_buckets.get(key, []))
            if not latencies:
                return {"key": key, "no_data": True}
            
            return {
                "key": key,
                "count": len(latencies),
                "min_ms": min(latencies),
                "max_ms": max(latencies),
                "avg_ms": statistics.mean(latencies),
                "median_ms": statistics.median(latencies),
                "stdev_ms": statistics.stdev(latencies) if len(latencies) > 1 else 0,
                "p95_ms": statistics.quantiles(
                    latencies, n=20
                )[18] if len(latencies) > 20 else max(latencies),
                "p99_ms": statistics.quantiles(
                    latencies, n=100
                )[98] if len(latencies) > 100 else max(latencies),
            }
        else:
            # Aggregate across all keys
            all_latencies = []
            for latencies in self.latency_buckets.values():
                all_latencies.extend(latencies)
            
            if not all_latencies:
                return {"total_keys": len(self.latency_buckets), "no_data": True}
            
            return {
                "total_keys": len(self.latency_buckets),
                "total_samples": len(all_latencies),
                "min_ms": min(all_latencies),
                "max_ms": max(all_latencies),
                "avg_ms": statistics.mean(all_latencies),
                "median_ms": statistics.median(all_latencies),
                "stdev_ms": statistics.stdev(
                    all_latencies
                ) if len(all_latencies) > 1 else 0,
            }
    
    def get_benchmark_metrics(
        self,
        version_id: int,
        baseline_latency_ms: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Calculate benchmark metrics comparing with baseline.
        
        Args:
            version_id: Model version ID
            baseline_latency_ms: Baseline latency for comparison
            
        Returns:
            Benchmark metrics
        """
        try:
            # Get all predictions for this version
            predictions = self.db.query(KeyPrediction).filter(
                KeyPrediction.version_id == version_id
            ).all()
            
            if not predictions:
                return {"version_id": version_id, "no_data": True}
            
            # Calculate hit rate (prediction accuracy)
            correct = sum(1 for p in predictions if p.is_correct)
            total = len(predictions)
            hit_rate = correct / total if total > 0 else 0
            
            # Get latency metrics
            latency_metrics = self.get_latency_metrics()
            avg_latency = latency_metrics.get("avg_ms", 0)
            
            # Calculate speedup factor
            speedup_factor = 1.0
            if baseline_latency_ms and avg_latency > 0:
                speedup_factor = baseline_latency_ms / avg_latency
            
            # Cache efficiency
            total_cache_ops = sum(
                stats["hits"] + stats["misses"]
                for stats in self.cache_stats.values()
            )
            total_cache_hits = sum(
                stats["hits"] for stats in self.cache_stats.values()
            )
            cache_hit_rate = (
                total_cache_hits / total_cache_ops if total_cache_ops > 0 else 0
            )
            
            return {
                "version_id": version_id,
                "hit_rate": hit_rate,
                "prediction_accuracy": hit_rate,
                "avg_latency_ms": avg_latency,
                "latency_reduction_percent": (
                    ((baseline_latency_ms - avg_latency) / baseline_latency_ms * 100)
                    if baseline_latency_ms else 0
                ),
                "speedup_factor": speedup_factor,
                "cache_hit_rate": cache_hit_rate,
                "total_predictions": total,
                "correct_predictions": correct,
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            logger.error(f"Failed to calculate benchmark metrics: {e}")
            return {"version_id": version_id, "error": str(e)}
    
    def get_accuracy_trend(
        self,
        key: Optional[str] = None,
        days: int = 7
    ) -> List[Dict[str, Any]]:
        """
        Get accuracy trend over time.
        
        Args:
            key: Specific key (optional)
            days: Number of days to look back
            
        Returns:
            List of accuracy measurements over time
        """
        try:
            start_time = datetime.utcnow() - timedelta(days=days)
            
            query = self.db.query(KeyPrediction).filter(
                KeyPrediction.timestamp >= start_time
            )
            
            if key:
                query = query.filter(KeyPrediction.key == key)
            
            predictions = query.order_by(KeyPrediction.timestamp).all()
            
            # Group by hour and calculate accuracy
            hourly_accuracy = defaultdict(lambda: {"correct": 0, "total": 0})
            for p in predictions:
                hour_key = p.timestamp.strftime("%Y-%m-%d %H:00")
                hourly_accuracy[hour_key]["total"] += 1
                if p.is_correct:
                    hourly_accuracy[hour_key]["correct"] += 1
            
            return [
                {
                    "timestamp": timestamp,
                    "accuracy": (
                        stats["correct"] / stats["total"]
                        if stats["total"] > 0 else 0
                    ),
                    "samples": stats["total"]
                }
                for timestamp, stats in sorted(hourly_accuracy.items())
            ]
        except Exception as e:
            logger.error(f"Failed to get accuracy trend: {e}")
            return []
    
    def get_drift_summary(self, version_id: int) -> Dict[str, Any]:
        """
        Get summary of drift detection across all keys.
        
        Args:
            version_id: Model version ID
            
        Returns:
            Drift summary dictionary
        """
        metrics = self.get_per_key_metrics(version_id)
        
        if not metrics:
            return {"version_id": version_id, "no_data": True}
        
        drift_scores = [m["drift_score"] for m in metrics if m["drift_score"]]
        
        import statistics
        
        return {
            "version_id": version_id,
            "total_keys": len(metrics),
            "keys_with_drift": sum(1 for m in metrics if m["drift_score"] > 0.3),
            "avg_drift_score": (
                statistics.mean(drift_scores) if drift_scores else 0
            ),
            "max_drift_score": max(drift_scores) if drift_scores else 0,
            "min_drift_score": min(drift_scores) if drift_scores else 0,
            "timestamp": datetime.utcnow().isoformat(),
        }
