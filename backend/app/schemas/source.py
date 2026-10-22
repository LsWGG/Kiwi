"""素材 / 导入 schemas。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kb_id: uuid.UUID
    type: str
    title: str
    raw_path: str
    status: str
    parse_quality: str
    parse_engine: str
    quality_report: dict = Field(default_factory=dict)
    scan_status: str
    scan_detail: str
    import_batch_id: str | None = None
    external_id: str | None = None
    source_url: str = ""
    content_updated_at: datetime | None = None
    parsed_at: datetime | None = None
    sha256: str
    created_at: datetime


class SourcePreviewOut(BaseModel):
    """素材原文预览：引用块「查看原文」目标页数据。"""

    id: uuid.UUID
    kb_id: uuid.UUID
    title: str
    type: str
    sha256: str
    source_url: str = ""
    parse_quality: str
    parse_engine: str
    text: str
    truncated: bool = False


class IngestJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kb_id: uuid.UUID
    source_id: uuid.UUID
    kind: str
    status: str
    progress: float
    error: str | None
    touched_page_ids: list
    import_batch_id: str | None = None
    note_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime | None = None
    # 列表/详情展示用的关联信息
    source_title: str | None = None
    source_type: str | None = None
    note_title: str | None = None
    touched_pages: list[dict] = Field(default_factory=list)
    # 持久化队列中的任务 id，供编译页直接取消 / 重试
    durable_job_id: uuid.UUID | None = None


class ImportBatchOut(BaseModel):
    """导入批次概览与报告。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kb_id: uuid.UUID
    provider: str
    status: str
    total_sources: int
    processed_count: int
    failed_count: int
    skipped_count: int
    report_json: dict = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class BatchCreateRequest(BaseModel):
    provider: str = "upload"
    label: str = ""
    expected_count: int = 0


class YuqueTokenRequest(BaseModel):
    token: str = Field(min_length=1)
    repo: str = Field(min_length=1)
    compile_now: bool = False
    folder_id: uuid.UUID | None = None
    create_notes: bool = True


class YuqueReposRequest(BaseModel):
    """令牌换取知识库列表；令牌放在请求体，避免进入访问日志。"""

    token: str = Field(min_length=1)


class ChunkInitRequest(BaseModel):
    filename: str
    size: int
    sha256: str = ""


class ChunkCompleteRequest(BaseModel):
    compile_now: bool = False
    title: str | None = None


class CompileRequest(BaseModel):
    """触发编译请求。"""

    source_ids: list[uuid.UUID] | None = None  # None = 全部未编译素材
