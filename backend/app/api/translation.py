from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.auth import get_current_user_id
from app.db.session import get_session
from app.models.job import Job
from app.models.project import Project
from app.models.transcript_segment import TranscriptSegment
from app.models.translation_segment import TranslationSegment
from app.workers.translate import translate_task

router = APIRouter(prefix="/api/projects", tags=["translation"])


class JobRead(BaseModel):
    id: str
    project_id: str
    job_type: str
    status: str
    progress_pct: float
    current_step: str | None
    error_message: str | None

    class Config:
        from_attributes = True


class StartTranslateRequest(BaseModel):
    engine: str  # "gemini" | "openai"


class TranslationSegmentRead(BaseModel):
    id: str
    segment_id: str
    seq_index: int
    start_time: float
    end_time: float
    speaker_label: str
    source_text: str
    translated_text: str
    translated_text_edited: str | None


class TranslationSegmentUpdate(BaseModel):
    translated_text_edited: str


def _get_owned_project(session: Session, project_id: str, user_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None or project.user_id != user_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("/{project_id}/translate", response_model=JobRead, status_code=202)
def start_translate(
    project_id: str,
    payload: StartTranslateRequest,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    project = _get_owned_project(session, project_id, user_id)

    project.translate_engine = payload.engine
    project.status = "translating"
    project.updated_at = datetime.now(timezone.utc)
    session.add(project)

    job = Job(project_id=project_id, job_type="translate")
    session.add(job)
    session.commit()
    session.refresh(job)

    translate_task.delay(project_id=project_id, engine_name=payload.engine)

    return job


@router.get("/{project_id}/translation", response_model=list[TranslationSegmentRead])
def get_translation(
    project_id: str,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    _get_owned_project(session, project_id, user_id)

    rows = session.exec(
        select(TranscriptSegment, TranslationSegment)
        .join(TranslationSegment, TranslationSegment.segment_id == TranscriptSegment.id)
        .where(TranscriptSegment.project_id == project_id)
        .order_by(TranscriptSegment.seq_index)
    ).all()

    return [
        TranslationSegmentRead(
            id=translation.id,
            segment_id=transcript.id,
            seq_index=transcript.seq_index,
            start_time=transcript.start_time,
            end_time=transcript.end_time,
            speaker_label=transcript.speaker_label,
            source_text=transcript.source_text_edited or transcript.source_text,
            translated_text=translation.translated_text,
            translated_text_edited=translation.translated_text_edited,
        )
        for transcript, translation in rows
    ]


@router.patch(
    "/{project_id}/translation/{translation_id}", response_model=TranslationSegmentRead
)
def update_translation_segment(
    project_id: str,
    translation_id: str,
    payload: TranslationSegmentUpdate,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    _get_owned_project(session, project_id, user_id)

    translation = session.get(TranslationSegment, translation_id)
    if translation is None:
        raise HTTPException(status_code=404, detail="Translation segment not found")
    transcript = session.get(TranscriptSegment, translation.segment_id)
    if transcript is None or transcript.project_id != project_id:
        raise HTTPException(status_code=404, detail="Translation segment not found")

    translation.translated_text_edited = payload.translated_text_edited
    session.add(translation)
    session.commit()
    session.refresh(translation)

    return TranslationSegmentRead(
        id=translation.id,
        segment_id=transcript.id,
        seq_index=transcript.seq_index,
        start_time=transcript.start_time,
        end_time=transcript.end_time,
        speaker_label=transcript.speaker_label,
        source_text=transcript.source_text_edited or transcript.source_text,
        translated_text=translation.translated_text,
        translated_text_edited=translation.translated_text_edited,
    )
