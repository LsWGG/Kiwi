"""各实体 repository。"""

import uuid

from sqlalchemy import func, select

from app.db.models import (
    ExamTemplate,
    KnowledgeBase,
    LearningAnnotation,
    LearningTopic,
    MockExam,
    MockExamItem,
    Note,
    NoteTag,
    Source,
    StudyAttempt,
    StudyPlan,
    StudyProfile,
    StudyQuestion,
    StudyReview,
    StudySession,
    WebResearchLog,
    WikiPage,
)
from app.repositories.base import BaseRepo


class KBRepo(BaseRepo):
    entity = KnowledgeBase

    async def list_all(self):
        stmt = select(self.entity).order_by(self.entity.created_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())


class SourceRepo(BaseRepo):
    entity = Source


class NoteRepo(BaseRepo):
    entity = Note


class NoteTagRepo(BaseRepo):
    entity = NoteTag


class WikiPageRepo(BaseRepo):
    entity = WikiPage

    async def get_by_slug(self, kb_id, slug):
        stmt = select(self.entity).where(self.entity.kb_id == kb_id, self.entity.slug == slug)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def upsert(self, kb_id, slug, **values):
        """存在则更新，否则新建；尊重 human_edited 保护。"""
        obj = await self.get_by_slug(kb_id, slug)
        if obj is None:
            obj = self.entity(kb_id=kb_id, slug=slug, **values)
            self.session.add(obj)
        elif not getattr(obj, "human_edited", False):
            for k, v in values.items():
                setattr(obj, k, v)
            obj.version = (obj.version or 1) + 1
        await self.session.flush()
        return obj


class StudyProfileRepo(BaseRepo):
    entity = StudyProfile

    async def get_by_kb(self, kb_id):
        stmt = select(self.entity).where(self.entity.kb_id == kb_id)
        return (await self.session.execute(stmt)).scalars().first()

    async def get_or_create(self, kb_id):
        obj = await self.get_by_kb(kb_id)
        if obj is None:
            obj = self.entity(kb_id=kb_id)
            self.session.add(obj)
            await self.session.flush()
        return obj

    async def update_mastery(self, kb_id, slug: str, score: float) -> StudyProfile:
        """EMA 合并写入掌握度聚合：{slug: score}。"""
        profile = await self.get_or_create(kb_id)
        mastery = dict(profile.mastery or {})
        mastery[slug] = round(float(score), 4)
        profile.mastery = mastery
        await self.session.flush()
        return profile


class StudySessionRepo(BaseRepo):
    entity = StudySession

    async def create(
        self,
        kb_id,
        mode: str = "drill",
        topic_slug: str | None = None,
        last_question_id=None,
    ) -> StudySession:
        obj = self.entity(
            kb_id=kb_id,
            mode=mode,
            topic_slug=topic_slug,
            last_question_id=last_question_id,
            status="in_progress",
        )
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def finish(self, kb_id, session_id, correct_count, question_count):
        from datetime import datetime, timezone

        obj = await self.get(kb_id, session_id)
        obj.status = "completed"
        obj.correct_count = correct_count
        obj.question_count = question_count
        obj.finished_at = datetime.now(timezone.utc)
        await self.session.flush()
        return obj

    async def get_latest_active(self, kb_id) -> StudySession | None:
        """最近一组未完成会话（继续学习入口）。"""
        stmt = (
            select(self.entity)
            .where(self.entity.kb_id == kb_id, self.entity.status == "in_progress")
            .order_by(self.entity.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()


class StudyQuestionRepo(BaseRepo):
    entity = StudyQuestion

    async def find_by_fingerprint(self, kb_id, fingerprint: str) -> StudyQuestion | None:
        stmt = select(self.entity).where(
            self.entity.kb_id == kb_id, self.entity.fingerprint == fingerprint
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def save(
        self,
        kb_id,
        wiki_page_id,
        fingerprint,
        question_json,
        difficulty,
        **extra,
    ) -> StudyQuestion:
        obj = self.entity(
            kb_id=kb_id,
            wiki_page_id=wiki_page_id,
            fingerprint=fingerprint,
            question_json=question_json,
            difficulty=difficulty,
            **extra,
        )
        self.session.add(obj)
        await self.session.flush()
        return obj


class StudyAttemptRepo(BaseRepo):
    entity = StudyAttempt

    async def create(
        self,
        kb_id,
        session_id,
        question_id,
        correct: bool,
        selected_index: int,
        time_ms: int,
        **extra,
    ) -> StudyAttempt:
        obj = self.entity(
            kb_id=kb_id,
            session_id=session_id,
            question_id=question_id,
            correct=correct,
            selected_index=selected_index,
            time_ms=time_ms,
            **extra,
        )
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def counts_for_session(self, session_id) -> tuple[int, int]:
        """会话作答统计：(答对数, 已答数)。"""
        flags = (
            await self.session.execute(
                select(self.entity.correct).where(self.entity.session_id == session_id)
            )
        ).scalars().all()
        return sum(1 for f in flags if f), len(flags)

    async def list_wrong(self, kb_id, question_ids: list[uuid.UUID] | None = None):
        """错题列表：join question 按 kb 过滤 + 可选 question_id 过滤。"""
        stmt = (
            select(self.entity, StudyQuestion)
            .join(StudyQuestion, self.entity.question_id == StudyQuestion.id)
            .where(self.entity.kb_id == kb_id, self.entity.correct.is_(False))
        )
        if question_ids:
            stmt = stmt.where(self.entity.question_id.in_(question_ids))
        stmt = stmt.order_by(self.entity.created_at.desc())
        return list((await self.session.execute(stmt)).all())


class StudyReviewRepo(BaseRepo):
    entity = StudyReview

    async def get_by_slug(self, kb_id, slug: str) -> StudyReview | None:
        stmt = select(self.entity).where(
            self.entity.kb_id == kb_id, self.entity.slug == slug
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def get_or_create(
        self, kb_id, slug: str, wiki_page_id=None
    ) -> StudyReview:
        obj = await self.get_by_slug(kb_id, slug)
        if obj is None:
            obj = self.entity(
                kb_id=kb_id, slug=slug, wiki_page_id=wiki_page_id
            )
            self.session.add(obj)
            await self.session.flush()
        elif wiki_page_id is not None and obj.wiki_page_id is None:
            obj.wiki_page_id = wiki_page_id
            await self.session.flush()
        return obj

    async def list_due(self, kb_id, now, limit: int = 50):
        """到期待复习项（join WikiPage 取标题），按到期时间升序。"""
        from sqlalchemy import and_

        stmt = (
            select(self.entity, WikiPage)
            .join(
                WikiPage,
                and_(
                    self.entity.wiki_page_id == WikiPage.id,
                    WikiPage.kb_id == kb_id,
                ),
            )
            .where(
                self.entity.kb_id == kb_id,
                self.entity.due_at <= now,
            )
            .order_by(self.entity.due_at.asc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).all())

    async def next_due_at(self, kb_id, now):
        """最近一次未来到期时间（用于「今日已完成」提示）。"""
        stmt = (
            select(func.min(self.entity.due_at)).where(
                self.entity.kb_id == kb_id,
                self.entity.due_at > now,
            )
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


class ExamTemplateRepo(BaseRepo):
    entity = ExamTemplate

    async def list_for_kb(self, kb_id):
        """内置（kb_id is null）+ 当前知识库自定义模板。"""
        stmt = (
            select(self.entity)
            .where((self.entity.kb_id == kb_id) | (self.entity.kb_id.is_(None)))
            .order_by(self.entity.is_builtin.desc(), self.entity.created_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_for_kb(self, kb_id, template_id):
        stmt = select(self.entity).where(
            self.entity.id == template_id,
            (self.entity.kb_id == kb_id) | (self.entity.kb_id.is_(None)),
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def get_builtin_by_code(self, code: str):
        stmt = select(self.entity).where(
            self.entity.code == code, self.entity.is_builtin.is_(True)
        )
        return (await self.session.execute(stmt)).scalars().first()


class StudyPlanRepo(BaseRepo):
    entity = StudyPlan

    async def get_by_profile(self, profile_id):
        stmt = select(self.entity).where(self.entity.profile_id == profile_id)
        return (await self.session.execute(stmt)).scalars().first()


class LearningTopicRepo(BaseRepo):
    entity = LearningTopic

    async def list_for_kb(self, kb_id, active_only: bool = True):
        stmt = select(self.entity).where(self.entity.kb_id == kb_id)
        if active_only:
            stmt = stmt.where(self.entity.active.is_(True))
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_by_slug(self, kb_id, slug):
        stmt = select(self.entity).where(
            self.entity.kb_id == kb_id, self.entity.slug == slug
        )
        return (await self.session.execute(stmt)).scalars().first()


class MockExamRepo(BaseRepo):
    entity = MockExam

    async def list_for_kb(self, kb_id, limit: int = 50):
        stmt = (
            select(self.entity)
            .where(self.entity.kb_id == kb_id)
            .order_by(self.entity.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())


class MockExamItemRepo(BaseRepo):
    entity = MockExamItem

    async def list_for_exam(self, exam_id):
        stmt = (
            select(self.entity)
            .where(self.entity.mock_exam_id == exam_id)
            .order_by(self.entity.order_index.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())


class WebResearchLogRepo(BaseRepo):
    entity = WebResearchLog


class LearningAnnotationRepo(BaseRepo):
    entity = LearningAnnotation

    async def list_for_target(self, kb_id, target_type, target_id):
        stmt = (
            select(self.entity)
            .where(
                self.entity.kb_id == kb_id,
                self.entity.target_type == target_type,
                self.entity.target_id == target_id,
            )
            .order_by(self.entity.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())


__all__ = [
    "BaseRepo",
    "KBRepo",
    "SourceRepo",
    "NoteRepo",
    "NoteTagRepo",
    "WikiPageRepo",
    "StudyProfileRepo",
    "StudySessionRepo",
    "StudyQuestionRepo",
    "StudyAttemptRepo",
    "StudyReviewRepo",
    "ExamTemplateRepo",
    "StudyPlanRepo",
    "LearningTopicRepo",
    "MockExamRepo",
    "MockExamItemRepo",
    "WebResearchLogRepo",
    "LearningAnnotationRepo",
]
