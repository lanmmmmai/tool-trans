import os
import tempfile
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.auth import get_current_user_id
from app.core.storage import get_r2_client
from app.db.session import get_session
from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from app.services.video.downloader import download_from_url
from app.services.video.ingest import VideoValidationError, ingest_video_file

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ImportUrlRequest(BaseModel):
    url: str


class VideoRead(BaseModel):
    id: str
    project_id: str
    source_type: str
    source_url: str | None
    storage_path: str
    duration_sec: float
    resolution: str
    codec: str
    file_size_bytes: int

    class Config:
        from_attributes = True


def _get_owned_project(session: Session, project_id: str, user_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None or project.user_id != user_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("", response_model=ProjectRead, status_code=201)
def create_project(
    payload: ProjectCreate,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    project = Project(user_id=user_id, **payload.model_dump())
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


@router.get("", response_model=list[ProjectRead])
def list_projects(
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    return session.exec(select(Project).where(Project.user_id == user_id)).all()


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(
    project_id: str,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    return _get_owned_project(session, project_id, user_id)


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    project = _get_owned_project(session, project_id, user_id)

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(project, field, value)
    project.updated_at = datetime.now(timezone.utc)

    session.add(project)
    session.commit()
    session.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: str,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    project = _get_owned_project(session, project_id, user_id)
    session.delete(project)
    session.commit()


@router.post("/{project_id}/upload", response_model=VideoRead, status_code=201)
def upload_video(
    project_id: str,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    _get_owned_project(session, project_id, user_id)

    if not (file.content_type or "").startswith("video/"):
        raise HTTPException(status_code=400, detail="File must be a video")

    with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{file.filename}") as tmp:
        tmp.write(file.file.read())
        tmp_path = tmp.name

    try:
        video = ingest_video_file(
            session=session,
            r2_client=get_r2_client(),
            project_id=project_id,
            local_path=tmp_path,
            source_type="upload",
        )
    except VideoValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        os.remove(tmp_path)

    return video


@router.post("/{project_id}/import-url", response_model=VideoRead, status_code=201)
def import_video_from_url(
    project_id: str,
    payload: ImportUrlRequest,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    _get_owned_project(session, project_id, user_id)

    with tempfile.TemporaryDirectory() as dest_dir:
        local_path = download_from_url(payload.url, dest_dir)
        try:
            video = ingest_video_file(
                session=session,
                r2_client=get_r2_client(),
                project_id=project_id,
                local_path=local_path,
                source_type="youtube" if "youtube" in payload.url or "youtu.be" in payload.url else "tiktok",
                source_url=payload.url,
            )
        except VideoValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return video
