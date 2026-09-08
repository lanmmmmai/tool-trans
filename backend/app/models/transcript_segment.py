from typing import Optional
from uuid import uuid4

from sqlmodel import Field, SQLModel


class TranscriptSegment(SQLModel, table=True):
    __tablename__ = "transcript_segments"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    seq_index: int
    start_time: float
    end_time: float
    speaker_label: str
    source_text: str
    source_text_edited: Optional[str] = None
    confidence: Optional[float] = None
