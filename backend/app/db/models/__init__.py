"""数据模型注册：供 Alembic 与业务导入。"""

from app.db.models.attachment import NoteAttachment
from app.db.models.collection_row import CollectionRow
from app.db.models.import_batch import ImportBatch
from app.db.models.ingest_job import IngestJob
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.llm_config import LLMConfig
from app.db.models.notes import (
    Note,
    NoteFolder,
    NoteLink,
    NoteTag,
    NoteTagLink,
    NoteTemplate,
)
from app.db.models.notes_collection import NoteCollection
from app.db.models.sources import Source
from app.db.models.study import (
    ExamTemplate,
    LearningAnnotation,
    LearningTopic,
    MockExam,
    MockExamItem,
    StudyAttempt,
    StudyPlan,
    StudyProfile,
    StudyQuestion,
    StudyReview,
    StudySession,
    WebResearchLog,
)
from app.db.models.wiki import WikiLink, WikiLintReport, WikiPage

__all__ = [
    "KnowledgeBase",
    "Source",
    "Note",
    "NoteFolder",
    "NoteTag",
    "NoteTagLink",
    "NoteTemplate",
    "NoteLink",
    "NoteCollection",
    "CollectionRow",
    "NoteAttachment",
    "WikiPage",
    "WikiLink",
    "WikiLintReport",
    "LLMConfig",
    "IngestJob",
    "ImportBatch",
    "StudyProfile",
    "StudySession",
    "StudyQuestion",
    "StudyAttempt",
    "StudyReview",
    "ExamTemplate",
    "StudyPlan",
    "LearningTopic",
    "MockExam",
    "MockExamItem",
    "WebResearchLog",
    "LearningAnnotation",
]
