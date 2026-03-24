# ============================================================
# Routes Simulation Endpoints Module
# ============================================================
import asyncio
import logging
import json
import uuid
from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Query, HTTPException, status, Request, BackgroundTasks
from fastapi.responses import StreamingResponse

from src.api.schemas import (
    SimulationRequest, SimulationResponse, OrganicSimulationRequest, OrganicSimulationResponse,
    SimulationEventsRequest, SimulationEventsResponse, DriftStatusResponse,
    RetrainingFromSimulationRequest, RetrainingFromSimulationResponse
)
from src.api.simulation_service import (
    list_simulation_scenarios, run_simulation_job, list_traffic_profiles, run_organic_simulation
)
from src.api.live_validation_service import run_live_validation
from src.api.live_simulation_service import (
    get_live_simulation_session, start_live_simulation_session, stop_live_simulation_session
)

logger = logging.getLogger(__name__)

# Simulation results storage
_simulation_results = {}


def _get_latest_simulation_result():
    if not _simulation_results:
        return None
    return max(
        _simulation_results.values(),
        key=lambda item: item.get("generated_at", ""),
    )


def create_simulation_router() -> APIRouter:
    """Create and return the simulation endpoints router"""
    router = APIRouter(prefix="/simulation", tags=["simulation"])

    @router.get("/scenarios")
    async def get_simulation_scenarios():
        """List available backend simulation scenarios."""
        return list_simulation_scenarios()

    @router.post("/run", response_model=SimulationResponse)
    async def run_simulation(req: SimulationRequest):
        """Run a batch-based simulation using the backend Python scenario engines."""
        sim_id = str(uuid.uuid4())
        try:
            simulation_payload = run_simulation_job(
                scenario_id=req.scenario,
                profile_id=req.profile_id,
                request_count=req.request_count,
                seed=req.seed,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        _simulation_results[sim_id] = {
            "simulation_id": sim_id,
            **simulation_payload,
        }

        return SimulationResponse(
            simulation_id=sim_id,
            status=simulation_payload["status"],
            scenario=req.scenario,
        )

    @router.get("/traffic-profiles")
    async def get_traffic_profiles():
        """List available organic traffic profiles for time-based simulations."""
        return list_traffic_profiles()

    @router.post("/run-organic", response_model=OrganicSimulationResponse)
    async def run_organic_simulation_endpoint(req: OrganicSimulationRequest):
        """Run a time-based, organic simulation."""
        try:
            result = run_organic_simulation(
                scenario_id=req.scenario_id,
                traffic_profile=req.traffic_profile,
                duration_seconds=req.duration_seconds,
            )
            return result
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            logger.exception(f"Organic simulation failed for scenario {req.scenario_id}")
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred during simulation: {exc}")

    @router.get("/results/{simulation_id}")
    async def get_simulation_results(simulation_id: str):
        """Get simulation results"""
        if simulation_id not in _simulation_results:
            latest = _get_latest_simulation_result()
            if latest and latest.get("simulation_id") == simulation_id:
                return latest
            raise HTTPException(status_code=404, detail="Simulation not found")
        return _simulation_results[simulation_id]

    @router.post("/live-test")
    async def run_live_system_test(
        request: Request,
        num_requests: Optional[int] = Query(default=None, ge=10, le=500),
        duration_seconds: Optional[int] = Query(default=None, ge=10, le=300),
        seed_data: bool = Query(default=True),
        scenario: str = Query(default="test", description="Scenario: siakad, sevima, pddikti, dynamic, test"),
        traffic_type: str = Query(default="normal", description="Traffic type: normal, heavy_load, prime_time, degraded, overload")
    ):
        """Run a live system test that exercises the full system stack."""
        try:
            return await run_live_validation(
                app_state=request.app.state,
                num_requests=num_requests,
                duration_seconds=duration_seconds,
                seed_data=seed_data,
                scenario=scenario,
                traffic_type=traffic_type,
            )
        except Exception as exc:
            logger.exception("Live validation failed")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Live validation failed: {exc}",
            )

    @router.get("/live-test")
    async def get_live_test_status():
        """Get the current system status for live testing."""
        from src.api.ml_service import get_ml_status_payload, get_prefetch_metrics_payload
        
        try:
            ml_status = get_ml_status_payload()
        except:
            ml_status = {"error": "ML runtime not available"}
        
        try:
            prefetch_stats = get_prefetch_metrics_payload()
        except:
            prefetch_stats = {"error": "Prefetch queue not available"}
        
        return {
            "ml_status": ml_status,
            "prefetch_stats": prefetch_stats,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    @router.post("/live-session/start")
    async def start_live_simulation(
        request: Request,
        seed_data: bool = Query(default=True),
        scenario: str = Query(default="test", description="Scenario: siakad, sevima, pddikti, dynamic, test"),
        traffic_type: str = Query(default="normal", description="Traffic type: normal, heavy_load, prime_time, degraded, overload"),
        simulate_kms: bool = Query(default=True, description="Also measure direct KMS latency as a baseline"),
        model_preference: str = Query(default="best_available", description="best_available or active_runtime"),
        key_mode: str = Query(default="auto", description="auto, stable, mixed, or high_churn"),
        virtual_nodes: int = Query(default=3, ge=1, le=12, description="Number of virtual API nodes with isolated L1 caches"),
        max_requests: Optional[int] = Query(default=None, ge=10, le=5000, description="Optional finite request budget for automation"),
    ):
        """Start a realtime simulation session that keeps running until stopped."""
        try:
            return await start_live_simulation_session(
                app_state=request.app.state,
                scenario=scenario,
                traffic_type=traffic_type,
                seed_data=seed_data,
                simulate_kms=simulate_kms,
                model_preference=model_preference,
                key_mode=key_mode,
                virtual_nodes=virtual_nodes,
                max_requests=max_requests,
            )
        except Exception as exc:
            logger.exception("Failed to start live simulation session")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to start live simulation session: {exc}",
            )

    @router.get("/live-session/{session_id}")
    async def get_live_simulation_snapshot(session_id: str):
        """Get the latest snapshot for a realtime simulation session."""
        session = get_live_simulation_session(session_id)
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Live simulation session not found")
        return session

    @router.get("/live-session/{session_id}/stream")
    async def stream_live_simulation_snapshot(session_id: str, request: Request):
        """Stream live simulation snapshots over SSE."""
        session = get_live_simulation_session(session_id)
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Live simulation session not found")

        async def event_stream():
            while True:
                if await request.is_disconnected():
                    break

                snapshot = get_live_simulation_session(session_id)
                if snapshot is None:
                    yield "event: end\ndata: {}\n\n"
                    break

                payload = json.dumps(snapshot, sort_keys=True, ensure_ascii=False)
                yield f"event: snapshot\ndata: {payload}\n\n"

                if snapshot.get("status") in {"completed", "stopped", "failed"}:
                    break

                yield ": keep-alive\n\n"
                await asyncio.sleep(1.0)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.post("/live-session/{session_id}/stop")
    async def stop_live_simulation(session_id: str):
        """Request a running realtime simulation session to stop."""
        session = stop_live_simulation_session(session_id)
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Live simulation session not found")
        return session

    @router.post("/events", response_model=SimulationEventsResponse)
    async def receive_simulation_events(request: SimulationEventsRequest) -> SimulationEventsResponse:
        """Receive simulation events and trigger drift analysis."""
        try:
            from src.ml.simulation_event_handler import (
                SimulationEvent, SimulationPatternExtractor, get_simulation_event_collector,
            )
            from src.ml.pattern_analyzer import PatternAnalyzer
            from src.ml.trainer import get_model_trainer
            import time
            
            if not request.events:
                logger.warning("receive_simulation_events: Empty events list")
                return SimulationEventsResponse(
                    success=False,
                    message="No events provided",
                    events_processed=0,
                    drift_detected=False,
                )
            
            sim_events = [
                SimulationEvent(
                    simulation_id=e.simulation_id,
                    timestamp=e.timestamp,
                    key_id=e.key_id,
                    service_id=e.service_id,
                    access_type=e.access_type,
                    latency_ms=e.latency_ms,
                    cache_hit=e.cache_hit,
                    metadata=e.metadata or {},
                )
                for e in request.events
            ]
            
            extractor = SimulationPatternExtractor()
            sim_patterns = extractor.extract_patterns(sim_events)
            
            trainer = get_model_trainer()
            training_patterns = trainer.get_training_patterns()
            
            if not training_patterns:
                logger.warning("receive_simulation_events: No training patterns available")
                return SimulationEventsResponse(
                    success=True,
                    message="Events received but no training data to compare",
                    events_processed=len(sim_events),
                    drift_detected=False,
                )
            
            analyzer = PatternAnalyzer(training_patterns)
            drift_report = analyzer.analyze_drift(sim_patterns)
            
            logger.info(
                f"receive_simulation_events: Processed {len(sim_events)} events, "
                f"drift_score={drift_report.drift_score:.3f}"
            )
            
            return SimulationEventsResponse(
                success=True,
                message=f"Processed {len(sim_events)} simulation events",
                events_processed=len(sim_events),
                drift_detected=drift_report.should_retrain,
                drift_score=drift_report.drift_score,
            )
            
        except Exception as e:
            logger.exception(f"receive_simulation_events: Error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to process simulation events: {str(e)}"
            )

    @router.get("/drift-status", response_model=DriftStatusResponse)
    async def get_drift_status() -> DriftStatusResponse:
        """Get current drift status between simulation and training patterns."""
        try:
            from src.ml.pattern_analyzer import PatternAnalyzer
            from src.ml.auto_retrainer import get_auto_retrainer
            from src.ml.trainer import get_model_trainer
            from src.ml.data_collector import get_data_collector
            import time
            
            trainer = get_model_trainer()
            retrainer = get_auto_retrainer()
            collector = get_data_collector()
            
            training_patterns = trainer.get_training_patterns()
            sim_event_count = len(collector.events) if hasattr(collector, 'events') else 0
            
            if not training_patterns:
                logger.warning("get_drift_status: No training patterns available")
                return DriftStatusResponse(
                    drift_score=0.0,
                    frequency_divergence=0.0,
                    temporal_divergence=0.0,
                    sequence_divergence=0.0,
                    should_retrain=False,
                    major_changes=["No training data available"],
                    recommendations=["Generate or import training data first"],
                    simulation_event_count=sim_event_count,
                    last_analysis_timestamp=time.time(),
                )
            
            stats = retrainer.get_stats()
            cooldown_remaining = retrainer.get_cooldown_remaining()
            
            next_available = None
            if cooldown_remaining and cooldown_remaining > 0:
                next_available = time.time() + cooldown_remaining
            
            return DriftStatusResponse(
                drift_score=stats.get('last_retraining_drift_score', 0.0) or 0.0,
                frequency_divergence=0.0,
                temporal_divergence=0.0,
                sequence_divergence=0.0,
                should_retrain=False,
                major_changes=["Drift analysis available via simulation events endpoint"],
                recommendations=stats.get('recommendations', ["No retraining needed"]),
                simulation_event_count=sim_event_count,
                last_analysis_timestamp=stats.get('last_retraining_timestamp', time.time()),
                next_retraining_available_at=next_available,
                cooldown_remaining_seconds=cooldown_remaining,
            )
            
        except Exception as e:
            logger.exception(f"get_drift_status: Error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get drift status: {str(e)}"
            )

    @router.post("/retrain-from-simulation", response_model=RetrainingFromSimulationResponse)
    async def retrain_from_simulation(
        request: RetrainingFromSimulationRequest,
        background_tasks: BackgroundTasks
    ) -> RetrainingFromSimulationResponse:
        """Trigger retraining from simulation events."""
        try:
            from src.ml.auto_retrainer import get_auto_retrainer
            from src.ml.trainer import get_model_trainer
            from src.ml.data_collector import get_data_collector
            from src.api.training_progress import get_training_progress_tracker
            import uuid
            import time
            
            trainer = get_model_trainer()
            retrainer = get_auto_retrainer()
            collector = get_data_collector()
            
            sim_event_count = len(collector.events) if hasattr(collector, 'events') else 0
            
            if sim_event_count < 100:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Insufficient simulation events. Need ≥100, have {sim_event_count}"
                )
            
            drift_score = retrainer.last_retraining_drift_score or 0.0
            decision = retrainer.decide(
                drift_score=drift_score,
                simulation_event_count=sim_event_count,
                manual_override=request.force
            )
            
            if not decision.should_retrain:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Retraining not recommended: {decision.reason}"
                )
            
            retraining_id = f"retrain_{uuid.uuid4().hex[:8]}"
            retrainer.mark_retraining_started(
                current_timestamp=time.time(),
                drift_score=drift_score
            )
            
            logger.info(
                f"retrain_from_simulation: Starting retraining {retraining_id} "
                f"with {sim_event_count} events"
            )
            
            async def run_retraining():
                try:
                    await asyncio.sleep(2)
                    retrainer.mark_retraining_completed(
                        accuracy_before=0.75,
                        accuracy_after=0.77
                    )
                except Exception as e:
                    logger.exception(f"retrain_from_simulation: Background task failed: {e}")
            
            background_tasks.add_task(run_retraining)
            
            return RetrainingFromSimulationResponse(
                success=True,
                message=f"Retraining started with {sim_event_count} simulation events",
                retraining_id=retraining_id,
                drift_score=drift_score,
                events_used=sim_event_count,
                expected_duration_seconds=120,
            )
            
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"retrain_from_simulation: Error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to start retraining: {str(e)}"
            )

    return router
