from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.core.auth import get_current_user_id
from app.db.session import get_session
from app.models.job import Job
from app.models.project import Project
from app.workers.dub import dub_task

router = APIRouter(prefix="/api/projects", tags=["dub"])


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


@router.post("/{project_id}/dub", response_model=JobRead, status_code=202)
def start_dub(
    project_id: str,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    project = session.get(Project, project_id)
    if project is None or project.user_id != user_id:
        raise HTTPException(status_code=404, detail="Project not found")

    job = Job(project_id=project_id, job_type="dub")
    session.add(job)
    project.status = "dubbing"
    project.updated_at = datetime.now(timezone.utc)
    session.add(project)
    session.commit()
    session.refresh(job)

    dub_task.delay(project_id=project_id)

    return job
