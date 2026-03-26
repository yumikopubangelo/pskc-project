# ============================================================
# Routes ML Training Endpoints Module
# ============================================================
import asyncio
import functools
import logging
from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Query, HTTPException, status, WebSocket, WebSocketDisconnect

from src.api.ml_service import (
    generate_training_data,
    train_model,
    get_training_plan,
    initialize_ml_runtime,
    shutdown_ml_runtime,
)
from src.api.training_progress import (
    get_training_progress_tracker, reset_training_progress, TrainingPhase,
    reset_data_generation_progress, get_data_generation_tracker,
    REDIS_PROGRESS_KEY
)

logger = logging.getLogger(__name__)


def create_training_router() -> APIRouter:
    """Create and return the ML training endpoints router"""
    router = APIRouter(prefix="/ml/training", tags=["training"])

    @router.post("/generate")
    async def generate_training_data_endpoint(
        num_events: Optional[int] = Query(default=None, ge=100),
        num_keys: Optional[int] = Query(default=None, ge=10),
        num_services: Optional[int] = Query(default=None, ge=1),
        scenario: str = Query(default="dynamic", description="Scenario: siakad, sevima, pddikti, dynamic"),
        traffic_profile: str = Query(default="normal", description="Traffic profile: normal, heavy, prime_time, overload"),
        duration_hours: Optional[int] = Query(default=None, ge=1),
    ):
        """
        Generate synthetic training data based on scenario and traffic profile.
        
        Returns immediately with HTTP 202 (Accepted) and starts generation in background.
        Poll /ml/training/generate/progress endpoint to check status.
        """
        from fastapi.responses import JSONResponse
        
        if num_events is None or num_keys is None or num_services is None or duration_hours is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="All numeric fields are required"
            )
        
        try:
            reset_data_generation_progress()
            get_data_generation_tracker().start_generation(num_events)
            
            # ✅ FIX: Start in background task instead of waiting for it
            # This returns immediately with HTTP 202, letting client poll for progress
            async def run_generation_in_background():
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    functools.partial(
                        generate_training_data,
                        num_events=num_events,
                        num_keys=num_keys,
                        num_services=num_services,
                        scenario=scenario,
                        traffic_profile=traffic_profile,
                        duration_hours=duration_hours,
                    ),
                )
            
            # Create and schedule background task (don't wait for it)
            asyncio.create_task(run_generation_in_background())
            
            # Return immediately with 202 Accepted
            return JSONResponse(
                status_code=202,
                content={
                    "status": "generating",
                    "message": "Data generation started in background",
                    "num_events": num_events,
                    "num_keys": num_keys,
                    "num_services": num_services,
                    "scenario": scenario,
                    "traffic_profile": traffic_profile,
                    "poll_endpoint": "/ml/training/generate-progress",
                    "instructions": "Poll the progress endpoint to check completion status"
                }
            )
        except Exception as e:
            logger.exception("Error starting data generation: %s", e)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    @router.get("/generate/estimate")
    async def estimate_data_generation(
        num_events: Optional[int] = Query(default=None, ge=100),
        num_keys: Optional[int] = Query(default=None, ge=10),
        num_services: Optional[int] = Query(default=None, ge=1),
        scenario: str = Query(default="dynamic"),
        traffic_profile: str = Query(default="normal"),
        duration_hours: Optional[int] = Query(default=None, ge=1),
    ):
        """Estimate the number of training samples that will be generated with given parameters."""
        if num_events is None or num_keys is None or num_services is None or duration_hours is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="All numeric fields are required"
            )
        
        try:
            # Basic estimation: num_events is the primary factor
            # Also consider the traffic profile multiplier
            traffic_profile_multipliers = {
                "normal": 1.0,
                "heavy": 1.2,
                "prime_time": 1.15,
                "overload": 1.5,
            }
            
            multiplier = traffic_profile_multipliers.get(traffic_profile, 1.0)
            estimated_events = int(num_events * multiplier)
            
            # Calculate approximate file size (rough estimate: 200 bytes per event)
            bytes_per_event = 200
            estimated_bytes = estimated_events * bytes_per_event
            
            # Format size in human-readable format
            if estimated_bytes < 1024:
                size_formatted = f"{estimated_bytes} B"
            elif estimated_bytes < 1024 * 1024:
                size_formatted = f"{estimated_bytes / 1024:.1f} KB"
            else:
                size_formatted = f"{estimated_bytes / (1024 * 1024):.1f} MB"
            
            return {
                "estimated_events": estimated_events,
                "bytes_per_event": bytes_per_event,
                "estimated_bytes": estimated_bytes,
                "estimated_size_formatted": size_formatted,
                "traffic_profile_multiplier": multiplier,
                "base_events": num_events,
                "scenario": scenario,
                "num_keys": num_keys,
                "num_services": num_services,
                "duration_hours": duration_hours,
            }
        except Exception as e:
            logger.exception("Error estimating data generation: %s", e)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    @router.get("/collector/config")
    async def get_collector_config():
        """Get data collector configuration and limits."""
        from config.settings import settings
        from src.ml.data_collector import get_data_collector
        
        collector = get_data_collector()
        stats = collector.get_stats()
        
        return {
            "max_events": settings.ml_collector_max_events,
            "current_events": stats.get("total_events", 0),
            "usage_percent": (stats.get("total_events", 0) / settings.ml_collector_max_events * 100) if settings.ml_collector_max_events > 0 else 0,
            "window_seconds": settings.ml_collector_window_seconds,
            "historical_stats_ttl_hours": settings.ml_collector_historical_stats_ttl_hours,
            "historical_stats_max_entries": settings.ml_collector_historical_stats_max_entries,
            "configuration_note": "To change these limits, set environment variables: ML_COLLECTOR_MAX_EVENTS, ML_COLLECTOR_WINDOW_SECONDS, ML_COLLECTOR_HISTORICAL_STATS_TTL_HOURS, ML_COLLECTOR_HISTORICAL_STATS_MAX_ENTRIES",
        }

    @router.post("/train")
    async def train_model_endpoint(
        force: bool = Query(default=True),
        reason: str = Query(default="manual", description="Reason for training: manual, drift_detected, scheduled"),
        quality_profile: str = Query(default="balanced", description="Training quality profile: fast, balanced, thorough"),
        time_budget_minutes: int = Query(default=30, ge=5, le=60, description="Requested time budget in minutes"),
    ):
        """
        Train the ML model using collected data.
        
        Returns immediately with status. Use WebSocket at /ml/training/ws for real-time updates
        or poll /ml/training/progress for status updates.
        """
        from src.api.ml_service import get_model_trainer
        from fastapi.responses import JSONResponse
        
        trainer = get_model_trainer()
        
        # Check if training already in progress
        if trainer._is_training:
            return JSONResponse(
                status_code=202,
                content={
                    "status": "already_training",
                    "message": "Training is already in progress. Watch the WebSocket stream for updates.",
                    "websocket_url": "/ml/training/ws",
                    "progress_endpoint": "/ml/training/progress"
                }
            )
        
        try:
            # ✅ FIX: Start training in background task instead of waiting
            async def run_training_in_background():
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    functools.partial(
                        train_model,
                        force=force,
                        reason=reason,
                        quality_profile=quality_profile,
                        time_budget_minutes=time_budget_minutes,
                    ),
                )
            
            # Create and schedule background task (don't wait for it)
            asyncio.create_task(run_training_in_background())
            
            # Return immediately with 202 Accepted
            return JSONResponse(
                status_code=202,
                content={
                    "status": "training_started",
                    "message": "Model training started in background",
                    "reason": reason,
                    "force": force,
                    "quality_profile": quality_profile,
                    "time_budget_minutes": time_budget_minutes,
                    "websocket_url": "/ml/training/ws",
                    "progress_endpoint": "/ml/training/progress",
                    "instructions": "Connect to WebSocket or poll progress endpoint for real-time updates"
                }
            )
        except Exception as e:
            logger.exception("Error starting training: %s", e)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    @router.post("/reset-lock")
    async def reset_training_lock():
        """Force-clear the _is_training lock on the trainer."""
        from src.api.ml_service import get_model_trainer
        trainer = get_model_trainer()
        was_locked = trainer._is_training
        trainer._is_training = False
        logger.warning("Training lock manually reset (was_locked=%s)", was_locked)
        return {"reset": True, "was_locked": was_locked}

    @router.post("/reset-model")
    async def reset_model_state():
        """Delete the incremental model file and clear the training lock."""
        from src.api.ml_service import get_model_trainer
        
        trainer = get_model_trainer()
        was_locked = trainer._is_training
        trainer._is_training = False
        reset_result = trainer._incremental_persistence.reset()
        trainer._model.is_trained = False
        trainer._active_model_version = None
        
        try:
            import redis as _redis, os as _os
            r = _redis.Redis(
                host=_os.environ.get("REDIS_HOST", "redis"),
                port=int(_os.environ.get("REDIS_PORT", "6379")),
                db=int(_os.environ.get("REDIS_DB", "0")),
                password=_os.environ.get("REDIS_PASSWORD", "pskc_redis_secret"),
                decode_responses=True,
                socket_connect_timeout=2,
            )
            r.delete(REDIS_PROGRESS_KEY)
        except Exception:
            pass

        logger.warning(
            "Model state reset by user — incremental model deleted, lock cleared. "
            "Next training will be accepted as initial model."
        )
        return {
            "success": True,
            "was_locked": was_locked,
            "file_deleted": reset_result.get("file_existed", False),
            "message": "Model reset complete. The next training run will be accepted regardless of accuracy.",
        }

    @router.get("/progress")
    async def get_training_progress():
        """Get real-time training progress for the current training session."""
        tracker = get_training_progress_tracker()
        return tracker.get_progress_summary()

    @router.get("/generate-progress")
    async def get_data_generation_progress():
        """Get progress for data generation."""
        tracker = get_data_generation_tracker()
        summary = tracker.get_summary()
        
        return {
            **summary,
            "message": f"Generating {summary.get('total', 0)} training events...",
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

    @router.get("/state")
    async def get_training_state():
        """Get the last saved training state from Redis."""
        tracker = get_training_progress_tracker()
        saved_state = tracker.get_last_saved_state()
        
        if saved_state:
            return {
                "state": saved_state,
                "source": "redis",
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
        else:
            return {
                "state": None,
                "source": "none",
                "message": "No prior training state found",
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }

    @router.get("/plan")
    async def get_training_plan_endpoint(
        quality_profile: str = Query(default="balanced", description="Training quality profile: fast, balanced, thorough"),
        time_budget_minutes: int = Query(default=30, ge=5, le=60, description="Requested time budget in minutes"),
    ):
        """Return a training recommendation and bounded runtime plan."""
        return get_training_plan(
            quality_profile=quality_profile,
            time_budget_minutes=time_budget_minutes,
        )

    @router.post("/train-improved")
    async def train_model_improved(
        use_balancing: bool = Query(default=True, description="Use class balancing"),
        use_augmentation: bool = Query(default=True, description="Use data augmentation"),
        use_feature_selection: bool = Query(default=True, description="Use feature selection"),
        data_path: Optional[str] = Query(default=None, description="Path to training data file"),
    ):
        """Train model with improved hyperparameters, data balancing, and feature selection."""
        from src.api.training_progress import reset_training_progress
        
        reset_training_progress()
        tracker = get_training_progress_tracker()
        tracker.start_training()
        
        try:
            tracker.update_progress(
                phase=TrainingPhase.LOADING_DATA,
                progress_percent=10.0,
                current_step=1,
                total_steps=10,
                message="Loading or generating training data...",
            )
            
            return {
                "success": False,
                "message": "Improved training endpoint available. Configure and install the improved training script.",
                "note": "Use POST /ml/training/train for current training with existing model improvements.",
                "available_features": {
                    "class_balancing": use_balancing,
                    "data_augmentation": use_augmentation,
                    "feature_selection": use_feature_selection,
                }
            }
            
        except Exception as e:
            tracker.finish_training(success=False)
            logger.exception("Error in improved training: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e)
            )

    @router.websocket("/progress/stream")
    async def websocket_training_progress(websocket: WebSocket):
        """WebSocket endpoint for real-time training progress updates."""
        await websocket.accept()
        client_id = id(websocket)
        logger.info(f"Training progress WebSocket client connected: {client_id}")

        try:
            tracker = get_training_progress_tracker()
            saved_state = tracker.get_last_saved_state()
            if saved_state:
                await websocket.send_json({
                    **saved_state,
                    "_source": "saved_state",
                    "message": "Resuming from saved state..."
                })
                logger.info(f"Sent saved state to client {client_id}")
            
            last_update_count = -1
            seen_training_start = False

            while True:
                tracker = get_training_progress_tracker()
                current_count = len(tracker.updates)
                phase = tracker.current_phase

                # Detect tracker reset (new training session started while WS was open)
                if current_count < last_update_count:
                    last_update_count = -1
                    seen_training_start = False

                if phase not in (TrainingPhase.IDLE, TrainingPhase.COMPLETED, TrainingPhase.FAILED):
                    seen_training_start = True

                if current_count > last_update_count:
                    latest = tracker.get_latest_update()
                    if latest:
                        payload = latest.to_dict()
                        elapsed = (tracker.end_time or datetime.utcnow().timestamp()) - (tracker.start_time or datetime.utcnow().timestamp())
                        payload["elapsed_seconds"] = max(0.0, elapsed)
                        await websocket.send_json(payload)
                    last_update_count = current_count

                if seen_training_start and phase in (TrainingPhase.COMPLETED, TrainingPhase.FAILED):
                    logger.info(f"Training {phase.value} — closing WebSocket for client {client_id}")
                    try:
                        await websocket.close(code=1000)
                    except Exception:
                        pass
                    break

                await asyncio.sleep(0.5)

        except WebSocketDisconnect:
            logger.info(f"Training progress WebSocket client disconnected: {client_id}")
        except Exception as e:
            logger.exception(f"Training progress WebSocket error for client {client_id}: {e}")
            await websocket.close(code=1011, reason="Internal error")

    @router.websocket("/generate-progress/stream")
    async def websocket_data_generation_progress(websocket: WebSocket):
        """WebSocket endpoint for real-time data generation progress."""
        await websocket.accept()
        client_id = id(websocket)
        logger.info(f"Data generation WebSocket client connected: {client_id}")

        try:
            last_processed = -1
            idle_ticks = 0
            max_idle_before_timeout = 240
            seen_in_progress = False

            while True:
                tracker = get_data_generation_tracker()
                current = tracker.processed_events
                total = tracker.total_events

                if total > 0 and current < total:
                    seen_in_progress = True

                if current > last_processed:
                    idle_ticks = 0
                    summary = tracker.get_summary()
                    await websocket.send_json({
                        **summary,
                        "message": f"Generating {total} training events..." if total > 0 else "Initializing...",
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "done": False,
                    })
                    last_processed = current
                else:
                    idle_ticks += 1

                if seen_in_progress and total > 0 and current >= total:
                    summary = tracker.get_summary()
                    await websocket.send_json({
                        **summary,
                        "message": "Data generation complete.",
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "done": True,
                    })
                    logger.info(f"Data generation complete for client {client_id} ({current}/{total} events)")
                    # Add a small delay to ensure the frontend receives the completion message
                    await asyncio.sleep(1)
                    break

                if idle_ticks % 5 == 0:
                    if seen_in_progress:
                        summary = tracker.get_summary()
                        await websocket.send_json({
                            **summary,
                            "message": f"Still generating... ({current}/{total})",
                            "timestamp": datetime.utcnow().isoformat() + "Z",
                            "done": False,
                        })
                    else:
                        await websocket.send_json({
                            "processed": 0, "total": total or 0, "percent": 0,
                            "message": "Waiting for generation to start...",
                            "timestamp": datetime.utcnow().isoformat() + "Z",
                            "done": False,
                        })

                if idle_ticks > max_idle_before_timeout:
                    logger.warning(f"Data generation WebSocket idle timeout for client {client_id}")
                    await websocket.send_json({
                        "processed": current, "total": total or 0, "percent": 0,
                        "message": "Generation timeout - no activity detected",
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "done": False,
                    })
                    break

                await asyncio.sleep(0.5)

        except WebSocketDisconnect:
            logger.info(f"Data generation WebSocket client disconnected: {client_id}")
        except Exception as e:
            logger.exception(f"Data generation WebSocket error for client {client_id}: {e}")
            try:
                await websocket.close(code=1011, reason="Internal error")
            except Exception:
                pass

    return router
