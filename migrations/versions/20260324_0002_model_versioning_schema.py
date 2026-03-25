"""Model versioning database schema — model_versions, model_metrics, training_metadata, key_predictions, per_key_metrics

Revision ID: 0002_model_versioning_schema
Revises: 0001_initial_schema
Create Date: 2026-03-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0002_model_versioning_schema"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- model_versions ---
    op.create_table(
        "model_versions",
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("version_number", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("parent_version_id", sa.Integer(), nullable=True),
        sa.Column("metrics_json", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("version_id"),
        sa.ForeignKeyConstraint(["parent_version_id"], ["model_versions.version_id"], ondelete="SET NULL"),
    )
    op.create_index(op.f("ix_model_versions_version_id"), "model_versions", ["version_id"])
    op.create_index(op.f("ix_model_versions_model_name"), "model_versions", ["model_name"])
    op.create_index(op.f("ix_model_versions_created_at"), "model_versions", ["created_at"])
    op.create_index(op.f("ix_model_versions_status"), "model_versions", ["status"])
    op.create_index("idx_model_versions_model_name_version_number", "model_versions", ["model_name", "version_number"])
    op.create_index("idx_model_versions_parent_version_id", "model_versions", ["parent_version_id"])

    # --- model_metrics ---
    op.create_table(
        "model_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("metric_name", sa.String(length=255), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["version_id"], ["model_versions.version_id"], ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_model_metrics_id"), "model_metrics", ["id"])
    op.create_index(op.f("ix_model_metrics_version_id"), "model_metrics", ["version_id"])
    op.create_index(op.f("ix_model_metrics_metric_name"), "model_metrics", ["metric_name"])
    op.create_index(op.f("ix_model_metrics_recorded_at"), "model_metrics", ["recorded_at"])
    op.create_index("idx_model_metrics_version_id_metric_name", "model_metrics", ["version_id", "metric_name"])

    # --- training_metadata ---
    op.create_table(
        "training_metadata",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("training_start_time", sa.DateTime(), nullable=False),
        sa.Column("training_end_time", sa.DateTime(), nullable=True),
        sa.Column("samples_count", sa.Integer(), nullable=False),
        sa.Column("accuracy_before", sa.Float(), nullable=True),
        sa.Column("accuracy_after", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["version_id"], ["model_versions.version_id"], ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_training_metadata_id"), "training_metadata", ["id"])
    op.create_index(op.f("ix_training_metadata_version_id"), "training_metadata", ["version_id"])
    op.create_index(op.f("ix_training_metadata_training_start_time"), "training_metadata", ["training_start_time"])
    op.create_index("idx_training_metadata_version_id", "training_metadata", ["version_id"])

    # --- key_predictions ---
    op.create_table(
        "key_predictions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("predicted_value", sa.String(length=500), nullable=False),
        sa.Column("actual_value", sa.String(length=500), nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["version_id"], ["model_versions.version_id"], ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_key_predictions_id"), "key_predictions", ["id"])
    op.create_index(op.f("ix_key_predictions_version_id"), "key_predictions", ["version_id"])
    op.create_index(op.f("ix_key_predictions_key"), "key_predictions", ["key"])
    op.create_index(op.f("ix_key_predictions_timestamp"), "key_predictions", ["timestamp"])
    op.create_index("idx_key_predictions_version_id_key", "key_predictions", ["version_id", "key"])
    op.create_index("idx_key_predictions_is_correct", "key_predictions", ["is_correct"])

    # --- per_key_metrics ---
    op.create_table(
        "per_key_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("accuracy", sa.Float(), nullable=False),
        sa.Column("drift_score", sa.Float(), nullable=True),
        sa.Column("cache_hit_rate", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["version_id"], ["model_versions.version_id"], ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_per_key_metrics_id"), "per_key_metrics", ["id"])
    op.create_index(op.f("ix_per_key_metrics_version_id"), "per_key_metrics", ["version_id"])
    op.create_index(op.f("ix_per_key_metrics_key"), "per_key_metrics", ["key"])
    op.create_index(op.f("ix_per_key_metrics_updated_at"), "per_key_metrics", ["updated_at"])
    op.create_index("idx_per_key_metrics_version_id_key", "per_key_metrics", ["version_id", "key"])


def downgrade() -> None:
    op.drop_table("per_key_metrics")
    op.drop_table("key_predictions")
    op.drop_table("training_metadata")
    op.drop_table("model_metrics")
    op.drop_table("model_versions")
