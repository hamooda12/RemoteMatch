from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CVParseStatus(StrEnum):
    PENDING = "pending"
    PROCESSED = "processed"
    FAILED = "failed"


class CVDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    original_filename: str
    media_type: str
    size_bytes: int
    parse_status: CVParseStatus
    created_at: datetime
    updated_at: datetime
