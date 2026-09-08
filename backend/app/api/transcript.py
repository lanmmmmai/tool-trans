from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.auth import get_current_user_id
from app.db.session import get_session
from app.models.job import Job
from app.models.project import Project
from app.models.transcript_segment import TranscriptSegment
from app.workers.transcribe import transcribe_task

router = APIRouter(prefix="/api/projects", tags=["transcript"])


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


class TranscriptSegmentRead(BaseModel):
    id: str
    project_id: str
    seq_index: int
    start_time: float
    end_time: float
    speaker_label: str
    source_text: str
    source_text_edited: str | None
    confidence: float | None

    class Config:
        from_attributes = True


def _get_owned_project(session: Session, project_id: str, user_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None or project.user_id != user_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("/{project_id}/transcribe", response_model=JobRead, status_code=202)
def start_transcribe(
    project_id: str,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    project = _get_owned_project(session, project_id, user_id)

    job = Job(project_id=project.id, job_type="transcribe")
    session.add(job)
    project.status = "transcribing"
    project.updated_at = datetime.now(timezone.utc)
    session.add(project)
    session.commit()
    session.refresh(job)

    transcribe_task.delay(project_id=project_id)

    return job


@router.get("/{project_id}/transcript", response_model=list[TranscriptSegmentRead])
def get_transcript(
    project_id: str,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    _get_owned_project(session, project_id, user_id)
    return session.exec(
        select(TranscriptSegment)
        .where(TranscriptSegment.project_id == project_id)
        .order_by(TranscriptSegment.seq_index)
    ).all()


class TranscriptSegmentUpdate(BaseModel):
    source_text_edited: str


@router.patch("/{project_id}/transcript/{segment_id}", response_model=TranscriptSegmentRead)
def update_transcript_segment(
    project_id: str,
    segment_id: str,
    payload: TranscriptSegmentUpdate,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    _get_owned_project(session, project_id, user_id)

    segment = session.get(TranscriptSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        raise HTTPException(status_code=404, detail="Segment not found")

    segment.source_text_edited = payload.source_text_edited
    session.add(segment)
    session.commit()
    session.refresh(segment)
    return segment
