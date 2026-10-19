"""数据模型注册：供 Alembic 与业务导入。"""

from app.db.models.attachment import NoteAttachment
from app.db.models.chat import ChatSession
from app.db.models.collection_row import CollectionRow
from app.db.models.embedding_config import EmbeddingConfig
from app.db.models.import_batch import ImportBatch
from app.db.models.ingest_job import IngestJob
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.llm_config import LLMConfig
from app.db.models.note_revision import NoteRevision
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
from app.db.models.system_settings import SystemSettings
from app.db.models.todo_mirror import TodoMirror
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
    "ChatSession",
    "Note",
    "NoteFolder",
    "NoteTag",
    "NoteTagLink",
    "NoteTemplate",
    "NoteLink",
    "NoteRevision",
    "NoteCollection",
    "SystemSettings",
    "TodoMirror",
    "CollectionRow",
    "NoteAttachment",
    "WikiPage",
    "WikiLink",
    "WikiLintReport",
    "LLMConfig",
    "EmbeddingConfig",
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
