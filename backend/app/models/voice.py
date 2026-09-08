from uuid import uuid4

from sqlmodel import Field, SQLModel


class Voice(SQLModel, table=True):
    __tablename__ = "voices"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    speaker_label: str
    engine: str  # "edge_tts" | "gemini_tts"
    voice_id: str
    speed: float = Field(default=1.0)
    pitch: float = Field(default=0.0)
