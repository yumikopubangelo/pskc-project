# ============================================================
# PSKC — Database Connection Management
# ============================================================
"""Database connection initialization and management for SQLite."""
import os
import logging
from typing import Dict, Generator, Optional
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from config.settings import settings
from src.database.models import Base

logger = logging.getLogger(__name__)


SQLITE_COMPATIBILITY_COLUMNS: Dict[str, Dict[str, str]] = {
    "per_key_metrics": {
        "hit_rate": "FLOAT DEFAULT 0.0",
        "error_count": "INTEGER DEFAULT 0",
        "avg_confidence": "FLOAT DEFAULT 0.0",
    },
}


class DatabaseConnection:
    """
    Manages SQLite database connection, initialization, and session management.
    
    Thread-safe singleton pattern for database connection management.
    """
    
    _instance: Optional["DatabaseConnection"] = None
    _engine: Optional[Engine] = None
    _session_maker: Optional[sessionmaker] = None
    
    def __new__(cls) -> "DatabaseConnection":
        """Ensure singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize database connection (called once)."""
        if self._engine is None:
            self._initialize_database()
    
    @classmethod
    def _initialize_database(cls):
        """Initialize database engine and session factory."""
        database_url = settings.database_url
        url = make_url(database_url)

        engine_kwargs = {
            "echo": False,
        }

        if url.get_backend_name() == "sqlite":
            database_path = url.database or ""
            if database_path and database_path != ":memory:":
                db_dir = os.path.dirname(os.path.abspath(database_path))
                if db_dir:
                    os.makedirs(db_dir, exist_ok=True)

            engine_kwargs.update(
                {
                    "connect_args": {"check_same_thread": False},
                    "poolclass": StaticPool,
                }
            )

        cls._engine = create_engine(database_url, **engine_kwargs)
        
        # Enable foreign keys for SQLite
        @event.listens_for(Engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            """Enable foreign key constraints in SQLite."""
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
        
        # Create session factory
        cls._session_maker = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=cls._engine,
        )
        
        # Initialize database schema
        cls._create_tables()
        logger.info("Database initialized at %s", database_url)
    
    @classmethod
    def _create_tables(cls):
        """
        Apply pending Alembic migrations, or fall back to create_all for
        environments where Alembic is not available (e.g. bare CI runners).
        """
        if cls._engine is None:
            raise RuntimeError("Engine not initialized")

        migrations_applied = False

        try:
            from alembic.config import Config
            from alembic import command

            # Locate alembic.ini relative to the project root
            project_root = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..")
            )
            alembic_cfg = Config(os.path.join(project_root, "alembic.ini"))
            # Override the DB URL so it matches the runtime engine
            alembic_cfg.set_main_option(
                "sqlalchemy.url", str(cls._engine.url)
            )

            import threading
            
            # Define the migration function
            def run_migration():
                command.upgrade(alembic_cfg, "head")

            logger.info("Starting Alembic migrations (with 30s timeout)...")
            migration_thread = threading.Thread(target=run_migration)
            migration_thread.daemon = True
            migration_thread.start()
            migration_thread.join(timeout=30.0)

            if migration_thread.is_alive():
                logger.error(
                    "CRITICAL: Alembic migrations timed out after 30 seconds! "
                    "The database might be locked. Falling back to create_all."
                )
                Base.metadata.create_all(bind=cls._engine)
                # We do not set migrations_applied = True because the migration didn't complete cleanly
            else:
                logger.info("Database schema is up-to-date (Alembic migrations applied successfully)")
                migrations_applied = True

        except ImportError:
            # Alembic not installed — fall back to SQLAlchemy create_all
            logger.warning(
                "Alembic not available; falling back to create_all. "
                "Install alembic for proper migration support."
            )
            Base.metadata.create_all(bind=cls._engine)
            logger.info("Database tables created/verified via create_all")

        except Exception as e:
            logger.error(f"Error applying database migrations: {e}")
            raise

        cls._repair_schema_compatibility(migrations_applied=migrations_applied)

    @classmethod
    def _repair_schema_compatibility(cls, *, migrations_applied: bool) -> None:
        """
        Repair lightweight schema drift for older SQLite databases.

        Existing user environments may already have tables created from older
        ORM definitions. New ORM fields such as ``per_key_metrics.hit_rate``
        make SQLAlchemy emit SELECT/INSERT statements that fail immediately on
        those databases. We repair a small set of additive columns here so the
        application remains upgrade-safe without requiring manual DB resets.
        """
        if cls._engine is None:
            raise RuntimeError("Engine not initialized")

        if cls._engine.url.get_backend_name() != "sqlite":
            return

        inspector = inspect(cls._engine)
        repaired_columns = []

        with cls._engine.begin() as connection:
            for table_name, expected_columns in SQLITE_COMPATIBILITY_COLUMNS.items():
                if not inspector.has_table(table_name):
                    continue

                existing_columns = {
                    column["name"]
                    for column in inspector.get_columns(table_name)
                }

                for column_name, ddl in expected_columns.items():
                    if column_name in existing_columns:
                        continue
                    connection.exec_driver_sql(
                        f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"
                    )
                    repaired_columns.append(f"{table_name}.{column_name}")

        if repaired_columns:
            logger.warning(
                "Applied SQLite schema compatibility repair for columns: %s",
                ", ".join(repaired_columns),
            )
        elif migrations_applied:
            logger.debug("No SQLite compatibility schema repair required")
    
    @classmethod
    def get_session(cls) -> Session:
        """
        Get a new database session.
        
        Returns:
            SQLAlchemy Session instance
            
        Raises:
            RuntimeError: If database connection is not initialized
        """
        if cls._session_maker is None:
            cls._initialize_database()
        
        return cls._session_maker()
    
    @classmethod
    def get_engine(cls) -> Engine:
        """
        Get the database engine.
        
        Returns:
            SQLAlchemy Engine instance
            
        Raises:
            RuntimeError: If database connection is not initialized
        """
        if cls._engine is None:
            cls._initialize_database()
        
        return cls._engine
    
    @classmethod
    def close_all(cls):
        """Close all connections in the pool."""
        if cls._engine is not None:
            cls._engine.dispose()
            logger.info("Database connections closed")


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a database session.
    
    Yields:
        SQLAlchemy Session
        
    Usage in routes:
        from fastapi import Depends
        from src.database import get_db
        
        @app.get("/data")
        def get_data(db: Session = Depends(get_db)):
            ...
    """
    db = DatabaseConnection.get_session()
    try:
        yield db
    finally:
        db.close()
