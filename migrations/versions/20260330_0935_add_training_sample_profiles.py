"""Add training_sample_profiles table

Revision ID: 20260330_0935
Revises: 0a88837a9eec
Create Date: 2026-03-30 09:35:00+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260330_0935"
down_revision: Union[str, None] = "0a88837a9eec"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "training_sample_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("total_samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unique_keys", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unique_services", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("temporal_profile", sa.JSON(), nullable=True),
        sa.Column("key_frequency_profile", sa.JSON(), nullable=True),
        sa.Column("service_distribution", sa.JSON(), nullable=True),
        sa.Column("cache_hit_rate", sa.Float(), nullable=True, server_default="0.0"),
        sa.Column("avg_latency_ms", sa.Float(), nullable=True, server_default="0.0"),
        sa.Column("latency_p95_ms", sa.Float(), nullable=True, server_default="0.0"),
        sa.Column("feature_stats", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["model_versions.version_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_training_sample_profiles_id"), "training_sample_profiles", ["id"])
    op.create_index(
        op.f("ix_training_sample_profiles_version_id"),
        "training_sample_profiles",
        ["version_id"],
    )
    op.create_index(
        op.f("ix_training_sample_profiles_created_at"),
        "training_sample_profiles",
        ["created_at"],
    )
    op.create_index(
        "idx_tsp_version_id",
        "training_sample_profiles",
        ["version_id"],
    )
    op.create_index(
        "idx_tsp_created_at",
        "training_sample_profiles",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_tsp_created_at", table_name="training_sample_profiles")
    op.drop_index("idx_tsp_version_id", table_name="training_sample_profiles")
    op.drop_index(op.f("ix_training_sample_profiles_created_at"), table_name="training_sample_profiles")
    op.drop_index(op.f("ix_training_sample_profiles_version_id"), table_name="training_sample_profiles")
    op.drop_index(op.f("ix_training_sample_profiles_id"), table_name="training_sample_profiles")
    op.drop_table("training_sample_profiles")
