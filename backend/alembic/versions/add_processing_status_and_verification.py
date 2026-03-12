"""Add processing_status and verification fields

Revision ID: add_processing_status_verification
Revises: add_title_status_fields
Create Date: 2026-03-11

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_processing_status_verification'
down_revision = 'add_title_status_fields'
branch_labels = None
depends_on = None


def upgrade():
    # Add unified processing status field
    op.add_column('news', sa.Column('processing_status', sa.String(32), server_default='fetching',
                                    comment='Unified status: fetching/verifying/translating/refining/ready/failed'))

    # Add verification fields
    op.add_column('news', sa.Column('verification_status', sa.String(32), server_default='pending',
                                    comment='Verification status: pending/verifying/verified/failed'))
    op.add_column('news', sa.Column('verification_score', sa.DECIMAL(5, 4), nullable=True,
                                    comment='Verification confidence score (0-1)'))
    op.add_column('news', sa.Column('verification_sources', sa.JSON, nullable=True,
                                    comment='Verification source list'))
    op.add_column('news', sa.Column('verification_error', sa.String(512), nullable=True,
                                    comment='Verification error message'))
    op.add_column('news', sa.Column('verification_retry_count', sa.Integer, server_default='0',
                                    comment='Verification retry count'))
    op.add_column('news', sa.Column('verification_next_retry_at', sa.DateTime, nullable=True,
                                    comment='Next retry time for verification'))

    # Add index on processing_status for efficient filtering
    op.create_index('ix_news_processing_status', 'news', ['processing_status'])

    # Backfill existing data: calculate processing_status based on existing fields
    # Logic:
    # - If content_status = 'ready' and title_status = 'ready' -> 'ready'
    # - If title_status = 'ready' but content_status != 'ready' -> 'refining'
    # - If title_status != 'ready' but has content -> 'translating'
    # - If no content (< 200 chars) -> 'fetching'
    # - For verification, set to 'verified' for existing ready items (skip verification for old data)
    op.execute("""
        UPDATE news
        SET processing_status = CASE
            WHEN content_status = 'ready' AND title_status = 'ready' THEN 'ready'
            WHEN title_status = 'ready' AND content_status != 'ready' THEN 'refining'
            WHEN LENGTH(COALESCE(original_content, '')) >= 200 AND title_status != 'ready' THEN 'translating'
            WHEN LENGTH(COALESCE(original_content, '')) >= 200 THEN 'verifying'
            ELSE 'fetching'
        END,
        verification_status = CASE
            WHEN content_status = 'ready' AND title_status = 'ready' THEN 'verified'
            WHEN LENGTH(COALESCE(original_content, '')) >= 200 THEN 'verified'
            ELSE 'pending'
        END
    """)


def downgrade():
    # Drop index
    op.drop_index('ix_news_processing_status', 'news')

    # Drop verification columns
    op.drop_column('news', 'verification_next_retry_at')
    op.drop_column('news', 'verification_retry_count')
    op.drop_column('news', 'verification_error')
    op.drop_column('news', 'verification_sources')
    op.drop_column('news', 'verification_score')
    op.drop_column('news', 'verification_status')

    # Drop processing_status column
    op.drop_column('news', 'processing_status')
