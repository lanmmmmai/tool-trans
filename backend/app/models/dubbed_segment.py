from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlmodel import Field, SQLModel


class DubbedSegment(SQLModel, table=True):
    __tablename__ = "dubbed_segments"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    segment_id: str = Field(foreign_key="transcript_segments.id", unique=True, index=True)
    audio_storage_path: str
    duration_sec: float
    status: str = Field(default="pending")  # "pending" | "done" | "failed"
    generated_at: Optional[datetime] = None
