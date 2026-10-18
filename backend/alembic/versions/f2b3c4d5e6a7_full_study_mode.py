"""full study mode: exam templates, mock exams, topics, plans, annotations

Revision ID: f2b3c4d5e6a7
Revises: b8d4f2a6c1e9
Create Date: 2026-10-18 09:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f2b3c4d5e6a7'
down_revision: Union[str, None] = 'b8d4f2a6c1e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------- 考试场景模板 ----------
    op.create_table(
        'exam_templates',
        sa.Column('kb_id', sa.Uuid(), nullable=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('code', sa.String(length=80), nullable=False),
        sa.Column('description', sa.Text(), server_default='', nullable=False),
        sa.Column('is_builtin', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column(
            'question_types_json',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            'scoring_rules_json',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            'passing_criteria_json',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column('duration_minutes', sa.Integer(), server_default=sa.text('120'), nullable=False),
        sa.Column(
            'difficulty_distribution',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            'coverage_domains',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['kb_id'], ['knowledge_bases.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_exam_templates_kb_code', 'exam_templates', ['kb_id', 'code'], unique=False
    )

    # ---------- 画像扩展 ----------
    op.add_column('study_profiles', sa.Column('exam_template_id', sa.Uuid(), nullable=True))
    op.add_column('study_profiles', sa.Column('target_date', sa.Date(), nullable=True))
    op.add_column(
        'study_profiles',
        sa.Column('preferred_mode', sa.String(length=20), server_default='auto', nullable=False),
    )
    op.add_column(
        'study_profiles',
        sa.Column(
            'weak_areas',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        'study_profiles',
        sa.Column(
            'profile_json',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        'study_profiles',
        sa.Column('onboarded', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    )
    op.create_foreign_key(
        'fk_study_profiles_exam_template',
        'study_profiles',
        'exam_templates',
        ['exam_template_id'],
        ['id'],
        ondelete='SET NULL',
    )

    # ---------- 仿真试卷 ----------
    op.create_table(
        'mock_exams',
        sa.Column('kb_id', sa.Uuid(), nullable=False),
        sa.Column('profile_id', sa.Uuid(), nullable=True),
        sa.Column('exam_template_id', sa.Uuid(), nullable=True),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='generating', nullable=False),
        sa.Column(
            'duration_minutes', sa.Integer(), server_default=sa.text('120'), nullable=False
        ),
        sa.Column('question_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('total_score', sa.Float(), nullable=True),
        sa.Column('max_score', sa.Float(), server_default=sa.text('100'), nullable=False),
        sa.Column('passing_score', sa.Float(), nullable=True),
        sa.Column(
            'score_breakdown_json',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            'time_spent_json',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            'template_snapshot_json',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            'generation_progress', sa.Float(), server_default=sa.text('0'), nullable=False
        ),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'generated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['kb_id'], ['knowledge_bases.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['profile_id'], ['study_profiles.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['exam_template_id'], ['exam_templates.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_mock_exams_kb_id', 'mock_exams', ['kb_id'], unique=False)
    op.create_index('ix_mock_exams_kb_created', 'mock_exams', ['kb_id', 'created_at'], unique=False)

    op.create_table(
        'mock_exam_items',
        sa.Column('mock_exam_id', sa.Uuid(), nullable=False),
        sa.Column('question_id', sa.Uuid(), nullable=True),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column(
            'section_type', sa.String(length=30), server_default='single_choice', nullable=False
        ),
        sa.Column('section_name', sa.String(length=120), server_default='', nullable=False),
        sa.Column('score', sa.Float(), server_default=sa.text('1'), nullable=False),
        sa.Column('user_answer', sa.Text(), server_default='', nullable=False),
        sa.Column('selected_index', sa.Integer(), nullable=True),
        sa.Column('score_awarded', sa.Float(), nullable=True),
        sa.Column(
            'feedback_json',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column('answered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['mock_exam_id'], ['mock_exams.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['question_id'], ['study_questions.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('mock_exam_id', 'order_index', name='uq_mock_exam_items_order'),
    )
    op.create_index(
        'ix_mock_exam_items_mock_exam_id', 'mock_exam_items', ['mock_exam_id'], unique=False
    )
    op.create_index(
        'ix_mock_exam_items_question_id', 'mock_exam_items', ['question_id'], unique=False
    )

    # ---------- 题目扩展 ----------
    op.add_column('study_questions', sa.Column('topic_slug', sa.String(length=120), nullable=True))
    op.add_column(
        'study_questions',
        sa.Column(
            'question_type',
            sa.String(length=30),
            server_default='single_choice',
            nullable=False,
        ),
    )
    op.add_column(
        'study_questions',
        sa.Column(
            'body_json',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        'study_questions',
        sa.Column(
            'answer_json',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column('study_questions', sa.Column('source_hash', sa.String(length=64), nullable=True))
    op.add_column(
        'study_questions',
        sa.Column(
            'web_sources_json',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        'study_questions',
        sa.Column(
            'confidence_level',
            sa.String(length=20),
            server_default='verified',
            nullable=False,
        ),
    )
    op.add_column(
        'study_questions',
        sa.Column(
            'cache_status', sa.String(length=20), server_default='active', nullable=False
        ),
    )
    op.create_index(
        'ix_study_questions_kb_type', 'study_questions', ['kb_id', 'question_type'], unique=False
    )

    # ---------- 作答扩展 ----------
    op.add_column(
        'study_attempts', sa.Column('mock_exam_id', sa.Uuid(), nullable=True)
    )
    op.add_column(
        'study_attempts', sa.Column('user_answer', sa.Text(), server_default='', nullable=False)
    )
    op.add_column('study_attempts', sa.Column('llm_score', sa.Float(), nullable=True))
    op.add_column(
        'study_attempts',
        sa.Column(
            'score_breakdown_json',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        'study_attempts',
        sa.Column('mode', sa.String(length=20), server_default='drill', nullable=False),
    )
    op.add_column(
        'study_attempts',
        sa.Column(
            'attempted_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        'fk_study_attempts_mock_exam',
        'study_attempts',
        'mock_exams',
        ['mock_exam_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        'ix_study_attempts_kb_created',
        'study_attempts',
        ['kb_id', 'created_at'],
        unique=False,
    )
    op.create_index(
        'ix_study_attempts_mock_exam_id',
        'study_attempts',
        ['mock_exam_id'],
        unique=False,
    )

    # ---------- 学习知识点 ----------
    op.create_table(
        'learning_topics',
        sa.Column('kb_id', sa.Uuid(), nullable=False),
        sa.Column('wiki_page_id', sa.Uuid(), nullable=True),
        sa.Column('slug', sa.String(length=120), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('summary', sa.Text(), server_default='', nullable=False),
        sa.Column('domain', sa.String(length=120), server_default='', nullable=False),
        sa.Column('mastery_score', sa.Float(), server_default=sa.text('0'), nullable=False),
        sa.Column(
            'sm2_state_json',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            'prerequisite_topic_ids',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column('weak_flag', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=True),
        sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['kb_id'], ['knowledge_bases.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['wiki_page_id'], ['wiki_pages.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('kb_id', 'slug', name='uq_learning_topics_kb_slug'),
    )
    op.create_index('ix_learning_topics_kb_id', 'learning_topics', ['kb_id'], unique=False)

    # ---------- 学习计划 ----------
    op.create_table(
        'study_plans',
        sa.Column('profile_id', sa.Uuid(), nullable=False),
        sa.Column('kb_id', sa.Uuid(), nullable=False),
        sa.Column('phase', sa.String(length=20), server_default='initial', nullable=False),
        sa.Column('suggested_mode', sa.String(length=20), server_default='drill', nullable=False),
        sa.Column(
            'plan_json',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            'computed_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['profile_id'], ['study_profiles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['kb_id'], ['knowledge_bases.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('profile_id'),
    )
    op.create_index('ix_study_plans_profile_id', 'study_plans', ['profile_id'], unique=False)
    op.create_index('ix_study_plans_kb_id', 'study_plans', ['kb_id'], unique=False)

    # ---------- 联网核查日志 ----------
    op.create_table(
        'web_research_logs',
        sa.Column('question_id', sa.Uuid(), nullable=True),
        sa.Column('kb_id', sa.Uuid(), nullable=False),
        sa.Column('query', sa.Text(), server_default='', nullable=False),
        sa.Column('provider', sa.String(length=40), server_default='', nullable=False),
        sa.Column(
            'sources_json',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column('outcome', sa.String(length=20), server_default='unavailable', nullable=False),
        sa.Column(
            'verified_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['question_id'], ['study_questions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['kb_id'], ['knowledge_bases.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_web_research_logs_kb_id', 'web_research_logs', ['kb_id'], unique=False)

    # ---------- 学习批注 ----------
    op.create_table(
        'learning_annotations',
        sa.Column('kb_id', sa.Uuid(), nullable=False),
        sa.Column('target_type', sa.String(length=20), server_default='wiki', nullable=False),
        sa.Column('target_id', sa.Uuid(), nullable=False),
        sa.Column('content_md', sa.Text(), server_default='', nullable=False),
        sa.Column('quote', sa.Text(), server_default='', nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['kb_id'], ['knowledge_bases.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_learning_annotations_kb_id', 'learning_annotations', ['kb_id'], unique=False)
    op.create_index(
        'ix_learning_annotations_kb_target',
        'learning_annotations',
        ['kb_id', 'target_type', 'target_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_learning_annotations_kb_target', table_name='learning_annotations')
    op.drop_index('ix_learning_annotations_kb_id', table_name='learning_annotations')
    op.drop_table('learning_annotations')
    op.drop_index('ix_web_research_logs_kb_id', table_name='web_research_logs')
    op.drop_table('web_research_logs')
    op.drop_index('ix_study_plans_kb_id', table_name='study_plans')
    op.drop_index('ix_study_plans_profile_id', table_name='study_plans')
    op.drop_table('study_plans')
    op.drop_index('ix_learning_topics_kb_id', table_name='learning_topics')
    op.drop_table('learning_topics')

    op.drop_index('ix_study_attempts_mock_exam_id', table_name='study_attempts')
    op.drop_index('ix_study_attempts_kb_created', table_name='study_attempts')
    op.drop_constraint('fk_study_attempts_mock_exam', 'study_attempts', type_='foreignkey')
    op.drop_column('study_attempts', 'attempted_at')
    op.drop_column('study_attempts', 'mode')
    op.drop_column('study_attempts', 'score_breakdown_json')
    op.drop_column('study_attempts', 'llm_score')
    op.drop_column('study_attempts', 'user_answer')
    op.drop_column('study_attempts', 'mock_exam_id')

    op.drop_index('ix_study_questions_kb_type', table_name='study_questions')
    op.drop_column('study_questions', 'cache_status')
    op.drop_column('study_questions', 'confidence_level')
    op.drop_column('study_questions', 'web_sources_json')
    op.drop_column('study_questions', 'source_hash')
    op.drop_column('study_questions', 'answer_json')
    op.drop_column('study_questions', 'body_json')
    op.drop_column('study_questions', 'question_type')
    op.drop_column('study_questions', 'topic_slug')

    op.drop_index('ix_mock_exam_items_question_id', table_name='mock_exam_items')
    op.drop_index('ix_mock_exam_items_mock_exam_id', table_name='mock_exam_items')
    op.drop_table('mock_exam_items')
    op.drop_index('ix_mock_exams_kb_created', table_name='mock_exams')
    op.drop_index('ix_mock_exams_kb_id', table_name='mock_exams')
    op.drop_table('mock_exams')

    op.drop_constraint('fk_study_profiles_exam_template', 'study_profiles', type_='foreignkey')
    op.drop_column('study_profiles', 'onboarded')
    op.drop_column('study_profiles', 'profile_json')
    op.drop_column('study_profiles', 'weak_areas')
    op.drop_column('study_profiles', 'preferred_mode')
    op.drop_column('study_profiles', 'target_date')
    op.drop_column('study_profiles', 'exam_template_id')

    op.drop_index('ix_exam_templates_kb_code', table_name='exam_templates')
    op.drop_table('exam_templates')
