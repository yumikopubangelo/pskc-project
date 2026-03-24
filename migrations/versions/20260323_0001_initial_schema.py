"""Initial schema — simulation_events, retraining_history, drift_analysis_history

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-03-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- simulation_events ---
    op.create_table(
        "simulation_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("simulation_id", sa.String(length=255), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("key_id", sa.String(length=255), nullable=False),
        sa.Column("service_id", sa.String(length=255), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("cache_hit", sa.Boolean(), nullable=False),
        sa.Column("features", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_simulation_events_id"), "simulation_events", ["id"])
    op.create_index(op.f("ix_simulation_events_simulation_id"), "simulation_events", ["simulation_id"])
    op.create_index(op.f("ix_simulation_events_timestamp"), "simulation_events", ["timestamp"])
    op.create_index(op.f("ix_simulation_events_created_at"), "simulation_events", ["created_at"])
    op.create_index("idx_sim_events_sim_id_timestamp", "simulation_events", ["simulation_id", "timestamp"])
    op.create_index("idx_sim_events_created_at", "simulation_events", ["created_at"])

    # --- retraining_history ---
    op.create_table(
        "retraining_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("simulation_id", sa.String(length=255), nullable=False),
        sa.Column("drift_score", sa.Float(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("accuracy_before", sa.Float(), nullable=True),
        sa.Column("accuracy_after", sa.Float(), nullable=True),
        sa.Column("improvement_percent", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.Column("retraining_started_at", sa.DateTime(), nullable=True),
        sa.Column("retraining_completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_retraining_history_id"), "retraining_history", ["id"])
    op.create_index(op.f("ix_retraining_history_simulation_id"), "retraining_history", ["simulation_id"])
    op.create_index(op.f("ix_retraining_history_created_at"), "retraining_history", ["created_at"])
    op.create_index("idx_retrain_sim_id", "retraining_history", ["simulation_id"])
    op.create_index("idx_retrain_created_at", "retraining_history", ["created_at"])

    # --- drift_analysis_history ---
    op.create_table(
        "drift_analysis_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("simulation_id", sa.String(length=255), nullable=False),
        sa.Column("drift_score", sa.Float(), nullable=False),
        sa.Column("distribution_divergence", sa.Float(), nullable=True),
        sa.Column("temporal_divergence", sa.Float(), nullable=True),
        sa.Column("sequence_divergence", sa.Float(), nullable=True),
        sa.Column("major_changes", sa.JSON(), nullable=True),
        sa.Column("analysis_timestamp", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_drift_analysis_history_id"), "drift_analysis_history", ["id"])
    op.create_index(op.f("ix_drift_analysis_history_simulation_id"), "drift_analysis_history", ["simulation_id"])
    op.create_index(op.f("ix_drift_analysis_history_created_at"), "drift_analysis_history", ["created_at"])
    op.create_index("idx_drift_sim_id", "drift_analysis_history", ["simulation_id"])
    op.create_index("idx_drift_created_at", "drift_analysis_history", ["created_at"])


def downgrade() -> None:
    op.drop_table("drift_analysis_history")
    op.drop_table("retraining_history")
    op.drop_table("simulation_events")
