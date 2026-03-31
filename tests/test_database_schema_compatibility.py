from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from src.database.connection import DatabaseConnection


def test_sqlite_compatibility_repair_adds_missing_per_key_metric_columns(tmp_path):
    db_path = Path(tmp_path) / "compat.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE per_key_metrics (
                    id INTEGER PRIMARY KEY,
                    version_id INTEGER NOT NULL,
                    key VARCHAR(255) NOT NULL,
                    accuracy FLOAT DEFAULT 0.0,
                    drift_score FLOAT DEFAULT 0.0,
                    cache_hit_rate FLOAT DEFAULT 0.0,
                    total_predictions INTEGER DEFAULT 0,
                    timestamp DATETIME
                )
                """
            )
        )

    original_engine = DatabaseConnection._engine
    try:
        DatabaseConnection._engine = engine
        DatabaseConnection._repair_schema_compatibility(migrations_applied=False)
    finally:
        DatabaseConnection._engine = original_engine

    columns = {
        column["name"]
        for column in inspect(engine).get_columns("per_key_metrics")
    }
    assert "hit_rate" in columns
    assert "error_count" in columns
    assert "avg_confidence" in columns


def test_metadata_compatibility_creates_missing_training_sample_profile_table(tmp_path):
    db_path = Path(tmp_path) / "compat_missing_table.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE model_versions (
                    version_id INTEGER PRIMARY KEY,
                    model_name VARCHAR(255) NOT NULL,
                    version_number VARCHAR(50) NOT NULL,
                    created_at DATETIME NOT NULL,
                    status VARCHAR(50) NOT NULL,
                    parent_version_id INTEGER,
                    metrics_json JSON
                )
                """
            )
        )

    original_engine = DatabaseConnection._engine
    try:
        DatabaseConnection._engine = engine
        DatabaseConnection._ensure_metadata_tables_exist()
    finally:
        DatabaseConnection._engine = original_engine

    inspector = inspect(engine)
    assert "training_sample_profiles" in inspector.get_table_names()
