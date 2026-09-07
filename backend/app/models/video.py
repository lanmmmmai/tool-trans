from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlmodel import Field, SQLModel


class Video(SQLModel, table=True):
    __tablename__ = "videos"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    source_type: str  # "upload" | "youtube" | "tiktok"
    source_url: Optional[str] = None
    storage_path: str
    duration_sec: float
    resolution: str
    codec: str
    file_size_bytes: int
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
