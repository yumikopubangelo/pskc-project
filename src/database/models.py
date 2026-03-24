# ============================================================
# PSKC — SQLAlchemy ORM Models
# ============================================================
"""SQLAlchemy ORM models for simulation learning data."""
from datetime import datetime
from typing import Optional, Any, Dict
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, JSON,
    Index, UniqueConstraint, ForeignKey, event
)
from sqlalchemy.orm import declarative_base, Session
from sqlalchemy.pool import NullPool

Base = declarative_base()


class SimulationEvent(Base):
    """
    Stores individual simulation events for learning.
    
    Attributes:
        id: Primary key
        simulation_id: Identifier for the simulation run (indexed for quick lookup)
        timestamp: When the event occurred (indexed for time-range queries)
        key_id: Cache key identifier
        service_id: Service that generated the event
        latency_ms: Latency in milliseconds
        cache_hit: Whether the cache was hit
        features: JSON features extracted from the event
        created_at: When the record was created (indexed for maintenance)
    """
    __tablename__ = "simulation_events"
    
    id = Column(Integer, primary_key=True, index=True)
    simulation_id = Column(String(255), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    key_id = Column(String(255), nullable=False)
    service_id = Column(String(255), nullable=False)
    latency_ms = Column(Float, nullable=False)
    cache_hit = Column(Boolean, nullable=False, default=False)
    features = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    __table_args__ = (
        Index('idx_sim_events_sim_id_timestamp', 'simulation_id', 'timestamp'),
        Index('idx_sim_events_created_at', 'created_at'),
    )


class RetrainingHistory(Base):
    """
    Tracks retraining events and their outcomes.
    
    Attributes:
        id: Primary key
        simulation_id: Identifier for the simulation run (indexed for quick lookup)
        drift_score: Detected drift score that triggered retraining
        event_count: Number of events used in retraining
        accuracy_before: Model accuracy before retraining
        accuracy_after: Model accuracy after retraining
        improvement_percent: Percentage improvement in accuracy
        status: Retraining status (pending, running, completed, failed)
        notes: Additional notes about the retraining run
        retraining_started_at: When retraining started
        retraining_completed_at: When retraining completed
        created_at: When the record was created (indexed for maintenance)
    """
    __tablename__ = "retraining_history"
    
    id = Column(Integer, primary_key=True, index=True)
    simulation_id = Column(String(255), nullable=False, index=True)
    drift_score = Column(Float, nullable=False)
    event_count = Column(Integer, nullable=False, default=0)
    accuracy_before = Column(Float, nullable=True)
    accuracy_after = Column(Float, nullable=True)
    improvement_percent = Column(Float, nullable=True)
    status = Column(String(50), nullable=False, default="pending")
    notes = Column(String(1000), nullable=True)
    retraining_started_at = Column(DateTime, nullable=True)
    retraining_completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    __table_args__ = (
        Index('idx_retrain_sim_id', 'simulation_id'),
        Index('idx_retrain_created_at', 'created_at'),
    )


class DriftAnalysisHistory(Base):
    """
    Tracks drift analysis results and trend detection.
    
    Attributes:
        id: Primary key
        simulation_id: Identifier for the simulation run (indexed for quick lookup)
        drift_score: Overall drift score
        distribution_divergence: Divergence in data distribution
        temporal_divergence: Divergence in temporal patterns
        sequence_divergence: Divergence in sequence patterns
        major_changes: JSON details of major detected changes
        analysis_timestamp: When the analysis was performed
        created_at: When the record was created (indexed for maintenance)
    """
    __tablename__ = "drift_analysis_history"
    
    id = Column(Integer, primary_key=True, index=True)
    simulation_id = Column(String(255), nullable=False, index=True)
    drift_score = Column(Float, nullable=False)
    distribution_divergence = Column(Float, nullable=True)
    temporal_divergence = Column(Float, nullable=True)
    sequence_divergence = Column(Float, nullable=True)
    major_changes = Column(JSON, nullable=True)
    analysis_timestamp = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    __table_args__ = (
        Index('idx_drift_sim_id', 'simulation_id'),
        Index('idx_drift_created_at', 'created_at'),
    )
