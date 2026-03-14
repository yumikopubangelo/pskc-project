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
