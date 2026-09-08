from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    title: str
    source_language: str
    target_language: str
    audio_mode: str
    translate_engine: Optional[str] = None


class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    source_language: Optional[str] = None
    target_language: Optional[str] = None
    audio_mode: Optional[str] = None
    background_volume: Optional[float] = None
    translate_engine: Optional[str] = None
    status: Optional[str] = None


class ProjectRead(BaseModel):
    id: str
    user_id: str
    title: str
    source_language: str
    target_language: str
    status: str
    audio_mode: str
    background_volume: float
    translate_engine: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
