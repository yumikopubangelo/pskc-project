# ============================================================
# PSKC — Model Version API Routes
# ============================================================
"""
API endpoints for model version management and lifecycle.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from datetime import datetime
from typing import Optional, List
import logging

from src.database.connection import get_db
from src.database.models import (
    ModelVersion, ModelMetric, TrainingMetadata,
    KeyPrediction, PerKeyMetric, RetrainingHistory,
)
from src.ml.model_version_manager import ModelVersionManager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/models", tags=["models"])


def get_version_manager(db: Session = Depends(get_db)) -> ModelVersionManager:
    """Dependency injection for ModelVersionManager."""
    return ModelVersionManager(db)


@router.post("/versions/create")
async def create_version(
    model_name: str,
    version_number: int,
    status: str = "dev",
    parent_version_id: Optional[int] = None,
    vm: ModelVersionManager = Depends(get_version_manager)
):
    """
    Create a new model version.
    
    Parameters:
    - model_name: Name of the model
    - version_number: Version number
    - status: Version status (dev, staging, production)
    - parent_version_id: Parent version ID for lineage tracking
    """
    try:
        version = vm.create_version(
            model_name=model_name,
            version_number=version_number,
            status=status,
            parent_version_id=parent_version_id
        )
        return {
            "success": True,
            "version_id": version.version_id,
            "model_name": version.model_name,
            "version_number": version.version_number,
            "status": version.status,
            "created_at": version.created_at.isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to create version: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/current/{model_name}")
async def get_current_version(
    model_name: str,
    vm: ModelVersionManager = Depends(get_version_manager)
):
    """Get the currently active production version of a model."""
    version = vm.get_current_version(model_name)
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No production version found for {model_name}"
        )
    
    return {
        "version_id": version.version_id,
        "model_name": version.model_name,
        "version_number": version.version_number,
        "status": version.status,
        "created_at": version.created_at.isoformat()
    }


@router.get("/latest/{model_name}")
async def get_latest_version(
    model_name: str,
    vm: ModelVersionManager = Depends(get_version_manager)
):
    """Get the latest version of a model (any status)."""
    version = vm.get_latest_version(model_name)
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No version found for {model_name}"
        )
    
    return {
        "version_id": version.version_id,
        "model_name": version.model_name,
        "version_number": version.version_number,
        "status": version.status,
        "created_at": version.created_at.isoformat()
    }


@router.get("/{version_id}")
async def get_version(
    version_id: int,
    vm: ModelVersionManager = Depends(get_version_manager)
):
    """Get a specific version by ID."""
    version = vm.get_version(version_id)
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {version_id} not found"
        )
    
    return {
        "version_id": version.version_id,
        "model_name": version.model_name,
        "version_number": version.version_number,
        "status": version.status,
        "created_at": version.created_at.isoformat()
    }


@router.get("/versions/{model_name}")
async def list_versions(
    model_name: str,
    status: Optional[str] = None,
    limit: int = 10,
    vm: ModelVersionManager = Depends(get_version_manager)
):
    """
    List versions for a model with optional filtering.
    
    Parameters:
    - model_name: Name of the model
    - status: Filter by status (dev, staging, production)
    - limit: Maximum number of versions to return
    """
    versions = vm.list_versions(
        model_name=model_name,
        status=status,
        limit=limit
    )
    
    return {
        "model_name": model_name,
        "count": len(versions),
        "versions": [
            {
                "version_id": v.version_id,
                "version_number": v.version_number,
                "status": v.status,
                "created_at": v.created_at.isoformat()
            }
            for v in versions
        ]
    }


@router.post("/{version_id}/switch")
async def switch_version(
    version_id: int,
    new_status: str,
    vm: ModelVersionManager = Depends(get_version_manager)
):
    """
    Switch a version to a new status.
    If promoting to production, current production is demoted to staging.
    
    Parameters:
    - version_id: Version ID to update
    - new_status: New status (dev, staging, production)
    """
    if new_status not in ["dev", "staging", "production"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid status. Must be one of: dev, staging, production"
        )
    
    success = vm.switch_version(version_id, new_status)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {version_id} not found"
        )
    
    return {
        "success": True,
        "version_id": version_id,
        "new_status": new_status
    }


@router.post("/{version_id}/metrics")
async def record_metric(
    version_id: int,
    metric_name: str,
    metric_value: float,
    vm: ModelVersionManager = Depends(get_version_manager)
):
    """
    Record a metric for a version.
    
    Parameters:
    - version_id: Version ID
    - metric_name: Name of the metric (e.g., accuracy, precision, recall)
    - metric_value: Numerical value of the metric
    """
    success = vm.record_metric(version_id, metric_name, metric_value)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record metric"
        )
    
    return {
        "success": True,
        "version_id": version_id,
        "metric_name": metric_name,
        "metric_value": metric_value
    }


@router.get("/{version_id}/metrics")
async def get_metrics(
    version_id: int,
    vm: ModelVersionManager = Depends(get_version_manager)
):
    """Get all metrics for a specific version."""
    metrics = vm.get_version_metrics(version_id)
    if not metrics:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No metrics found for version {version_id}"
        )
    
    return {
        "version_id": version_id,
        "metrics": metrics
    }


@router.post("/{version_id}/training")
async def record_training(
    version_id: int,
    training_start_time: str,
    training_end_time: str,
    samples_count: int,
    accuracy_before: Optional[float] = None,
    accuracy_after: Optional[float] = None,
    vm: ModelVersionManager = Depends(get_version_manager)
):
    """
    Record training metadata for a version.
    
    Parameters:
    - version_id: Version ID
    - training_start_time: ISO format datetime when training started
    - training_end_time: ISO format datetime when training ended
    - samples_count: Number of samples used in training
    - accuracy_before: Model accuracy before training
    - accuracy_after: Model accuracy after training
    """
    try:
        start = datetime.fromisoformat(training_start_time)
        end = datetime.fromisoformat(training_end_time)
        
        success = vm.record_training(
            version_id=version_id,
            training_start_time=start,
            training_end_time=end,
            samples_count=samples_count,
            accuracy_before=accuracy_before,
            accuracy_after=accuracy_after
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to record training metadata"
            )
        
        return {
            "success": True,
            "version_id": version_id,
            "samples_count": samples_count,
            "accuracy_before": accuracy_before,
            "accuracy_after": accuracy_after
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid datetime format: {e}"
        )


@router.get("/{version_id}/summary")
async def get_summary(
    version_id: int,
    vm: ModelVersionManager = Depends(get_version_manager)
):
    """Get a comprehensive summary of a version including metrics and predictions."""
    summary = vm.get_version_summary(version_id)
    if not summary:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {version_id} not found"
        )
    
    return summary


@router.post("/{version_id}/cleanup")
async def cleanup_old_versions(
    model_name: str,
    keep_count: int = 5,
    vm: ModelVersionManager = Depends(get_version_manager)
):
    """
    Delete old versions, keeping only the most recent ones.
    Does not delete production versions.
    
    Parameters:
    - model_name: Name of the model
    - keep_count: Number of recent versions to keep
    """
    deleted_count = vm.cleanup_old_versions(model_name, keep_count)
    return {
        "success": True,
        "model_name": model_name,
        "deleted_count": deleted_count,
        "kept_count": keep_count
    }


# ============================================================
# Model Intelligence Dashboard — comprehensive model overview
# ============================================================

@router.get("/intelligence/dashboard")
async def model_intelligence_dashboard(db: Session = Depends(get_db)):
    """
    Comprehensive model intelligence dashboard.
    Returns all model versions, training history, metrics, predictions,
    River online learning stats, and drift info in one payload.
    """
    try:
        # 1. All model versions with metrics
        versions = (
            db.query(ModelVersion)
            .order_by(desc(ModelVersion.created_at))
            .limit(20)
            .all()
        )

        version_data = []
        for v in versions:
            # Get metrics for this version
            metrics_rows = (
                db.query(ModelMetric)
                .filter(ModelMetric.version_id == v.version_id)
                .all()
            )
            metrics_dict = {m.metric_name: m.metric_value for m in metrics_rows}

            # Get training metadata
            training = (
                db.query(TrainingMetadata)
                .filter(TrainingMetadata.version_id == v.version_id)
                .first()
            )
            training_info = None
            if training:
                duration = None
                if training.training_end_time and training.training_start_time:
                    duration = (training.training_end_time - training.training_start_time).total_seconds()
                training_info = {
                    "samples_count": training.samples_count,
                    "accuracy_before": training.accuracy_before,
                    "accuracy_after": training.accuracy_after,
                    "duration_seconds": duration,
                    "started_at": training.training_start_time.isoformat() if training.training_start_time else None,
                    "ended_at": training.training_end_time.isoformat() if training.training_end_time else None,
                }

            # Prediction stats for this version
            pred_count = (
                db.query(func.count(KeyPrediction.id))
                .filter(KeyPrediction.version_id == v.version_id)
                .scalar()
            ) or 0
            correct_count = (
                db.query(func.count(KeyPrediction.id))
                .filter(KeyPrediction.version_id == v.version_id, KeyPrediction.is_correct == True)
                .scalar()
            ) or 0

            version_data.append({
                "version_id": v.version_id,
                "model_name": v.model_name,
                "version_number": v.version_number,
                "status": v.status,
                "created_at": v.created_at.isoformat(),
                "metrics": metrics_dict,
                "training": training_info,
                "predictions": {
                    "total": pred_count,
                    "correct": correct_count,
                    "accuracy": round(correct_count / pred_count, 4) if pred_count > 0 else None,
                },
                "parent_version_id": v.parent_version_id,
            })

        # 2. Accuracy trend across versions
        accuracy_trend = []
        for vd in reversed(version_data):
            acc = vd["metrics"].get("accuracy") or vd["metrics"].get("val_accuracy")
            top10 = vd["metrics"].get("top_10_accuracy") or vd["metrics"].get("val_top_10_accuracy")
            if acc is not None or top10 is not None:
                accuracy_trend.append({
                    "version": vd["version_number"],
                    "version_id": vd["version_id"],
                    "accuracy": acc,
                    "top_10_accuracy": top10,
                    "created_at": vd["created_at"],
                })

        # 3. Per-key metrics (latest version)
        latest_version_id = versions[0].version_id if versions else None
        per_key_data = []
        if latest_version_id:
            per_key_rows = (
                db.query(PerKeyMetric)
                .filter(PerKeyMetric.version_id == latest_version_id)
                .order_by(desc(PerKeyMetric.total_predictions))
                .limit(20)
                .all()
            )
            per_key_data = [
                {
                    "key": pk.key,
                    "accuracy": pk.accuracy,
                    "drift_score": pk.drift_score,
                    "cache_hit_rate": pk.cache_hit_rate,
                    "total_predictions": pk.total_predictions,
                }
                for pk in per_key_rows
            ]

        # 4. Retraining history
        retrain_rows = (
            db.query(RetrainingHistory)
            .order_by(desc(RetrainingHistory.created_at))
            .limit(10)
            .all()
        )
        retrain_data = [
            {
                "id": r.id,
                "drift_score": r.drift_score,
                "accuracy_before": r.accuracy_before,
                "accuracy_after": r.accuracy_after,
                "improvement": r.improvement_percent,
                "status": r.status,
                "event_count": r.event_count,
                "created_at": r.created_at.isoformat(),
            }
            for r in retrain_rows
        ]

        # 5. River online learning stats (from predictor)
        river_stats = {"initialized": False}
        try:
            from src.ml.predictor import get_predictor
            predictor = get_predictor()
            if predictor:
                stats = predictor.get_prediction_stats()
                river_stats = stats.get("river_online", {"initialized": False})
        except Exception:
            pass

        # 6. Summary stats
        total_versions = db.query(func.count(ModelVersion.version_id)).scalar() or 0
        total_predictions = db.query(func.count(KeyPrediction.id)).scalar() or 0
        total_correct = (
            db.query(func.count(KeyPrediction.id))
            .filter(KeyPrediction.is_correct == True)
            .scalar()
        ) or 0

        return {
            "summary": {
                "total_versions": total_versions,
                "total_predictions": total_predictions,
                "overall_accuracy": round(total_correct / total_predictions, 4) if total_predictions > 0 else None,
                "latest_version": version_data[0] if version_data else None,
            },
            "versions": version_data,
            "accuracy_trend": accuracy_trend,
            "per_key_metrics": per_key_data,
            "retraining_history": retrain_data,
            "river_online": river_stats,
        }

    except Exception as e:
        logger.error(f"Model intelligence dashboard error: {e}")
        return {
            "summary": {"total_versions": 0, "total_predictions": 0, "overall_accuracy": None},
            "versions": [],
            "accuracy_trend": [],
            "per_key_metrics": [],
            "retraining_history": [],
            "river_online": {"initialized": False},
            "error": str(e),
        }
