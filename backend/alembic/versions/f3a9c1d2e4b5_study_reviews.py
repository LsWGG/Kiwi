"""study reviews scheduling

Revision ID: f3a9c1d2e4b5
Revises: cab40dbd056d
Create Date: 2026-10-17 21:10:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f3a9c1d2e4b5'
down_revision: Union[str, None] = 'cab40dbd056d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 会话形态：drill（渐进训练）/ review（今日复习）
    op.add_column(
        'study_sessions',
        sa.Column('mode', sa.String(length=20), server_default='drill', nullable=False),
    )

    op.create_table(
        'study_reviews',
        sa.Column('kb_id', sa.Uuid(), nullable=False),
        sa.Column('wiki_page_id', sa.Uuid(), nullable=True),
        sa.Column('slug', sa.String(length=120), nullable=False),
        sa.Column('ease_factor', sa.Float(), server_default=sa.text('2.5'), nullable=False),
        sa.Column('interval_days', sa.Float(), server_default=sa.text('0'), nullable=False),
        sa.Column('repetitions', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column(
            'due_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('last_reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_correct', sa.Boolean(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['kb_id'], ['knowledge_bases.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['wiki_page_id'], ['wiki_pages.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('kb_id', 'slug', name='uq_study_reviews_kb_slug'),
    )
    op.create_index(op.f('ix_study_reviews_kb_id'), 'study_reviews', ['kb_id'], unique=False)
    op.create_index(op.f('ix_study_reviews_due_at'), 'study_reviews', ['due_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_study_reviews_due_at'), table_name='study_reviews')
    op.drop_index(op.f('ix_study_reviews_kb_id'), table_name='study_reviews')
    op.drop_table('study_reviews')
    op.drop_column('study_sessions', 'mode')
