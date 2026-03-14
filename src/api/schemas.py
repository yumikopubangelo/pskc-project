# ============================================================
# PSKC — API Schemas
# Pydantic schemas for request/response
# ============================================================
from typing import Optional, List, Dict, Any, Any
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime

SAFE_IDENTIFIER_PATTERN = r"^[A-Za-z0-9._-]+$"


# === Request Schemas ===

class KeyAccessRequest(BaseModel):
    """Request to access a key"""
    key_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        pattern=SAFE_IDENTIFIER_PATTERN,
        description="Key identifier",
    )
    service_id: str = Field(
        default="default",
        min_length=1,
        max_length=64,
        pattern=SAFE_IDENTIFIER_PATTERN,
        description="Service requesting the key",
    )
    verify: bool = Field(default=True, description="Verify key after fetching")


class KeyStoreRequest(BaseModel):
    """Request to store a key in cache"""
    key_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        pattern=SAFE_IDENTIFIER_PATTERN,
        description="Key identifier",
    )
    key_data: str = Field(..., description="Key data (base64 encoded)")
    service_id: str = Field(
        default="default",
        min_length=1,
        max_length=64,
        pattern=SAFE_IDENTIFIER_PATTERN,
        description="Service storing the key",
    )
    ttl: Optional[int] = Field(default=None, ge=1, le=604800, description="Time-to-live in seconds")


class PredictionRequest(BaseModel):
    """Request for key predictions"""
    service_id: str = Field(
        default="default",
        min_length=1,
        max_length=64,
        pattern=SAFE_IDENTIFIER_PATTERN,
        description="Service to predict for",
    )
    n: int = Field(default=10, ge=1, le=100, description="Number of predictions")


class PrefetchRequest(BaseModel):
    """Request to prefetch predicted keys"""
    service_id: str = Field(
        default="default",
        min_length=1,
        max_length=64,
        pattern=SAFE_IDENTIFIER_PATTERN,
        description="Service to prefetch for",
    )
    n: int = Field(default=10, ge=1, le=50, description="Number of keys to prefetch")


class TrainingRequest(BaseModel):
    """Request to train the model"""
    force: bool = Field(default=False, description="Force training even with insufficient samples")


class ModelPromotionRequest(BaseModel):
    """Promote a registered model version to a target stage."""

    model_config = ConfigDict(protected_namespaces=())

    model_name: str = Field(
        default="pskc_model",
        min_length=1,
        max_length=128,
        pattern=SAFE_IDENTIFIER_PATTERN,
        description="Logical model name in the registry",
    )
    version: str = Field(
        ...,
        min_length=1,
        max_length=128,
        pattern=SAFE_IDENTIFIER_PATTERN,
        description="Version to promote",
    )
    target_stage: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=SAFE_IDENTIFIER_PATTERN,
        description="Target lifecycle stage, for example staging or production",
    )
    actor: str = Field(
        default="api",
        min_length=1,
        max_length=64,
        pattern=SAFE_IDENTIFIER_PATTERN,
        description="Actor recorded in lifecycle history",
    )
    notes: Optional[str] = Field(default="", max_length=256, description="Optional promotion note")
    make_active: bool = Field(default=True, description="Set promoted version as active runtime version")


class ModelRollbackRequest(BaseModel):
    """Rollback the active version to another registered version."""

    model_config = ConfigDict(protected_namespaces=())

    model_name: str = Field(
        default="pskc_model",
        min_length=1,
        max_length=128,
        pattern=SAFE_IDENTIFIER_PATTERN,
        description="Logical model name in the registry",
    )
    version: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=SAFE_IDENTIFIER_PATTERN,
        description="Optional explicit version to roll back to. If omitted, the previous version is selected.",
    )
    actor: str = Field(
        default="api",
        min_length=1,
        max_length=64,
        pattern=SAFE_IDENTIFIER_PATTERN,
        description="Actor recorded in lifecycle history",
    )
    notes: Optional[str] = Field(default="", max_length=256, description="Optional rollback note")


# === Response Schemas ===

class KeyAccessResponse(BaseModel):
    """Response for key access"""
    success: bool
    key_id: str
    cache_hit: bool
    latency_ms: float
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class KeyStoreResponse(BaseModel):
    """Response for key storage"""
    success: bool
    key_id: str
    service_id: str
    ttl: Optional[int] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class PredictionResponse(BaseModel):
    """Response for predictions"""
    predictions: List[Dict[str, Any]]
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class PrefetchResponse(BaseModel):
    """Response for prefetch"""
    prefetched_count: int
    keys: List[str]
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class TrainingResponse(BaseModel):
    """Response for training"""
    success: bool
    message: str
    sample_count: Optional[int] = None
    training_time: Optional[float] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class CacheStatsResponse(BaseModel):
    """Response for cache statistics"""
    size: int
    max_size: int
    hits: int
    misses: int
    hit_rate: float
    total_requests: int


class MLStatsResponse(BaseModel):
    """Response for ML statistics"""
    collector_stats: Dict[str, Any]
    prediction_stats: Dict[str, Any]
    training_count: int
    last_train_time: Optional[float] = None


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    version: str = "1.0.0"
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    services: Dict[str, str] = Field(default_factory=dict)


class ReadinessResponse(BaseModel):
    """Readiness check response - verifies all dependencies are available"""
    ready: bool
    status: str
    version: str = "1.0.0"
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    dependencies: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    # fail_open: dependency failure doesn't block startup (e.g., Redis optional for read-heavy)
    # fail_closed: dependency failure blocks startup (e.g., FIPS module required)


class StartupResponse(BaseModel):
    """Startup check response - Kubernetes-style startup probe"""
    started: bool
    status: str
    version: str = "1.0.0"
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    progress: Optional[str] = None
    error: Optional[str] = None


class MetricsResponse(BaseModel):
    """Response for system metrics"""
    cache_hits: int
    cache_misses: int
    cache_hit_rate: float
    total_requests: int
    avg_latency_ms: float
    active_keys: int
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class SimulationRequest(BaseModel):
    """Request to run simulation"""
    scenario: str = Field(default="spotify", description="Simulation scenario name")
    profile_id: Optional[str] = Field(default=None, description="Simulation profile identifier")
    request_count: int = Field(default=1000, ge=50, le=10000, description="Number of requests to simulate")
    seed: Optional[int] = Field(default=None, description="Optional seed for deterministic simulation runs")
    duration_seconds: int = Field(default=60, ge=10, le=3600, description="Simulation duration")
    traffic_rate: float = Field(default=100.0, description="Requests per second")


class SimulationResponse(BaseModel):
    """Response for simulation"""
    simulation_id: str
    status: str
    scenario: str
    profile_id: Optional[str] = None
    request_count: Optional[int] = None
    duration_seconds: int
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class SimulationResultResponse(BaseModel):
    """Response for simulation results"""
    simulation_id: str
    status: str
    results: Dict[str, Any]
    metrics: Dict[str, Any]
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class SecurityAuditResponse(BaseModel):
    """Response for security audit"""
    audit_events: List[Dict[str, Any]]
    total_count: int
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class IntrusionLogResponse(BaseModel):
    """Response for intrusion logs"""
    intrusions: List[Dict[str, Any]]
    total_count: int
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class ErrorResponse(BaseModel):
    """Error response"""
    error: str
    detail: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# === Internal Schemas ===

class AuditEventResponse(BaseModel):
    """Audit event for logging"""
    event_type: str
    key_id: Optional[str] = None
    service_id: Optional[str] = None
    timestamp: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ============================================================
# Pipeline Builder Schemas
# ============================================================

class PipelineNodeSchema(BaseModel):
    """Schema for a pipeline node"""
    id: str
    type: str
    x: float
    y: float
    params: Dict[str, Any] = Field(default_factory=dict)


class PipelineConnectionSchema(BaseModel):
    """Schema for a pipeline connection"""
    from_node: str = Field(..., alias="from")
    to_node: str = Field(..., alias="to")

    class Config:
        populate_by_name = True


class PipelineRequest(BaseModel):
    """Request to run a pipeline"""
    name: Optional[str] = Field(default=None, description="Pipeline name")
    nodes: List[Dict[str, Any]] = Field(..., description="List of pipeline nodes")
    connections: List[Dict[str, Any]] = Field(default_factory=list, description="List of node connections")


class PipelineResponse(BaseModel):
    """Response for pipeline operation"""
    pipeline_id: str
    status: str
    message: str
    progress: float
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class PipelineStatusResponse(BaseModel):
    """Response for pipeline status"""
    pipeline_id: str
    status: str
    progress: float
    metrics: Dict[str, Any] = Field(default_factory=dict)
    results: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: str
    completed_at: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
