from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.dubbed_segment import DubbedSegment
from app.models.job import Job
from app.models.project import Project
from app.models.transcript_segment import TranscriptSegment
from app.models.translation_segment import TranslationSegment
from app.models.voice import Voice
from app.services.tts.base import TTSProviderError


def make_engine():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine


def seed(session):
    project = Project(
        user_id="u1", title="t", source_language="en", target_language="vi", audio_mode="ducking"
    )
    session.add(project)
    session.commit()
    session.refresh(project)

    seg = TranscriptSegment(
        project_id=project.id, seq_index=0, start_time=0, end_time=2,
        speaker_label="speaker_1", source_text="Hello",
    )
    session.add(seg)
    session.commit()
    session.refresh(seg)

    session.add(TranslationSegment(segment_id=seg.id, translated_text="Xin chào"))
    session.add(Voice(project_id=project.id, speaker_label="speaker_1", engine="edge_tts", voice_id="vi-VN-HoaiMyNeural"))

    job = Job(project_id=project.id, job_type="dub")
    session.add(job)
    session.commit()
    session.refresh(job)

    project_id, job_id = project.id, job.id
    return project_id, job_id


def test_dub_task_creates_dubbed_segment_and_marks_job_done():
    engine = make_engine()
    with Session(engine) as session:
        project_id, job_id = seed(session)

    with patch("app.workers.dub.get_session_for_worker", return_value=Session(engine)), patch(
        "app.workers.dub.get_r2_client"
    ), patch("app.workers.dub.synthesize_segment_with_rate_adjustment", return_value=1.9), patch(
        "app.workers.dub.broadcast_sync"
    ):
        from app.workers.dub import dub_task

        dub_task.run(project_id=project_id)

    with Session(engine) as session:
        refreshed_job = session.get(Job, job_id)
        assert refreshed_job.status == "done"

        dubbed = session.exec(select(DubbedSegment)).all()
        assert len(dubbed) == 1
        assert dubbed[0].duration_sec == 1.9
        assert dubbed[0].status == "done"


def test_dub_task_fails_fast_without_auto_fallback_on_tts_error():
    engine = make_engine()
    with Session(engine) as session:
        project_id, job_id = seed(session)

    with patch("app.workers.dub.get_session_for_worker", return_value=Session(engine)), patch(
        "app.workers.dub.get_r2_client"
    ), patch(
        "app.workers.dub.synthesize_segment_with_rate_adjustment",
        side_effect=TTSProviderError("edge-tts unreachable"),
    ), patch("app.workers.dub.broadcast_sync") as mock_broadcast:
        from app.workers.dub import dub_task

        dub_task.run(project_id=project_id)

    with Session(engine) as session:
        refreshed_job = session.get(Job, job_id)
        assert refreshed_job.status == "failed"
        assert "edge-tts unreachable" in refreshed_job.error_message
        assert "speaker_1" in refreshed_job.error_message

        # no silent switch to another engine happened
        dubbed = session.exec(select(DubbedSegment)).all()
        assert len(dubbed) == 0

    # the frontend needs to know a fallback is offerable
    broadcast_payload = mock_broadcast.call_args_list[-1].args[1]
    assert broadcast_payload["can_retry_with_fallback"] is True
    assert broadcast_payload["failed_speaker"] == "speaker_1"
