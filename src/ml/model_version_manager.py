# ============================================================
# PSKC — Model Version Manager
# ============================================================
"""
Manages model versioning, switching, and lifecycle.
Handles creation, tracking, and switching between model versions.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_
import json
import logging

from src.database.models import (
    ModelVersion, ModelMetric, TrainingMetadata,
    KeyPrediction, PerKeyMetric
)

logger = logging.getLogger(__name__)


class ModelVersionManager:
    """
    Manages model versions with database persistence.
    
    Responsibilities:
    - Create new model versions after training
    - Switch between versions
    - Track metrics per version
    - Log predictions for analysis
    - Manage version lifecycle (dev -> staging -> production)
    """
    
    def __init__(self, db_session: Session):
        """
        Initialize ModelVersionManager.
        
        Args:
            db_session: SQLAlchemy database session
        """
        self.db = db_session
    
    def create_version(
        self,
        model_name: str,
        version_number: int,
        status: str = "dev",
        parent_version_id: Optional[int] = None,
        metrics: Optional[Dict[str, Any]] = None
    ) -> ModelVersion:
        """
        Create a new model version.
        
        Args:
            model_name: Name of the model (e.g., "cache_predictor", "key_selector")
            version_number: Semantic version number (e.g., 1, 2, 3)
            status: Version status ("dev", "staging", "production")
            parent_version_id: ID of parent version (for lineage tracking)
            metrics: Initial metrics dict
            
        Returns:
            ModelVersion object
        """
        try:
            version = ModelVersion(
                model_name=model_name,
                version_number=version_number,
                status=status,
                parent_version_id=parent_version_id,
                metrics_json=metrics or {}
            )
            self.db.add(version)
            self.db.commit()
            
            logger.info(
                f"Created model version: {model_name}@v{version_number} "
                f"(id={version.version_id}, status={status})"
            )
            return version
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to create model version: {e}")
            raise
    
    def get_current_version(self, model_name: str) -> Optional[ModelVersion]:
        """
        Get the currently active production version.
        
        Args:
            model_name: Name of the model
            
        Returns:
            ModelVersion object or None if no production version exists
        """
        try:
            version = self.db.query(ModelVersion).filter(
                and_(
                    ModelVersion.model_name == model_name,
                    ModelVersion.status == "production"
                )
            ).order_by(desc(ModelVersion.created_at)).first()
            return version
        except Exception as e:
            logger.error(f"Failed to get current version for {model_name}: {e}")
            return None
    
    def get_latest_version(self, model_name: str) -> Optional[ModelVersion]:
        """
        Get the latest version (regardless of status).
        
        Args:
            model_name: Name of the model
            
        Returns:
            ModelVersion object or None
        """
        try:
            version = self.db.query(ModelVersion).filter(
                ModelVersion.model_name == model_name
            ).order_by(desc(ModelVersion.created_at)).first()
            return version
        except Exception as e:
            logger.error(f"Failed to get latest version for {model_name}: {e}")
            return None
    
    def get_version(self, version_id: int) -> Optional[ModelVersion]:
        """
        Get a specific version by ID.
        
        Args:
            version_id: Version ID
            
        Returns:
            ModelVersion object or None
        """
        try:
            return self.db.query(ModelVersion).filter(
                ModelVersion.version_id == version_id
            ).first()
        except Exception as e:
            logger.error(f"Failed to get version {version_id}: {e}")
            return None
    
    def list_versions(
        self,
        model_name: str,
        status: Optional[str] = None,
        limit: int = 10
    ) -> List[ModelVersion]:
        """
        List model versions with optional filtering.
        
        Args:
            model_name: Name of the model
            status: Filter by status ("dev", "staging", "production")
            limit: Maximum number of versions to return
            
        Returns:
            List of ModelVersion objects
        """
        try:
            query = self.db.query(ModelVersion).filter(
                ModelVersion.model_name == model_name
            )
            if status:
                query = query.filter(ModelVersion.status == status)
            
            versions = query.order_by(
                desc(ModelVersion.created_at)
            ).limit(limit).all()
            return versions
        except Exception as e:
            logger.error(f"Failed to list versions for {model_name}: {e}")
            return []
    
    def switch_version(self, version_id: int, new_status: str) -> bool:
        """
        Switch a version to a new status.
        First, demote current production version to staging.
        
        Args:
            version_id: Version ID to promote
            new_status: New status ("dev", "staging", "production")
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Get the version to promote
            target_version = self.db.query(ModelVersion).filter(
                ModelVersion.version_id == version_id
            ).first()
            
            if not target_version:
                logger.error(f"Version {version_id} not found")
                return False
            
            model_name = target_version.model_name
            
            # If promoting to production, demote current production to staging
            if new_status == "production":
                current_prod = self.db.query(ModelVersion).filter(
                    and_(
                        ModelVersion.model_name == model_name,
                        ModelVersion.status == "production"
                    )
                ).first()
                if current_prod:
                    current_prod.status = "staging"
                    logger.info(
                        f"Demoted version {current_prod.version_id} to staging"
                    )
            
            # Update target version status
            target_version.status = new_status
            self.db.commit()
            
            logger.info(
                f"Version {version_id} switched to {new_status}"
            )
            return True
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to switch version {version_id}: {e}")
            return False
    
    def record_metric(
        self,
        version_id: int,
        metric_name: str,
        metric_value: float
    ) -> bool:
        """
        Record a metric for a specific version.
        
        Args:
            version_id: Version ID
            metric_name: Name of the metric (e.g., "accuracy", "precision")
            metric_value: Metric value
            
        Returns:
            True if successful, False otherwise
        """
        try:
            metric = ModelMetric(
                version_id=version_id,
                metric_name=metric_name,
                metric_value=metric_value,
                recorded_at=datetime.utcnow()
            )
            self.db.add(metric)
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to record metric for version {version_id}: {e}")
            return False
    
    def get_version_metrics(self, version_id: int) -> Dict[str, float]:
        """
        Get all metrics for a version.
        
        Args:
            version_id: Version ID
            
        Returns:
            Dictionary of metric_name: metric_value
        """
        try:
            metrics = self.db.query(ModelMetric).filter(
                ModelMetric.version_id == version_id
            ).all()
            
            return {metric.metric_name: metric.metric_value for metric in metrics}
        except Exception as e:
            logger.error(f"Failed to get metrics for version {version_id}: {e}")
            return {}
    
    def record_training(
        self,
        version_id: int,
        training_start_time: datetime,
        training_end_time: datetime,
        samples_count: int,
        accuracy_before: Optional[float] = None,
        accuracy_after: Optional[float] = None
    ) -> bool:
        """
        Record training metadata for a version.
        
        Args:
            version_id: Version ID
            training_start_time: When training started
            training_end_time: When training ended
            samples_count: Number of samples used
            accuracy_before: Accuracy before training
            accuracy_after: Accuracy after training
            
        Returns:
            True if successful, False otherwise
        """
        try:
            training = TrainingMetadata(
                version_id=version_id,
                training_start_time=training_start_time,
                training_end_time=training_end_time,
                samples_count=samples_count,
                accuracy_before=accuracy_before,
                accuracy_after=accuracy_after
            )
            self.db.add(training)
            self.db.commit()
            
            logger.info(
                f"Recorded training for version {version_id}: "
                f"{samples_count} samples, {accuracy_before} -> {accuracy_after}"
            )
            return True
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to record training for version {version_id}: {e}")
            return False
    
    def record_prediction(
        self,
        version_id: int,
        key: str,
        predicted_value: str,
        actual_value: Optional[str] = None,
        is_correct: Optional[bool] = None,
        confidence: Optional[float] = None
    ) -> bool:
        """
        Record a prediction for analysis.
        
        Args:
            version_id: Version ID
            key: Cache key
            predicted_value: Predicted value
            actual_value: Actual value (if known)
            is_correct: Whether prediction was correct
            confidence: Model confidence in prediction (0-1)
            
        Returns:
            True if successful, False otherwise
        """
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
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to record prediction for version {version_id}: {e}")
            return False
    
    def update_per_key_metrics(
        self,
        version_id: int,
        key: str,
        accuracy: Optional[float] = None,
        drift_score: Optional[float] = None,
        cache_hit_rate: Optional[float] = None
    ) -> bool:
        """
        Update aggregated metrics for a specific key.
        Creates new record or updates existing one.
        
        Args:
            version_id: Version ID
            key: Cache key
            accuracy: Prediction accuracy for this key
            drift_score: Drift score for this key
            cache_hit_rate: Cache hit rate for this key
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Try to find existing record
            metric = self.db.query(PerKeyMetric).filter(
                and_(
                    PerKeyMetric.version_id == version_id,
                    PerKeyMetric.key == key
                )
            ).first()
            
            if metric:
                # Update existing
                if accuracy is not None:
                    metric.accuracy = accuracy
                if drift_score is not None:
                    metric.drift_score = drift_score
                if cache_hit_rate is not None:
                    metric.cache_hit_rate = cache_hit_rate
                metric.updated_at = datetime.utcnow()
            else:
                # Create new
                metric = PerKeyMetric(
                    version_id=version_id,
                    key=key,
                    accuracy=accuracy,
                    drift_score=drift_score,
                    cache_hit_rate=cache_hit_rate,
                    updated_at=datetime.utcnow()
                )
                self.db.add(metric)
            
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to update per-key metrics for {key}: {e}")
            return False
    
    def get_per_key_metrics(
        self,
        version_id: int,
        key: Optional[str] = None
    ) -> List[PerKeyMetric]:
        """
        Get per-key metrics for a version.
        
        Args:
            version_id: Version ID
            key: Optional specific key to filter by
            
        Returns:
            List of PerKeyMetric objects
        """
        try:
            query = self.db.query(PerKeyMetric).filter(
                PerKeyMetric.version_id == version_id
            )
            if key:
                query = query.filter(PerKeyMetric.key == key)
            
            return query.order_by(desc(PerKeyMetric.updated_at)).all()
        except Exception as e:
            logger.error(f"Failed to get per-key metrics for version {version_id}: {e}")
            return []
    
    def get_version_summary(self, version_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a comprehensive summary of a version including metrics and predictions.
        
        Args:
            version_id: Version ID
            
        Returns:
            Dictionary with version info or None if version not found
        """
        try:
            version = self.get_version(version_id)
            if not version:
                return None
            
            metrics = self.get_version_metrics(version_id)
            training = self.db.query(TrainingMetadata).filter(
                TrainingMetadata.version_id == version_id
            ).first()
            
            # Get prediction accuracy
            predictions = self.db.query(KeyPrediction).filter(
                KeyPrediction.version_id == version_id
            ).all()
            
            total_predictions = len(predictions)
            correct_predictions = sum(1 for p in predictions if p.is_correct)
            prediction_accuracy = (
                correct_predictions / total_predictions
                if total_predictions > 0 else 0
            )
            
            return {
                "version_id": version.version_id,
                "model_name": version.model_name,
                "version_number": version.version_number,
                "status": version.status,
                "created_at": version.created_at.isoformat(),
                "metrics": metrics,
                "training": {
                    "samples_count": training.samples_count if training else None,
                    "accuracy_before": training.accuracy_before if training else None,
                    "accuracy_after": training.accuracy_after if training else None,
                    "duration_seconds": (
                        (training.training_end_time - training.training_start_time).total_seconds()
                        if training else None
                    )
                } if training else None,
                "predictions": {
                    "total": total_predictions,
                    "correct": correct_predictions,
                    "accuracy": prediction_accuracy
                }
            }
        except Exception as e:
            logger.error(f"Failed to get version summary for {version_id}: {e}")
            return None
    
    def cleanup_old_versions(
        self,
        model_name: str,
        keep_count: int = 5
    ) -> int:
        """
        Delete old versions, keeping only the most recent ones.
        
        Args:
            model_name: Name of the model
            keep_count: Number of recent versions to keep
            
        Returns:
            Number of versions deleted
        """
        try:
            # Get all versions sorted by creation date
            versions = self.db.query(ModelVersion).filter(
                ModelVersion.model_name == model_name
            ).order_by(desc(ModelVersion.created_at)).all()
            
            # Mark old versions for deletion
            deleted_count = 0
            for version in versions[keep_count:]:
                # Don't delete production versions
                if version.status != "production":
                    self.db.delete(version)
                    deleted_count += 1
            
            if deleted_count > 0:
                self.db.commit()
                logger.info(
                    f"Cleaned up {deleted_count} old versions for {model_name}"
                )
            
            return deleted_count
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to cleanup old versions for {model_name}: {e}")
            return 0
