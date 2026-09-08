import os
import tempfile
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.storage import get_r2_client
from app.core.ws_manager import publish_progress_sync
from app.db.session import engine
from app.models.dubbed_segment import DubbedSegment
from app.models.job import Job
from app.models.transcript_segment import TranscriptSegment
from app.models.translation_segment import TranslationSegment
from app.models.voice import Voice
from app.services.tts.base import TTSProviderError
from app.services.tts.edge_tts_engine import EdgeTTSEngine
from app.services.tts.gemini_tts_engine import GeminiTTSEngine
from app.services.tts.sync import synthesize_segment_with_rate_adjustment


def get_session_for_worker() -> Session:
    return Session(engine)


def broadcast_sync(project_id: str, message: dict) -> None:
    # Runs inside the Celery worker process — must cross the process
    # boundary to reach the backend's live WebSocket connections, so this
    # publishes over Redis rather than touching an in-memory WSManager.
    publish_progress_sync(project_id, message)


def _build_tts_engine(engine_name: str):
    if engine_name == "gemini_tts":
        return GeminiTTSEngine(api_key=settings.gemini_api_key)
    return EdgeTTSEngine()


def _effective_translated_text(translation: TranslationSegment) -> str:
    return translation.translated_text_edited or translation.translated_text


@celery_app.task(name="app.workers.dub.dub_task")
def dub_task(project_id: str) -> None:
    session = get_session_for_worker()
    job = session.exec(
        select(Job)
        .where(Job.project_id == project_id, Job.job_type == "dub")
        .order_by(Job.started_at.desc().nullslast())
    ).first()
    if job is None:
        session.close()
        return

    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    job.current_step = "synthesizing_speech"
    session.add(job)
    session.commit()
    broadcast_sync(project_id, {"status": "running", "step": "synthesizing_speech", "progress_pct": 5})

    try:
        rows = session.exec(
            select(TranscriptSegment, TranslationSegment)
            .join(TranslationSegment, TranslationSegment.segment_id == TranscriptSegment.id)
            .where(TranscriptSegment.project_id == project_id)
            .order_by(TranscriptSegment.seq_index)
        ).all()

        voices_by_speaker = {
            v.speaker_label: v
            for v in session.exec(select(Voice).where(Voice.project_id == project_id)).all()
        }

        r2_client = get_r2_client()
        total = max(len(rows), 1)

        with tempfile.TemporaryDirectory() as tmp_dir:
            for index, (transcript, translation) in enumerate(rows):
                voice = voices_by_speaker.get(transcript.speaker_label)
                if voice is None:
                    raise RuntimeError(f"No voice assigned for {transcript.speaker_label}")

                tts_engine = _build_tts_engine(voice.engine)
                out_path = os.path.join(tmp_dir, f"{transcript.id}.mp3")
                target_duration = transcript.end_time - transcript.start_time

                try:
                    final_duration = synthesize_segment_with_rate_adjustment(
                        engine=tts_engine,
                        text=_effective_translated_text(translation),
                        voice_id=voice.voice_id,
                        target_duration=target_duration,
                        out_path=out_path,
                    )
                except TTSProviderError as exc:
                    job.status = "failed"
                    job.error_message = (
                        f"{voice.engine} failed for speaker {transcript.speaker_label}: {exc}"
                    )
                    job.finished_at = datetime.now(timezone.utc)
                    session.add(job)
                    session.commit()
                    broadcast_sync(
                        project_id,
                        {
                            "status": "failed",
                            "error": job.error_message,
                            "can_retry_with_fallback": True,
                            "failed_speaker": transcript.speaker_label,
                            "failed_engine": voice.engine,
                        },
                    )
                    return

                key = f"dubbed/{project_id}/{transcript.id}.mp3"
                r2_client.upload_file(out_path, key)

                session.add(
                    DubbedSegment(
                        segment_id=transcript.id,
                        audio_storage_path=key,
                        duration_sec=final_duration,
                        status="done",
                        generated_at=datetime.now(timezone.utc),
                    )
                )
                session.commit()

                progress = int(((index + 1) / total) * 90) + 5
                job.progress_pct = progress
                session.add(job)
                session.commit()
                broadcast_sync(
                    project_id,
                    {"status": "running", "step": "synthesizing_speech", "progress_pct": progress},
                )

        job.status = "done"
        job.progress_pct = 100
        job.current_step = "done"
        job.finished_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()
        broadcast_sync(project_id, {"status": "done", "progress_pct": 100})
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error_message = str(exc)
        job.finished_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()
        broadcast_sync(project_id, {"status": "failed", "error": str(exc)})
    finally:
        session.close()
