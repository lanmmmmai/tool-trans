from unittest.mock import MagicMock, patch

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.job import Job
from app.models.project import Project
from app.models.transcript_segment import TranscriptSegment
from app.models.video import Video
from app.services.stt.base import STTSegment


def make_engine():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine


def seed_project_with_video(session):
    project = Project(
        user_id="u1", title="t", source_language="en", target_language="vi", audio_mode="ducking"
    )
    session.add(project)
    session.commit()
    session.refresh(project)

    video = Video(
        project_id=project.id,
        source_type="upload",
        storage_path="videos/x/tiny.mp4",
        duration_sec=2.0,
        resolution="320x240",
        codec="h264",
        file_size_bytes=100,
    )
    session.add(video)
    session.commit()

    job = Job(project_id=project.id, job_type="transcribe")
    session.add(job)
    session.commit()
    session.refresh(job)

    return project, video, job


def test_transcribe_task_writes_segments_and_marks_job_done():
    engine = make_engine()
    with Session(engine) as session:
        project, video, job = seed_project_with_video(session)
        project_id, job_id = project.id, job.id

    fake_segments = [
        STTSegment(start=0.0, end=1.0, speaker_label="speaker_1", text="Hello"),
        STTSegment(start=1.0, end=2.0, speaker_label="speaker_2", text="Hi there"),
    ]

    with patch("app.workers.transcribe.get_session_for_worker", return_value=Session(engine)), patch(
        "app.workers.transcribe.get_r2_client"
    ) as mock_get_r2, patch("app.workers.transcribe.extract_audio"), patch(
        "app.workers.transcribe.transcribe_with_fallback",
        return_value=(fake_segments, "elevenlabs"),
    ), patch("app.workers.transcribe.broadcast_sync") as mock_broadcast:
        mock_get_r2.return_value.download_file = MagicMock()

        from app.workers.transcribe import transcribe_task

        transcribe_task.run(project_id=project_id)

    with Session(engine) as session:
        refreshed_job = session.get(Job, job_id)
        assert refreshed_job.status == "done"
        assert refreshed_job.progress_pct == 100

        segments = session.exec(
            select(TranscriptSegment).where(TranscriptSegment.project_id == project_id)
        ).all()
        assert len(segments) == 2
        assert segments[0].source_text == "Hello"
        assert segments[1].speaker_label == "speaker_2"

    assert mock_broadcast.called


def test_transcribe_task_marks_job_failed_on_exception():
    engine = make_engine()
    with Session(engine) as session:
        project, video, job = seed_project_with_video(session)
        project_id, job_id = project.id, job.id

    with patch("app.workers.transcribe.get_session_for_worker", return_value=Session(engine)), patch(
        "app.workers.transcribe.get_r2_client"
    ), patch("app.workers.transcribe.extract_audio", side_effect=RuntimeError("boom")), patch(
        "app.workers.transcribe.broadcast_sync"
    ):
        from app.workers.transcribe import transcribe_task

        transcribe_task.run(project_id=project_id)

    with Session(engine) as session:
        refreshed_job = session.get(Job, job_id)
        assert refreshed_job.status == "failed"
        assert "boom" in refreshed_job.error_message
