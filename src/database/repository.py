# ============================================================
# PSKC — Data Repository (CRUD Operations)
# ============================================================
"""Repository pattern for data access layer CRUD operations."""
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_

from src.database.models import (
    SimulationEvent,
    RetrainingHistory,
    DriftAnalysisHistory,
)

logger = logging.getLogger(__name__)


class Repository:
    """
    Repository for CRUD operations on simulation learning data.
    
    Provides abstract data access layer for all three main tables.
    """
    
    # ====================================================================
    # SimulationEvent Operations
    # ====================================================================
    
    @staticmethod
    def create_simulation_event(
        db: Session,
        simulation_id: str,
        timestamp: datetime,
        key_id: str,
        service_id: str,
        latency_ms: float,
        cache_hit: bool,
        features: Optional[Dict[str, Any]] = None,
    ) -> SimulationEvent:
        """
        Create a new simulation event record.
        
        Args:
            db: Database session
            simulation_id: Simulation identifier
            timestamp: Event timestamp
            key_id: Cache key identifier
            service_id: Service identifier
            latency_ms: Latency in milliseconds
            cache_hit: Whether cache was hit
            features: Optional JSON features
            
        Returns:
            Created SimulationEvent instance
        """
        event = SimulationEvent(
            simulation_id=simulation_id,
            timestamp=timestamp,
            key_id=key_id,
            service_id=service_id,
            latency_ms=latency_ms,
            cache_hit=cache_hit,
            features=features,
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        return event
    
    @staticmethod
    def get_simulation_event(db: Session, event_id: int) -> Optional[SimulationEvent]:
        """
        Get a simulation event by ID.
        
        Args:
            db: Database session
            event_id: Event ID
            
        Returns:
            SimulationEvent or None if not found
        """
        return db.query(SimulationEvent).filter(SimulationEvent.id == event_id).first()
    
    @staticmethod
    def get_simulation_events_by_simulation_id(
        db: Session,
        simulation_id: str,
        limit: int = 1000,
        offset: int = 0,
    ) -> List[SimulationEvent]:
        """
        Get all events for a specific simulation.
        
        Args:
            db: Database session
            simulation_id: Simulation identifier
            limit: Maximum records to return
            offset: Record offset for pagination
            
        Returns:
            List of SimulationEvent records
        """
        return (
            db.query(SimulationEvent)
            .filter(SimulationEvent.simulation_id == simulation_id)
            .order_by(desc(SimulationEvent.timestamp))
            .limit(limit)
            .offset(offset)
            .all()
        )
    
    @staticmethod
    def get_simulation_events_count(
        db: Session,
        simulation_id: str,
    ) -> int:
        """
        Get count of events for a simulation.
        
        Args:
            db: Database session
            simulation_id: Simulation identifier
            
        Returns:
            Count of events
        """
        return (
            db.query(SimulationEvent)
            .filter(SimulationEvent.simulation_id == simulation_id)
            .count()
        )
    
    @staticmethod
    def delete_simulation_event(db: Session, event_id: int) -> bool:
        """
        Delete a simulation event by ID.
        
        Args:
            db: Database session
            event_id: Event ID
            
        Returns:
            True if deleted, False if not found
        """
        event = db.query(SimulationEvent).filter(SimulationEvent.id == event_id).first()
        if event:
            db.delete(event)
            db.commit()
            return True
        return False
    
    @staticmethod
    def delete_simulation_events_by_simulation_id(
        db: Session,
        simulation_id: str,
    ) -> int:
        """
        Delete all events for a simulation.
        
        Args:
            db: Database session
            simulation_id: Simulation identifier
            
        Returns:
            Count of deleted records
        """
        count = (
            db.query(SimulationEvent)
            .filter(SimulationEvent.simulation_id == simulation_id)
            .delete()
        )
        db.commit()
        return count
    
    # ====================================================================
    # RetrainingHistory Operations
    # ====================================================================
    
    @staticmethod
    def create_retraining_record(
        db: Session,
        simulation_id: str,
        drift_score: float,
        event_count: int = 0,
        accuracy_before: Optional[float] = None,
        accuracy_after: Optional[float] = None,
        improvement_percent: Optional[float] = None,
        status: str = "pending",
        notes: Optional[str] = None,
    ) -> RetrainingHistory:
        """
        Create a new retraining history record.
        
        Args:
            db: Database session
            simulation_id: Simulation identifier
            drift_score: Drift score that triggered retraining
            event_count: Number of events used
            accuracy_before: Accuracy before retraining
            accuracy_after: Accuracy after retraining
            improvement_percent: Improvement percentage
            status: Retraining status
            notes: Additional notes
            
        Returns:
            Created RetrainingHistory instance
        """
        record = RetrainingHistory(
            simulation_id=simulation_id,
            drift_score=drift_score,
            event_count=event_count,
            accuracy_before=accuracy_before,
            accuracy_after=accuracy_after,
            improvement_percent=improvement_percent,
            status=status,
            notes=notes,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record
    
    @staticmethod
    def get_retraining_record(db: Session, record_id: int) -> Optional[RetrainingHistory]:
        """
        Get a retraining record by ID.
        
        Args:
            db: Database session
            record_id: Record ID
            
        Returns:
            RetrainingHistory or None if not found
        """
        return db.query(RetrainingHistory).filter(RetrainingHistory.id == record_id).first()
    
    @staticmethod
    def get_retraining_records_by_simulation_id(
        db: Session,
        simulation_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[RetrainingHistory]:
        """
        Get retraining records for a simulation.
        
        Args:
            db: Database session
            simulation_id: Simulation identifier
            limit: Maximum records to return
            offset: Record offset for pagination
            
        Returns:
            List of RetrainingHistory records
        """
        return (
            db.query(RetrainingHistory)
            .filter(RetrainingHistory.simulation_id == simulation_id)
            .order_by(desc(RetrainingHistory.created_at))
            .limit(limit)
            .offset(offset)
            .all()
        )
    
    @staticmethod
    def update_retraining_record(
        db: Session,
        record_id: int,
        **kwargs
    ) -> Optional[RetrainingHistory]:
        """
        Update a retraining record.
        
        Args:
            db: Database session
            record_id: Record ID
            **kwargs: Fields to update
            
        Returns:
            Updated RetrainingHistory or None if not found
        """
        record = db.query(RetrainingHistory).filter(RetrainingHistory.id == record_id).first()
        if record:
            for key, value in kwargs.items():
                if hasattr(record, key):
                    setattr(record, key, value)
            db.commit()
            db.refresh(record)
        return record
    
    @staticmethod
    def delete_retraining_record(db: Session, record_id: int) -> bool:
        """
        Delete a retraining record.
        
        Args:
            db: Database session
            record_id: Record ID
            
        Returns:
            True if deleted, False if not found
        """
        record = db.query(RetrainingHistory).filter(RetrainingHistory.id == record_id).first()
        if record:
            db.delete(record)
            db.commit()
            return True
        return False
    
    # ====================================================================
    # DriftAnalysisHistory Operations
    # ====================================================================
    
    @staticmethod
    def create_drift_analysis_record(
        db: Session,
        simulation_id: str,
        drift_score: float,
        analysis_timestamp: datetime,
        distribution_divergence: Optional[float] = None,
        temporal_divergence: Optional[float] = None,
        sequence_divergence: Optional[float] = None,
        major_changes: Optional[Dict[str, Any]] = None,
    ) -> DriftAnalysisHistory:
        """
        Create a new drift analysis record.
        
        Args:
            db: Database session
            simulation_id: Simulation identifier
            drift_score: Overall drift score
            analysis_timestamp: When analysis was performed
            distribution_divergence: Distribution divergence score
            temporal_divergence: Temporal divergence score
            sequence_divergence: Sequence divergence score
            major_changes: JSON details of major changes
            
        Returns:
            Created DriftAnalysisHistory instance
        """
        record = DriftAnalysisHistory(
            simulation_id=simulation_id,
            drift_score=drift_score,
            distribution_divergence=distribution_divergence,
            temporal_divergence=temporal_divergence,
            sequence_divergence=sequence_divergence,
            major_changes=major_changes,
            analysis_timestamp=analysis_timestamp,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record
    
    @staticmethod
    def get_drift_analysis_record(
        db: Session,
        record_id: int,
    ) -> Optional[DriftAnalysisHistory]:
        """
        Get a drift analysis record by ID.
        
        Args:
            db: Database session
            record_id: Record ID
            
        Returns:
            DriftAnalysisHistory or None if not found
        """
        return (
            db.query(DriftAnalysisHistory)
            .filter(DriftAnalysisHistory.id == record_id)
            .first()
        )
    
    @staticmethod
    def get_drift_analysis_records_by_simulation_id(
        db: Session,
        simulation_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[DriftAnalysisHistory]:
        """
        Get drift analysis records for a simulation.
        
        Args:
            db: Database session
            simulation_id: Simulation identifier
            limit: Maximum records to return
            offset: Record offset for pagination
            
        Returns:
            List of DriftAnalysisHistory records
        """
        return (
            db.query(DriftAnalysisHistory)
            .filter(DriftAnalysisHistory.simulation_id == simulation_id)
            .order_by(desc(DriftAnalysisHistory.analysis_timestamp))
            .limit(limit)
            .offset(offset)
            .all()
        )
    
    @staticmethod
    def get_latest_drift_analysis(
        db: Session,
        simulation_id: str,
    ) -> Optional[DriftAnalysisHistory]:
        """
        Get the most recent drift analysis for a simulation.
        
        Args:
            db: Database session
            simulation_id: Simulation identifier
            
        Returns:
            Most recent DriftAnalysisHistory or None
        """
        return (
            db.query(DriftAnalysisHistory)
            .filter(DriftAnalysisHistory.simulation_id == simulation_id)
            .order_by(desc(DriftAnalysisHistory.analysis_timestamp))
            .first()
        )
    
    @staticmethod
    def delete_drift_analysis_record(db: Session, record_id: int) -> bool:
        """
        Delete a drift analysis record.
        
        Args:
            db: Database session
            record_id: Record ID
            
        Returns:
            True if deleted, False if not found
        """
        record = (
            db.query(DriftAnalysisHistory)
            .filter(DriftAnalysisHistory.id == record_id)
            .first()
        )
        if record:
            db.delete(record)
            db.commit()
            return True
        return False
