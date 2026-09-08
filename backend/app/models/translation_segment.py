from typing import Optional
from uuid import uuid4

from sqlmodel import Field, SQLModel


class TranslationSegment(SQLModel, table=True):
    __tablename__ = "translation_segments"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    segment_id: str = Field(foreign_key="transcript_segments.id", unique=True, index=True)
    translated_text: str
    translated_text_edited: Optional[str] = None
