import os
import tempfile
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.celery_app import celery_app
from app.core.storage import get_r2_client
from app.core.ws_manager import publish_progress_sync
from app.db.session import engine
from app.models.job import Job
from app.models.transcript_segment import TranscriptSegment
from app.models.video import Video
from app.services.audio.extract import extract_audio
from app.services.stt.router import transcribe_with_fallback


def get_session_for_worker() -> Session:
    return Session(engine)


def broadcast_sync(project_id: str, message: dict) -> None:
    # Runs inside the Celery worker process — must cross the process
    # boundary to reach the backend's live WebSocket connections, so this
    # publishes over Redis rather than touching an in-memory WSManager.
    publish_progress_sync(project_id, message)


@celery_app.task(name="app.workers.transcribe.transcribe_task")
def transcribe_task(project_id: str) -> None:
    session = get_session_for_worker()
    job = session.exec(
        select(Job)
        .where(Job.project_id == project_id, Job.job_type == "transcribe")
        .order_by(Job.started_at.desc().nullslast())
    ).first()
    if job is None:
        session.close()
        return

    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    job.current_step = "downloading_video"
    job.progress_pct = 5
    session.add(job)
    session.commit()
    broadcast_sync(project_id, {"status": "running", "step": job.current_step, "progress_pct": 5})

    try:
        video = session.exec(select(Video).where(Video.project_id == project_id)).first()
        if video is None:
            raise RuntimeError("No video found for project")

        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = os.path.join(tmp_dir, "video.mp4")
            get_r2_client().download_file(video.storage_path, video_path)

            job.current_step = "extracting_audio"
            job.progress_pct = 20
            session.add(job)
            session.commit()
            broadcast_sync(project_id, {"status": "running", "step": job.current_step, "progress_pct": 20})

            audio_path = os.path.join(tmp_dir, "audio.wav")
            extract_audio(video_path, audio_path)

            job.current_step = "transcribing"
            job.progress_pct = 40
            session.add(job)
            session.commit()
            broadcast_sync(project_id, {"status": "running", "step": job.current_step, "progress_pct": 40})

            stt_segments, engine_used = transcribe_with_fallback(audio_path)

            for index, seg in enumerate(stt_segments):
                session.add(
                    TranscriptSegment(
                        project_id=project_id,
                        seq_index=index,
                        start_time=seg.start,
                        end_time=seg.end,
                        speaker_label=seg.speaker_label,
                        source_text=seg.text,
                        confidence=seg.confidence,
                    )
                )
            session.commit()

        job.status = "done"
        job.current_step = f"done ({engine_used})"
        job.progress_pct = 100
        job.finished_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()
        broadcast_sync(
            project_id,
            {"status": "done", "step": job.current_step, "progress_pct": 100},
        )
    except Exception as exc:  # noqa: BLE001 — job-failure path must catch everything
        job.status = "failed"
        job.error_message = str(exc)
        job.finished_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()
        broadcast_sync(project_id, {"status": "failed", "error": str(exc)})
    finally:
        session.close()
