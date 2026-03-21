# ============================================================
# PSKC — Global Configuration Settings
# ============================================================
import os
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Application-level settings"""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # App
    app_env: str = Field(default="development", alias="APP_ENV")
    app_port: int = Field(default=8000, alias="APP_PORT")
    log_level: str = Field(default="debug", alias="LOG_LEVEL")
    secret_key: str = Field(default="", alias="SECRET_KEY")
    trusted_proxies: str = Field(default="", alias="TRUSTED_PROXIES")
    audit_log_directory: str = Field(default="/app/logs", alias="AUDIT_LOG_DIRECTORY")
    
    # HTTP Security
    fips_self_test_enabled: bool = Field(default=True, alias="FIPS_SELF_TEST_ENABLED")
    http_security_enabled: bool = Field(default=True, alias="HTTP_SECURITY_ENABLED")
    http_security_block_sensitive_from_external: bool = Field(
        default=False,
        alias="HTTP_SECURITY_BLOCK_SENSITIVE_FROM_EXTERNAL",
    )
    http_security_max_request_body_bytes: int = Field(
        default=10 * 1024 * 1024,
        alias="HTTP_SECURITY_MAX_REQUEST_BODY_BYTES",
    )
    http_rate_limit_enabled: bool = Field(default=True, alias="HTTP_RATE_LIMIT_ENABLED")
    http_rate_limit_max_requests: int = Field(default=300, alias="HTTP_RATE_LIMIT_MAX_REQUESTS")
    http_rate_limit_window_seconds: int = Field(default=60, alias="HTTP_RATE_LIMIT_WINDOW_SECONDS")
    http_rate_limit_burst_max: int = Field(default=60, alias="HTTP_RATE_LIMIT_BURST_MAX")
    http_rate_limit_burst_window_seconds: int = Field(
        default=5,
        alias="HTTP_RATE_LIMIT_BURST_WINDOW_SECONDS",
    )
    http_rate_limit_whitelist_private_ips: bool = Field(
        default=True,
        alias="HTTP_RATE_LIMIT_WHITELIST_PRIVATE_IPS",
    )
    
    # Redis
    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_db: int = Field(default=0, alias="REDIS_DB")
    redis_password: str = Field(default="", alias="REDIS_PASSWORD")
    redis_socket_connect_timeout_seconds: float = Field(
        default=0.5,
        alias="REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS",
    )
    redis_socket_timeout_seconds: float = Field(
        default=10.0,
        alias="REDIS_SOCKET_TIMEOUT_SECONDS",
    )
    redis_failure_backoff_seconds: float = Field(
        default=30.0,
        alias="REDIS_FAILURE_BACKOFF_SECONDS",
    )
    redis_cache_prefix: str = Field(default="pskc:cache", alias="REDIS_CACHE_PREFIX")
    prefetch_queue_key: str = Field(default="pskc:prefetch:jobs", alias="PREFETCH_QUEUE_KEY")
    prefetch_worker_block_timeout: int = Field(default=5, alias="PREFETCH_WORKER_BLOCK_TIMEOUT")
    prefetch_max_retries: int = Field(default=3, alias="PREFETCH_MAX_RETRIES")
    prefetch_retry_backoff_seconds: int = Field(default=5, alias="PREFETCH_RETRY_BACKOFF_SECONDS")
    
    # Cache Settings (PSKC Core)
    cache_ttl_seconds: int = Field(default=300, alias="CACHE_TTL_SECONDS")  # 5 minutes - AWS KMS recommendation
    cache_max_size: int = Field(default=10000, alias="CACHE_MAX_SIZE")
    cache_encryption_key: str = Field(default="", alias="CACHE_ENCRYPTION_KEY")
    
    # ML Model Settings
    ml_model_path: str = Field(default="data/models/pskc_model.pt", alias="ML_MODEL_PATH")
    ml_model_name: str = Field(default="pskc_model", alias="ML_MODEL_NAME")
    ml_model_registry_dir: str = Field(default="data/models", alias="ML_MODEL_REGISTRY_DIR")
    ml_model_stage: str = Field(default="development", alias="ML_MODEL_STAGE")
    ml_model_signing_key: str = Field(default="", alias="ML_MODEL_SIGNING_KEY")
    ml_prediction_threshold: float = Field(default=0.75, alias="ML_PREDICTION_THRESHOLD")
    ml_update_interval_seconds: int = Field(default=30, alias="ML_UPDATE_INTERVAL_SECONDS")
    ml_top_n_predictions: int = Field(default=10, alias="ML_TOP_N_PREDICTIONS")
    ml_min_accuracy_for_version_bump: float = Field(
        default=0.01,
        alias="ML_MIN_ACCURACY_FOR_VERSION_BUMP",
    )
    ml_min_sample_delta_for_version_bump: int = Field(
        default=250,
        alias="ML_MIN_SAMPLE_DELTA_FOR_VERSION_BUMP",
    )
    
    # ============================================================
    # ML Hyperparameter Configuration (LSTM, RF, Markov, Ensemble)
    # ============================================================
    
    # LSTM Settings
    ml_lstm_input_size: int = Field(default=30, alias="ML_LSTM_INPUT_SIZE")
    ml_lstm_hidden_size: int = Field(default=64, alias="ML_LSTM_HIDDEN_SIZE")
    ml_lstm_num_layers: int = Field(default=2, alias="ML_LSTM_NUM_LAYERS")
    ml_lstm_dropout: float = Field(default=0.2, alias="ML_LSTM_DROPOUT")
    ml_lstm_learning_rate: float = Field(default=0.001, alias="ML_LSTM_LEARNING_RATE")
    ml_lstm_batch_size: int = Field(default=32, alias="ML_LSTM_BATCH_SIZE")
    ml_lstm_max_epochs: int = Field(default=50, alias="ML_LSTM_MAX_EPOCHS")
    ml_lstm_early_stopping_patience: int = Field(default=5, alias="ML_LSTM_EARLY_STOPPING_PATIENCE")
    ml_lstm_early_stopping_min_delta: float = Field(default=0.001, alias="ML_LSTM_EARLY_STOPPING_MIN_DELTA")
    ml_lstm_use_lr_scheduler: bool = Field(default=True, alias="ML_LSTM_USE_LR_SCHEDULER")
    ml_lstm_lr_scheduler_factor: float = Field(default=0.5, alias="ML_LSTM_LR_SCHEDULER_FACTOR")
    ml_lstm_lr_scheduler_patience: int = Field(default=3, alias="ML_LSTM_LR_SCHEDULER_PATIENCE")
    
    # Random Forest Settings
    ml_rf_n_estimators: int = Field(default=100, alias="ML_RF_N_ESTIMATORS")
    ml_rf_max_depth: int = Field(default=10, alias="ML_RF_MAX_DEPTH")
    ml_rf_min_samples_split: int = Field(default=2, alias="ML_RF_MIN_SAMPLES_SPLIT")
    ml_rf_min_samples_leaf: int = Field(default=1, alias="ML_RF_MIN_SAMPLES_LEAF")
    ml_rf_use_class_weight: bool = Field(default=True, alias="ML_RF_USE_CLASS_WEIGHT")
    ml_rf_random_state: int = Field(default=42, alias="ML_RF_RANDOM_STATE")
    ml_rf_n_jobs: int = Field(default=-1, alias="ML_RF_N_JOBS")
    
    # Markov Chain Settings
    ml_markov_max_history: int = Field(default=10000, alias="ML_MARKOV_MAX_HISTORY")
    ml_markov_smoothing: float = Field(default=0.1, alias="ML_MARKOV_SMOOTHING")
    ml_markov_max_transitions: int = Field(default=100000, alias="ML_MARKOV_MAX_TRANSITIONS")
    
    # Ensemble Settings
    ml_ensemble_lstm_weight: float = Field(default=0.5, alias="ML_ENSEMBLE_LSTM_WEIGHT")
    ml_ensemble_rf_weight: float = Field(default=0.35, alias="ML_ENSEMBLE_RF_WEIGHT")
    ml_ensemble_markov_weight: float = Field(default=0.15, alias="ML_ENSEMBLE_MARKOV_WEIGHT")
    ml_ensemble_dynamic_weights: bool = Field(default=True, alias="ML_ENSEMBLE_DYNAMIC_WEIGHTS")
    ml_ensemble_window_size: int = Field(default=200, alias="ML_ENSEMBLE_WINDOW_SIZE")
    ml_ensemble_update_every: int = Field(default=50, alias="ML_ENSEMBLE_UPDATE_EVERY")
    ml_ensemble_temperature: float = Field(default=3.0, alias="ML_ENSEMBLE_TEMPERATURE")
    ml_ensemble_min_weight: float = Field(default=0.05, alias="ML_ENSEMBLE_MIN_WEIGHT")
    
    # Data Collector Settings
    ml_collector_max_events: int = Field(default=100000, alias="ML_COLLECTOR_MAX_EVENTS")
    ml_collector_window_seconds: int = Field(default=3600, alias="ML_COLLECTOR_WINDOW_SECONDS")
    ml_collector_historical_stats_ttl_hours: int = Field(default=168, alias="ML_COLLECTOR_HISTORICAL_STATS_TTL_HOURS")
    ml_collector_historical_stats_max_entries: int = Field(default=100000, alias="ML_COLLECTOR_HISTORICAL_STATS_MAX_ENTRIES")
    
    # Feature Engineering Settings
    ml_feature_context_window: int = Field(default=10, alias="ML_FEATURE_CONTEXT_WINDOW")
    ml_feature_burst_threshold_seconds: float = Field(default=1.0, alias="ML_FEATURE_BURST_THRESHOLD_SECONDS")
    ml_feature_regular_min_seconds: float = Field(default=10.0, alias="ML_FEATURE_REGULAR_MIN_SECONDS")
    ml_feature_regular_max_seconds: float = Field(default=60.0, alias="ML_FEATURE_REGULAR_MAX_SECONDS")
    ml_feature_recent_window_seconds: int = Field(default=3600, alias="ML_FEATURE_RECENT_WINDOW_SECONDS")
    ml_feature_expected_size: int = Field(default=30, alias="ML_FEATURE_EXPECTED_SIZE")
    
    # Predictor Settings
    ml_predictor_cache_ttl_seconds: int = Field(default=10, alias="ML_PREDICTOR_CACHE_TTL_SECONDS")
    ml_predictor_cache_max_size: int = Field(default=10000, alias="ML_PREDICTOR_CACHE_MAX_SIZE")
    ml_predictor_top_n: int = Field(default=10, alias="ML_PREDICTOR_TOP_N")
    ml_predictor_confidence_threshold: float = Field(default=0.75, alias="ML_PREDICTOR_CONFIDENCE_THRESHOLD")
    
    # Simulation Mode
    simulation_mode: bool = Field(default=False, alias="SIMULATION_MODE")
    simulation_scenario: str = Field(default="all", alias="SIMULATION_SCENARIO")
    
    # Monitoring
    grafana_password: str = Field(default="", alias="GRAFANA_PASSWORD")
    
    # Derived properties
    @property
    def redis_url(self) -> str:
        """Build Redis connection URL"""
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def trusted_proxy_networks(self) -> list[str]:
        """Return trusted proxy CIDRs from TRUSTED_PROXIES."""
        return [
            entry.strip()
            for entry in self.trusted_proxies.split(",")
            if entry.strip()
        ]

    @property
    def effective_ml_model_registry_dir(self) -> str:
        if self.ml_model_registry_dir:
            return self.ml_model_registry_dir

        model_dir = os.path.dirname(self.ml_model_path)
        return model_dir or "data/models"
    
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"
    
    @property
    def is_development(self) -> bool:
        return self.app_env == "development"
    
    # ============================================================
    # Endpoint Access Control Configuration
    # ============================================================
    
    @property
    def public_endpoints(self) -> set[str]:
        """Endpoints that can be accessed publicly (no authentication required)"""
        return {
            "/health",
            "/health/ready",
            "/health/startup",
            "/metrics",
            "/metrics/prometheus",
        }
    
    @property
    def operational_endpoints(self) -> set[str]:
        """Operational endpoints - metrics, monitoring, queue inspection"""
        return {
            "/metrics",
            "/metrics/prometheus",
            "/metrics/latency",
            "/metrics/cache-distribution",
            "/metrics/accuracy",
            "/metrics/prefetch",
            "/cache/stats",
            "/cache/keys",
            "/prefetch/dlq",
            "/ml/status",
            "/ml/registry",
            "/ml/lifecycle",
        }
    
    @property
    def admin_endpoints(self) -> set[str]:
        """Admin endpoints - require restricted access"""
        return {
            "/admin",
            "/internal",
            "/security/audit",
            "/security/intrusions",
            "/cache/invalidate",
            "/ml/promote",
            "/ml/rollback",
            "/ml/retrain",
        }
    
    @property
    def sensitive_path_prefixes(self) -> list[str]:
        """Path prefixes that should be blocked from external access"""
        return [
            "/admin",
            "/internal",
            "/debug",
            "/security/audit",
            "/security/intrusions",
        ]
    
    # ============================================================
    # Dependency Policy Configuration
    # ============================================================
    
    @property
    def fail_closed_dependencies(self) -> set[str]:
        """Dependencies that must be healthy for the system to be ready"""
        return {"fips_module", "audit_logger"}
    
    @property
    def fail_open_dependencies(self) -> set[str]:
        """Dependencies that can be unavailable without blocking readiness"""
        return {"redis_cache", "prefetch_queue", "ml_runtime"}
    
    # ============================================================
    # Observability Configuration
    # ============================================================
    
    @property
    def metrics_retention_days(self) -> int:
        """Number of days to retain metrics"""
        return int(os.getenv("METRICS_RETENTION_DAYS", "7"))
    
    @property
    def audit_retention_days(self) -> int:
        """Number of days to retain audit logs"""
        return int(os.getenv("AUDIT_RETENTION_DAYS", "90"))
    
    @property
    def lifecycle_retention_days(self) -> int:
        """Number of days to retain ML lifecycle events"""
        return int(os.getenv("LIFECYCLE_RETENTION_DAYS", "365"))
    
    @property
    def metrics_persistence_enabled(self) -> bool:
        """Enable persistent metrics storage in Redis"""
        return bool(os.getenv("METRICS_PERSISTENCE_ENABLED", "true").lower() == "true")
    
    def validate_production_settings(self):
        """Validate required settings for production"""
        errors = []
        
        if self.is_production:
            if not self.secret_key or self.secret_key == "dev_secret_key_change_in_prod":
                errors.append("SECRET_KEY must be set in production")
            if not self.cache_encryption_key or self.cache_encryption_key == "dev_key_32_characters_here!!":
                errors.append("CACHE_ENCRYPTION_KEY must be set in production")
            if not self.grafana_password:
                errors.append("GRAFANA_PASSWORD must be set in production")
        
        if errors:
            raise ValueError("; ".join(errors))


class Settings:
    """Singleton settings instance"""
    _instance: Optional[AppSettings] = None
    
    @classmethod
    def get(cls) -> AppSettings:
        if cls._instance is None:
            cls._instance = AppSettings()
            # Validate production settings
            cls._instance.validate_production_settings()
        return cls._instance


# Global settings instance
settings = Settings.get()
