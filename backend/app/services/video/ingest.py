import os

from sqlmodel import Session

from app.core.storage import R2Client
from app.models.video import Video
from app.services.video.ffprobe import probe_video

MAX_DURATION_SEC = 60 * 60
MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024 * 1024


class VideoValidationError(Exception):
    pass


def ingest_video_file(
    session: Session,
    r2_client: R2Client,
    project_id: str,
    local_path: str,
    source_type: str,
    source_url: str | None = None,
) -> Video:
    metadata = probe_video(local_path)

    if metadata.duration_sec > MAX_DURATION_SEC:
        raise VideoValidationError(
            f"Video is {metadata.duration_sec / 60:.1f} minutes; max is 60 minutes."
        )
    if metadata.file_size_bytes > MAX_FILE_SIZE_BYTES:
        raise VideoValidationError(
            f"Video is {metadata.file_size_bytes / (1024**3):.2f} GB; max size is 2 GB."
        )

    key = f"videos/{project_id}/{os.path.basename(local_path)}"
    r2_client.upload_file(local_path, key)

    video = Video(
        project_id=project_id,
        source_type=source_type,
        source_url=source_url,
        storage_path=key,
        duration_sec=metadata.duration_sec,
        resolution=metadata.resolution,
        codec=metadata.codec,
        file_size_bytes=metadata.file_size_bytes,
    )
    session.add(video)
    session.commit()
    session.refresh(video)
    return video
