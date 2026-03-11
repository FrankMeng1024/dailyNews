"""Add quality scoring and system config tables

Revision ID: add_quality_scoring
Revises: add_content_type_fields
Create Date: 2026-03-02

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = 'add_quality_scoring'
down_revision = 'add_content_type_fields'
branch_labels = None
depends_on = None


def upgrade():
    # Add quality scoring fields to news table
    op.add_column('news', sa.Column('source_authority_score', sa.DECIMAL(5, 4), nullable=True, comment='Source authority score (0-1)'))
    op.add_column('news', sa.Column('content_depth_score', sa.DECIMAL(5, 4), nullable=True, comment='Content depth score (0-1)'))
    op.add_column('news', sa.Column('timeliness_score', sa.DECIMAL(5, 4), nullable=True, comment='Timeliness score (0-1)'))
    op.add_column('news', sa.Column('technical_credibility_score', sa.DECIMAL(5, 4), nullable=True, comment='Technical credibility score (0-1)'))
    op.add_column('news', sa.Column('quality_breakdown', sa.JSON, nullable=True, comment='Quality score breakdown details'))
    op.add_column('news', sa.Column('entity_count', sa.Integer, default=0, comment='Technical entity count'))
    op.add_column('news', sa.Column('content_length', sa.Integer, default=0, comment='Content character count'))
    op.add_column('news', sa.Column('source_tier', sa.Integer, default=3, comment='Source priority tier (1=highest, 4=lowest)'))

    # Add index on source_tier
    op.create_index('ix_news_source_tier', 'news', ['source_tier'])

    # Create system_config table
    op.create_table(
        'system_config',
        sa.Column('key', sa.String(128), primary_key=True, comment='Config key'),
        sa.Column('value', sa.Text, comment='Config value (JSON or string)'),
        sa.Column('updated_at', sa.DateTime, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=True),
    )

    # Create fetch_history table
    op.create_table(
        'fetch_history',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('fetch_type', sa.String(32), nullable=True, comment='Type: rss/newsapi/manual'),
        sa.Column('source_name', sa.String(128), nullable=True, comment='Source identifier'),
        sa.Column('started_at', sa.DateTime, nullable=False, comment='Fetch start time'),
        sa.Column('completed_at', sa.DateTime, nullable=True, comment='Fetch completion time'),
        sa.Column('status', sa.String(32), default='running', comment='running/completed/failed'),
        sa.Column('articles_found', sa.Integer, default=0, comment='Articles found'),
        sa.Column('articles_new', sa.Integer, default=0, comment='New articles added'),
        sa.Column('articles_filtered', sa.Integer, default=0, comment='Articles filtered by quality'),
        sa.Column('error_message', sa.Text, nullable=True, comment='Error message if failed'),
        sa.Column('metadata', sa.JSON, nullable=True, comment='Additional metadata'),
    )

    # Add indexes on fetch_history
    op.create_index('ix_fetch_history_fetch_type', 'fetch_history', ['fetch_type'])
    op.create_index('ix_fetch_history_source_name', 'fetch_history', ['source_name'])


def downgrade():
    # Drop tables
    op.drop_table('fetch_history')
    op.drop_table('system_config')

    # Drop indexes
    op.drop_index('ix_news_source_tier', 'news')

    # Drop columns from news table
    op.drop_column('news', 'source_tier')
    op.drop_column('news', 'content_length')
    op.drop_column('news', 'entity_count')
    op.drop_column('news', 'quality_breakdown')
    op.drop_column('news', 'technical_credibility_score')
    op.drop_column('news', 'timeliness_score')
    op.drop_column('news', 'content_depth_score')
    op.drop_column('news', 'source_authority_score')
