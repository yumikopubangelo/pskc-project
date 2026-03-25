"""Add PredictionLog model

Revision ID: 20260325_0003
Revises: 20260324_0002
Create Date: 2026-03-25 10:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260325_0003'
down_revision = '20260324_0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create prediction_logs table
    op.create_table(
        'prediction_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('version_id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=255), nullable=False),
        sa.Column('predicted_value', sa.String(length=500), nullable=False),
        sa.Column('actual_value', sa.String(length=500), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('is_correct', sa.Boolean(), nullable=True),
        sa.Column('latency_ms', sa.Float(), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['version_id'], ['model_versions.version_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes
    op.create_index('idx_prediction_logs_version_id', 'prediction_logs', ['version_id'])
    op.create_index('idx_prediction_logs_key', 'prediction_logs', ['key'])
    op.create_index('idx_prediction_logs_timestamp', 'prediction_logs', ['timestamp'])
    op.create_index('idx_prediction_logs_version_key_timestamp', 'prediction_logs', ['version_id', 'key', 'timestamp'])
    
    # Update per_key_metrics table with new columns
    op.add_column('per_key_metrics', sa.Column('hit_rate', sa.Float(), nullable=True))
    op.add_column('per_key_metrics', sa.Column('total_predictions', sa.Integer(), nullable=True))
    op.add_column('per_key_metrics', sa.Column('error_count', sa.Integer(), nullable=True))
    op.add_column('per_key_metrics', sa.Column('avg_confidence', sa.Float(), nullable=True))
    op.add_column('per_key_metrics', sa.Column('timestamp', sa.DateTime(), nullable=True))
    
    # Rename updated_at to timestamp if it exists, or just add timestamp
    try:
        op.drop_column('per_key_metrics', 'updated_at')
    except:
        pass
    
    # Add timestamp with default
    try:
        op.alter_column('per_key_metrics', 'timestamp', existing_type=sa.DateTime(), nullable=False)
    except:
        pass
    
    # Create index on timestamp
    op.create_index('idx_per_key_metrics_timestamp', 'per_key_metrics', ['timestamp'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('idx_per_key_metrics_timestamp', table_name='per_key_metrics')
    op.drop_index('idx_prediction_logs_version_key_timestamp', table_name='prediction_logs')
    op.drop_index('idx_prediction_logs_timestamp', table_name='prediction_logs')
    op.drop_index('idx_prediction_logs_key', table_name='prediction_logs')
    op.drop_index('idx_prediction_logs_version_id', table_name='prediction_logs')
    
    # Drop columns from per_key_metrics
    op.drop_column('per_key_metrics', 'timestamp')
    op.drop_column('per_key_metrics', 'avg_confidence')
    op.drop_column('per_key_metrics', 'error_count')
    op.drop_column('per_key_metrics', 'total_predictions')
    op.drop_column('per_key_metrics', 'hit_rate')
    
    # Add back updated_at
    op.add_column('per_key_metrics', sa.Column('updated_at', sa.DateTime(), nullable=False))
    
    # Drop prediction_logs table
    op.drop_table('prediction_logs')
