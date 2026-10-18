"""附件 schemas。"""

import uuid
from datetime import datetime

from pydantic import BaseModel


class AttachmentOut(BaseModel):
    id: uuid.UUID
    kb_id: uuid.UUID
    note_id: uuid.UUID | None
    filename: str
    content_type: str
    size: int
    url: str
    created_at: datetime
