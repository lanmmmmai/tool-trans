from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.auth import get_current_user_id
from app.db.session import get_session
from app.models.project import Project
from app.models.voice import Voice

router = APIRouter(prefix="/api/projects", tags=["voices"])


class VoiceAssignment(BaseModel):
    speaker_label: str
    engine: str
    voice_id: str
    speed: float = 1.0
    pitch: float = 0.0


class VoiceRead(BaseModel):
    id: str
    project_id: str
    speaker_label: str
    engine: str
    voice_id: str
    speed: float
    pitch: float

    class Config:
        from_attributes = True


def _get_owned_project(session: Session, project_id: str, user_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None or project.user_id != user_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/{project_id}/voices", response_model=list[VoiceRead])
def get_project_voices(
    project_id: str,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    _get_owned_project(session, project_id, user_id)
    return session.exec(select(Voice).where(Voice.project_id == project_id)).all()


@router.put("/{project_id}/voices", response_model=list[VoiceRead])
def set_project_voices(
    project_id: str,
    payload: list[VoiceAssignment],
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    _get_owned_project(session, project_id, user_id)

    existing = session.exec(select(Voice).where(Voice.project_id == project_id)).all()
    for voice in existing:
        session.delete(voice)
    session.commit()

    created = []
    for assignment in payload:
        voice = Voice(project_id=project_id, **assignment.model_dump())
        session.add(voice)
        created.append(voice)
    session.commit()
    for voice in created:
        session.refresh(voice)

    return created
