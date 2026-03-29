# ============================================================
# PSKC — SQLAlchemy ORM Models
# ============================================================
"""SQLAlchemy ORM models for simulation learning data."""
from datetime import datetime
from typing import Optional, Any, Dict, List
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, JSON,
    Index, UniqueConstraint, ForeignKey, event
)
from sqlalchemy.orm import declarative_base, Session, relationship
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


class ModelVersion(Base):
    """
    Stores model versions and their metadata.
    
    Tracks different versions of ML models used in the system, supporting model lineage
    through parent_version_id and providing a unified metrics storage location.
    
    Attributes:
        version_id: Primary key and unique identifier for this model version
        model_name: Name of the model (indexed for filtering by model)
        version_number: Semantic version string (e.g., "1.0.0", "1.1.0")
        created_at: Timestamp when the version was created (indexed for time-based queries)
        status: Current status of the model (e.g., "active", "archived", "deprecated")
        parent_version_id: Optional reference to parent version for lineage tracking
        metrics_json: Optional JSON field for storing summary metrics
    """
    __tablename__ = "model_versions"
    
    version_id = Column(Integer, primary_key=True, index=True)
    model_name = Column(String(255), nullable=False, index=True)
    version_number = Column(String(50), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    status = Column(String(50), nullable=False, index=True)
    parent_version_id = Column(Integer, ForeignKey('model_versions.version_id', ondelete='SET NULL'), nullable=True)
    metrics_json = Column(JSON, nullable=True)
    
    # Relationships
    metrics = relationship('ModelMetric', back_populates='version', cascade='all, delete-orphan')
    training_metadata = relationship('TrainingMetadata', back_populates='version', uselist=False, cascade='all, delete-orphan')
    key_predictions = relationship('KeyPrediction', back_populates='version', cascade='all, delete-orphan')
    per_key_metrics = relationship('PerKeyMetric', back_populates='version', cascade='all, delete-orphan')
    parent = relationship('ModelVersion', remote_side=[version_id], backref='child_versions')
    
    __table_args__ = (
        Index('idx_model_versions_model_name_version_number', 'model_name', 'version_number'),
        Index('idx_model_versions_parent_version_id', 'parent_version_id'),
    )
    
    def __repr__(self) -> str:
        return f"<ModelVersion(version_id={self.version_id}, model_name='{self.model_name}', version_number='{self.version_number}', status='{self.status}')>"


class ModelMetric(Base):
    """
    Stores performance metrics for a specific model version.
    
    Captures individual metrics (accuracy, precision, recall, F1, etc.) for each
    model version, allowing tracking of metric evolution over time and model iterations.
    
    Attributes:
        id: Primary key
        version_id: Foreign key to ModelVersion
        metric_name: Name of the metric (e.g., "accuracy", "precision", "recall")
        metric_value: Numeric value of the metric
        recorded_at: Timestamp when the metric was recorded (indexed for time-based queries)
    """
    __tablename__ = "model_metrics"
    
    id = Column(Integer, primary_key=True, index=True)
    version_id = Column(Integer, ForeignKey('model_versions.version_id', ondelete='CASCADE'), nullable=False, index=True)
    metric_name = Column(String(255), nullable=False, index=True)
    metric_value = Column(Float, nullable=False)
    recorded_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    # Relationships
    version = relationship('ModelVersion', back_populates='metrics')

    __table_args__ = (
        Index('idx_model_metrics_version_id_metric_name', 'version_id', 'metric_name'),
    )
    
    def __repr__(self) -> str:
        return f"<ModelMetric(id={self.id}, version_id={self.version_id}, metric_name='{self.metric_name}', metric_value={self.metric_value})>"


class TrainingMetadata(Base):
    """
    Stores training session metadata for a model version.
    
    Records information about the training process for each model version, including
    training duration, sample count, and accuracy improvements before and after training.
    
    Attributes:
        id: Primary key
        version_id: Foreign key to ModelVersion
        training_start_time: When the training session started
        training_end_time: When the training session ended (nullable if still training)
        samples_count: Number of samples used in training
        accuracy_before: Model accuracy before training
        accuracy_after: Model accuracy after training
    """
    __tablename__ = "training_metadata"
    
    id = Column(Integer, primary_key=True, index=True)
    version_id = Column(Integer, ForeignKey('model_versions.version_id', ondelete='CASCADE'), nullable=False, index=True)
    training_start_time = Column(DateTime, nullable=False, index=True)
    training_end_time = Column(DateTime, nullable=True)
    samples_count = Column(Integer, nullable=False)
    accuracy_before = Column(Float, nullable=True)
    accuracy_after = Column(Float, nullable=True)
    
    # Relationships
    version = relationship('ModelVersion', back_populates='training_metadata')

    def __repr__(self) -> str:
        return f"<TrainingMetadata(id={self.id}, version_id={self.version_id}, samples_count={self.samples_count})>"


class KeyPrediction(Base):
    """
    Stores individual key predictions made by a model version.
    
    Captures detailed prediction data for specific cache keys, including predicted values,
    actual values, correctness, and confidence scores. Used for model evaluation and debugging.
    
    Attributes:
        id: Primary key
        version_id: Foreign key to ModelVersion
        key: Cache key being predicted (indexed for per-key analysis)
        predicted_value: The value predicted by the model
        actual_value: The actual value (nullable if not yet known)
        is_correct: Whether the prediction was correct (nullable if actual value unknown)
        confidence: Model confidence score for the prediction
        timestamp: When the prediction was made (indexed for time-based queries)
    """
    __tablename__ = "key_predictions"
    
    id = Column(Integer, primary_key=True, index=True)
    version_id = Column(Integer, ForeignKey('model_versions.version_id', ondelete='CASCADE'), nullable=False, index=True)
    key = Column(String(255), nullable=False, index=True)
    predicted_value = Column(String(500), nullable=False)
    actual_value = Column(String(500), nullable=True)
    is_correct = Column(Boolean, nullable=True, index=True)
    confidence = Column(Float, nullable=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    # Relationships
    version = relationship('ModelVersion', back_populates='key_predictions')

    __table_args__ = (
        Index('idx_key_predictions_version_id_key', 'version_id', 'key'),
    )
    
    def __repr__(self) -> str:
        return f"<KeyPrediction(id={self.id}, version_id={self.version_id}, key='{self.key}', is_correct={self.is_correct})>"


class PerKeyMetric(Base):
    """
    Stores aggregated metrics for individual cache keys across a model version.
    
    Provides per-key performance statistics (accuracy, drift score, cache hit rate),
    enabling identification of keys with performance issues or high drift.
    
    Attributes:
        id: Primary key
        version_id: Foreign key to ModelVersion
        key: Cache key identifier (indexed for per-key lookups)
        accuracy: Accuracy for predictions of this key
        drift_score: Detected drift score for this key
        cache_hit_rate: Proportion of cache hits for this key
        total_predictions: Total number of predictions for this key
        error_count: Number of incorrect predictions for this key
        hit_rate: Cache hit rate for this key
        avg_confidence: Average confidence for predictions of this key
        timestamp: When the metrics were recorded (indexed for time-based queries)
    """
    __tablename__ = "per_key_metrics"
    
    id = Column(Integer, primary_key=True, index=True)
    version_id = Column(Integer, ForeignKey('model_versions.version_id', ondelete='CASCADE'), nullable=False, index=True)
    key = Column(String(255), nullable=False, index=True)
    accuracy = Column(Float, nullable=True, default=0.0)
    drift_score = Column(Float, nullable=True, default=0.0)
    cache_hit_rate = Column(Float, nullable=True, default=0.0)
    hit_rate = Column(Float, nullable=True, default=0.0)
    total_predictions = Column(Integer, nullable=True, default=0)
    error_count = Column(Integer, nullable=True, default=0)
    avg_confidence = Column(Float, nullable=True, default=0.0)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    # Relationships
    version = relationship('ModelVersion', back_populates='per_key_metrics')
    
    __table_args__ = (
        Index('idx_per_key_metrics_version_id_key', 'version_id', 'key'),
        Index('idx_per_key_metrics_timestamp', 'timestamp'),
    )
    
    def __repr__(self) -> str:
        return f"<PerKeyMetric(id={self.id}, version_id={self.version_id}, key='{self.key}', accuracy={self.accuracy})>"


class PredictionLog(Base):
    """
    Stores detailed logs of all predictions made by model versions.
    
    Records every prediction for auditing, analysis, and model evaluation purposes.
    Enables calculation of per-key metrics and drift detection.
    
    Attributes:
        id: Primary key
        version_id: Foreign key to ModelVersion
        key: Cache key being predicted
        predicted_value: The value predicted by the model
        actual_value: The actual value (for comparing accuracy)
        confidence: Model confidence score (0-1)
        is_correct: Whether the prediction matched actual value
        latency_ms: Latency in milliseconds for this prediction
        timestamp: When the prediction was made (indexed for time-based queries)
    """
    __tablename__ = "prediction_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    version_id = Column(Integer, ForeignKey('model_versions.version_id', ondelete='CASCADE'), nullable=False, index=True)
    key = Column(String(255), nullable=False, index=True)
    predicted_value = Column(String(500), nullable=False)
    actual_value = Column(String(500), nullable=True)
    confidence = Column(Float, nullable=True, default=0.0)
    is_correct = Column(Boolean, nullable=True)
    latency_ms = Column(Float, nullable=True, default=0.0)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    # Relationships
    version = relationship('ModelVersion', foreign_keys=[version_id])
    
    __table_args__ = (
        Index('idx_prediction_logs_version_id', 'version_id'),
        Index('idx_prediction_logs_key', 'key'),
        Index('idx_prediction_logs_timestamp', 'timestamp'),
        Index('idx_prediction_logs_version_key_timestamp', 'version_id', 'key', 'timestamp'),
    )
    
    def __repr__(self) -> str:
        return f"<PredictionLog(id={self.id}, version_id={self.version_id}, key='{self.key}', confidence={self.confidence})>"


class TrainingSampleProfile(Base):
    """
    Stores statistical metadata (fingerprint) of the training dataset
    used for a model version.  Not raw data — only aggregated distributions,
    frequencies, and feature statistics.

    Used by the TrafficPatternTracker to compare live traffic patterns
    against the training baseline for concept-drift / pattern-divergence
    detection.

    Attributes:
        id: Primary key
        version_id: FK → ModelVersion this profile belongs to
        total_samples: Number of samples in the training set
        unique_keys: Number of distinct cache keys
        unique_services: Number of distinct service IDs
        temporal_profile: JSON – per-hour access histogram (24 buckets)
        key_frequency_profile: JSON – top-50 keys and their counts
        service_distribution: JSON – service → proportion mapping
        cache_hit_rate: Overall cache-hit rate of the dataset
        avg_latency_ms: Mean latency across the dataset
        latency_p95_ms: 95th-percentile latency
        feature_stats: JSON – per-RF-feature mean & std
        created_at: When the profile was created
    """
    __tablename__ = "training_sample_profiles"

    id = Column(Integer, primary_key=True, index=True)
    version_id = Column(
        Integer,
        ForeignKey('model_versions.version_id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    total_samples = Column(Integer, nullable=False, default=0)
    unique_keys = Column(Integer, nullable=False, default=0)
    unique_services = Column(Integer, nullable=False, default=0)
    temporal_profile = Column(JSON, nullable=True)
    key_frequency_profile = Column(JSON, nullable=True)
    service_distribution = Column(JSON, nullable=True)
    cache_hit_rate = Column(Float, nullable=True, default=0.0)
    avg_latency_ms = Column(Float, nullable=True, default=0.0)
    latency_p95_ms = Column(Float, nullable=True, default=0.0)
    feature_stats = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    # Relationships
    version = relationship('ModelVersion', foreign_keys=[version_id])

    __table_args__ = (
        Index('idx_tsp_version_id', 'version_id'),
        Index('idx_tsp_created_at', 'created_at'),
    )

    def __repr__(self) -> str:
        return (
            f"<TrainingSampleProfile(id={self.id}, version_id={self.version_id}, "
            f"total_samples={self.total_samples}, unique_keys={self.unique_keys})>"
        )


# ============================================================
# Database Session Management
# ============================================================

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

def get_database_session():
    """
    Create database engine and session factory.
    
    This function is called once on application startup to initialize
    the database connection pool and session factory.
    """
    # Import settings here to avoid circular imports
    from config.settings import settings
    
    # Create engine with connection pooling
    engine = create_engine(
        settings.database_url,
        poolclass=NullPool,  # Use NullPool for SQLite (no connection pooling)
        echo=False,
        future=True
    )
    
    # Create all tables
    Base.metadata.create_all(bind=engine)
    
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Session:
    """
    Dependency injection function for FastAPI.
    
    Provides a database session for each request. Used as a dependency
    in FastAPI route handlers.
    
    Usage in routes:
        @router.get("/example")
        def example_route(db: Session = Depends(get_session)):
            ...
    """
    # Import here to avoid circular imports and ensure settings are loaded
    from config.settings import settings
    from sqlalchemy.orm import sessionmaker
    
    engine = create_engine(
        settings.database_url,
        poolclass=NullPool,
        echo=False,
        future=True
    )
    
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    db = SessionLocal()
    
    try:
        yield db
    finally:
        db.close()

