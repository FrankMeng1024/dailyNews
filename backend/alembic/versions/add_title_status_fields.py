"""Add title translation status fields

Revision ID: add_title_status_fields
Revises: add_quality_scoring
Create Date: 2026-03-09

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_title_status_fields'
down_revision = 'add_quality_scoring'
branch_labels = None
depends_on = None


def upgrade():
    # Add title translation status fields to news table
    op.add_column('news', sa.Column('title_status', sa.String(32), server_default='pending', comment='Title translation status: pending/ready/failed'))
    op.add_column('news', sa.Column('title_retry_count', sa.Integer, server_default='0', comment='Title translation retry count'))
    op.add_column('news', sa.Column('title_last_error', sa.String(512), nullable=True, comment='Last title translation error message'))
    op.add_column('news', sa.Column('title_next_retry_at', sa.DateTime, nullable=True, comment='Next retry time for title translation'))

    # Add index on title_status for efficient filtering
    op.create_index('ix_news_title_status', 'news', ['title_status'])

    # Backfill existing data: set title_status based on title_zh
    # If title_zh is not null, set status to 'ready', otherwise 'pending'
    op.execute("""
        UPDATE news
        SET title_status = CASE
            WHEN title_zh IS NOT NULL AND title_zh != '' THEN 'ready'
            ELSE 'pending'
        END
    """)


def downgrade():
    # Drop index
    op.drop_index('ix_news_title_status', 'news')

    # Drop columns
    op.drop_column('news', 'title_next_retry_at')
    op.drop_column('news', 'title_last_error')
    op.drop_column('news', 'title_retry_count')
    op.drop_column('news', 'title_status')
