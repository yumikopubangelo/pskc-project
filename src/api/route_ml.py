# ============================================================
# Routes ML Endpoints Module
# ============================================================
import asyncio
import functools
import json
import logging
import os
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from fastapi import APIRouter, Query, HTTPException, status, BackgroundTasks, Request

from src.api.schemas import (
    PredictionResponse, DriftStatusResponse, RetrainingFromSimulationResponse,
    SimulationEventsRequest, SimulationEventsResponse, ModelPromotionRequest,
    ModelRollbackRequest, PipelineRequest, PipelineResponse, PipelineStatusResponse
)
from src.api.ml_service import (
    get_prediction_payload, get_ml_status_payload, get_model_evaluation_payload,
    get_accuracy_history_payload, get_model_lifecycle_payload, get_model_registry_payload,
    promote_runtime_model_version, rollback_runtime_model_version,
    trigger_runtime_retraining, generate_training_data, train_model, initialize_ml_runtime,
    shutdown_ml_runtime
)
from src.ml.data_collector import get_data_collector
from src.ml.trainer import get_model_trainer
from src.api.training_progress import (
    get_training_progress_tracker, reset_training_progress, TrainingPhase,
    reset_data_generation_progress, get_data_generation_tracker
)

import uuid

logger = logging.getLogger(__name__)


def _raise_ml_registry_error(result: dict) -> None:
    reason = str(result.get("reason") or "unknown")
    detail = result.get("detail")
    if reason in {"model_not_found", "version_not_found", "rollback_target_not_found"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail or reason)
    if reason == "integrity_verification_failed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail or "Model integrity verification failed")
    if reason in {"runtime_reload_failed", "rollback_activation_failed"}:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detail or reason)
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail or reason)


def create_ml_router() -> APIRouter:
    """Create and return the ML endpoints router"""
    router = APIRouter(prefix="/ml", tags=["ml"])

    @router.post("/data/import")
    async def import_training_data():
        """Import seed training data into the DataCollector."""
        collector = get_data_collector()
        seed_file = "data/raw/access_events.json"
        
        if not os.path.exists(seed_file):
            from scripts.seed_data import generate_access_events
            events = generate_access_events(num_events=5000, num_keys=500, num_services=5, duration_hours=24)
            os.makedirs("data/raw", exist_ok=True)
            with open(seed_file, 'w') as f:
                json.dump(events, f)
            logger.info(f"Generated {len(events)} seed events")
        else:
            with open(seed_file, 'r') as f:
                events = json.load(f)
            logger.info(f"Loaded {len(events)} events from {seed_file}")
        
        imported = collector.import_events(events)
        stats = collector.get_stats()
        
        return {
            "success": True,
            "imported_events": imported,
            "total_events": stats["total_events"],
            "unique_keys": stats["unique_keys"],
            "message": f"Successfully imported {imported} events"
        }

    @router.get("/data/stats")
    async def get_data_stats():
        """Get current data collector statistics."""
        collector = get_data_collector()
        return collector.get_stats()

    @router.get("/diagnostics")
    async def get_ml_diagnostics():
        """Get ML diagnostics - why predictions/confidence are low."""
        from collections import Counter
        from src.ml.predictor import get_key_predictor
        
        collector = get_data_collector()
        collector_stats = collector.get_stats()
        recent_events = collector.get_access_sequence(window_seconds=3600, max_events=1000)
        
        data_issues = []
        if not recent_events:
            data_status = "no_data"
            data_issues.append("No events in last hour - call /ml/data/import first")
        else:
            data_status = "ok"
            key_counts = Counter(e.get("key_id") for e in recent_events)
            if len(key_counts) < 10:
                data_issues.append(f"Only {len(key_counts)} unique keys - need more variety")
        
        predictor = get_key_predictor()
        pred_stats = predictor.get_prediction_stats()
        
        try:
            preds = predictor.predict(n=5)
        except:
            preds = []
        
        pred_issues = []
        if not preds:
            pred_status = "no_predictions"
            pred_issues.append("No predictions generated - model may not be trained")
        else:
            pred_status = "ok"
            confs = [p[1] for p in preds]
            avg_conf = sum(confs) / len(confs) if confs else 0
            if avg_conf < 0.3:
                pred_issues.append(f"Low avg confidence: {avg_conf:.2f}")
        
        recommendations = []
        if data_status != "ok":
            recommendations.append("1. Call POST /ml/data/import to load training data")
        if pred_status != "ok" or pred_issues:
            recommendations.append("2. Call POST /ml/retrain to train the model")
        if data_status == "ok" and len(Counter(e.get("key_id") for e in recent_events if recent_events)) < 50:
            recommendations.append("3. Generate more traffic for better patterns")
        
        return {
            "summary": {
                "data_status": data_status,
                "prediction_status": pred_status,
                "collector_events": collector_stats.get("total_events", 0),
                "model_loaded": pred_stats.get("model_loaded", False)
            },
            "data_issues": data_issues,
            "prediction_issues": pred_issues,
            "recommendations": recommendations
        }

    @router.get("/predictions", response_model=PredictionResponse)
    async def get_predictions(n: int = 10):
        """Get ML predictions for keys to pre-cache"""
        return get_prediction_payload(service_id="default", n=n)

    @router.get("/status")
    async def get_ml_status():
        """Get ML model status"""
        try:
            return get_ml_status_payload()
        except Exception as e:
            logger.exception("Error getting ML status: %s", e)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    @router.get("/drift")
    async def get_drift_analysis():
        """Get detailed drift analysis from the EWMA-based concept drift detector."""
        trainer = get_model_trainer()
        drift_stats = trainer._drift_detector.get_stats()
        drift_analysis = trainer._drift_detector.get_drift_analysis()
        
        return {
            "drift_stats": drift_stats,
            "drift_analysis": drift_analysis,
        }

    @router.get("/registry")
    async def get_ml_registry(model_name: Optional[str] = Query(default=None)):
        """Get registry summary for the active ML model lineage."""
        return get_model_registry_payload(model_name=model_name)

    @router.get("/lifecycle")
    async def get_ml_lifecycle(
        limit: int = Query(default=100, ge=1, le=1000),
        model_name: Optional[str] = Query(default=None),
        event_type: Optional[str] = Query(default=None),
    ):
        """Get persistent lifecycle history for ML model operations."""
        return get_model_lifecycle_payload(limit=limit, model_name=model_name, event_type=event_type)

    @router.post("/retrain")
    async def trigger_retraining():
        """Trigger live model retraining using collected runtime events."""
        return trigger_runtime_retraining(force=True)

    @router.get("/evaluate")
    async def evaluate_ml_model():
        """Evaluate the currently active model using recent collected traffic."""
        result = get_model_evaluation_payload()
        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("reason") or "evaluation_failed",
            )
        return result

    @router.post("/promote")
    async def promote_ml_model(req: ModelPromotionRequest):
        """Promote a registered model version to a target stage and optionally activate it."""
        result = promote_runtime_model_version(
            model_name=req.model_name,
            version=req.version,
            target_stage=req.target_stage,
            actor=req.actor,
            notes=req.notes or "",
            make_active=req.make_active,
        )
        if not result.get("success"):
            _raise_ml_registry_error(result)
        return result

    @router.post("/rollback")
    async def rollback_ml_model(req: ModelRollbackRequest):
        """Rollback the active runtime model to a prior secure registry version."""
        result = rollback_runtime_model_version(
            model_name=req.model_name,
            version=req.version,
            actor=req.actor,
            notes=req.notes or "",
        )
        if not result.get("success"):
            _raise_ml_registry_error(result)
        return result

    return router
