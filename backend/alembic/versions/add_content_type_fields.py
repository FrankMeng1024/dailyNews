"""add content type and verification fields

Revision ID: add_content_type_fields
Revises:
Create Date: 2026-03-01

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = 'add_content_type_fields'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Add new columns to news table
    op.add_column('news', sa.Column('source_type', sa.String(32), nullable=True, server_default='news', comment='Content type: news/blog/paper/discussion/podcast/video'))
    op.add_column('news', sa.Column('content_format', sa.String(32), nullable=True, server_default='text', comment='Format: text/audio/video/mixed'))
    op.add_column('news', sa.Column('media_duration', sa.Integer(), nullable=True, comment='Media duration in seconds (for audio/video)'))
    op.add_column('news', sa.Column('is_verified', sa.Boolean(), nullable=True, server_default='0', comment='Whether content source is verified and trustworthy'))
    op.add_column('news', sa.Column('ai_relevance_score', sa.DECIMAL(5, 4), nullable=True, comment='AI relevance score (0-1) from GLM verification'))

    # Create indexes
    op.create_index('ix_news_source_type', 'news', ['source_type'])


def downgrade():
    # Drop indexes
    op.drop_index('ix_news_source_type', table_name='news')

    # Drop columns
    op.drop_column('news', 'ai_relevance_score')
    op.drop_column('news', 'is_verified')
    op.drop_column('news', 'media_duration')
    op.drop_column('news', 'content_format')
    op.drop_column('news', 'source_type')
