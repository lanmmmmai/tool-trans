import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models.project import Project
from app.services.video.ingest import VideoValidationError, ingest_video_file

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.mp4"


@pytest.fixture(autouse=True)
def ensure_fixture():
    if not FIXTURE.exists():
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                "-shortest",
                str(FIXTURE),
            ],
            check=True,
        )


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def project(session):
    p = Project(
        user_id="user-1",
        title="t",
        source_language="en",
        target_language="vi",
        audio_mode="ducking",
    )
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def test_ingest_video_file_creates_video_row(session, project):
    mock_r2 = MagicMock()
    mock_r2.upload_file.side_effect = lambda local_path, key: key

    video = ingest_video_file(
        session=session,
        r2_client=mock_r2,
        project_id=project.id,
        local_path=str(FIXTURE),
        source_type="upload",
    )

    assert video.project_id == project.id
    assert video.resolution == "320x240"
    assert video.storage_path.startswith(f"videos/{project.id}/")
    mock_r2.upload_file.assert_called_once()


def test_ingest_video_file_rejects_video_over_60_minutes(session, project, monkeypatch):
    from app.services.video import ingest as ingest_module
    from app.services.video.ffprobe import VideoProbeResult

    monkeypatch.setattr(
        ingest_module,
        "probe_video",
        lambda path: VideoProbeResult(
            duration_sec=3601, resolution="1920x1080", codec="h264", file_size_bytes=100
        ),
    )
    mock_r2 = MagicMock()

    with pytest.raises(VideoValidationError, match="60"):
        ingest_video_file(
            session=session,
            r2_client=mock_r2,
            project_id=project.id,
            local_path=str(FIXTURE),
            source_type="upload",
        )
    mock_r2.upload_file.assert_not_called()


def test_ingest_video_file_rejects_file_over_2gb(session, project, monkeypatch):
    from app.services.video import ingest as ingest_module
    from app.services.video.ffprobe import VideoProbeResult

    monkeypatch.setattr(
        ingest_module,
        "probe_video",
        lambda path: VideoProbeResult(
            duration_sec=60,
            resolution="1920x1080",
            codec="h264",
            file_size_bytes=2 * 1024 * 1024 * 1024 + 1,
        ),
    )
    mock_r2 = MagicMock()

    with pytest.raises(VideoValidationError, match="2 ?GB|size"):
        ingest_video_file(
            session=session,
            r2_client=mock_r2,
            project_id=project.id,
            local_path=str(FIXTURE),
            source_type="upload",
        )
    mock_r2.upload_file.assert_not_called()
