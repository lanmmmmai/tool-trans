from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.ws_manager import publish_progress_sync
from app.db.session import engine
from app.models.glossary_term import GlossaryTerm
from app.models.job import Job
from app.models.project import Project
from app.models.transcript_segment import TranscriptSegment
from app.models.translation_segment import TranslationSegment
from app.services.translation.base import ChunkSegment, GlossaryEntry
from app.services.translation.chunker import chunk_segments
from app.services.translation.gemini import GeminiTranslator
from app.services.translation.openai import OpenAITranslator


def get_session_for_worker() -> Session:
    return Session(engine)


def broadcast_sync(project_id: str, message: dict) -> None:
    # Runs inside the Celery worker process — must cross the process
    # boundary to reach the backend's live WebSocket connections, so this
    # publishes over Redis rather than touching an in-memory WSManager.
    publish_progress_sync(project_id, message)


def _effective_source_text(segment: TranscriptSegment) -> str:
    return segment.source_text_edited or segment.source_text


def _build_translator(engine_name: str):
    if engine_name == "openai":
        return OpenAITranslator(api_key=settings.openai_api_key)
    return GeminiTranslator(api_key=settings.gemini_api_key)


@celery_app.task(name="app.workers.translate.translate_task")
def translate_task(project_id: str, engine_name: str = "gemini") -> None:
    session = get_session_for_worker()
    job = session.exec(
        select(Job)
        .where(Job.project_id == project_id, Job.job_type == "translate")
        .order_by(Job.started_at.desc().nullslast())
    ).first()
    if job is None:
        session.close()
        return

    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    job.current_step = "translating"
    session.add(job)
    session.commit()
    broadcast_sync(project_id, {"status": "running", "step": "translating", "progress_pct": 5})

    try:
        segments = session.exec(
            select(TranscriptSegment)
            .where(TranscriptSegment.project_id == project_id)
            .order_by(TranscriptSegment.seq_index)
        ).all()
        full_transcript = " ".join(_effective_source_text(s) for s in segments)

        glossary_rows = session.exec(select(GlossaryTerm)).all()
        glossary = [GlossaryEntry(g.source_term, g.target_term) for g in glossary_rows]

        project = session.get(Project, project_id)
        translator = _build_translator(engine_name)

        chunks = chunk_segments(segments, chunk_size=15)
        total_chunks = max(len(chunks), 1)

        for chunk_index, chunk in enumerate(chunks):
            chunk_segments_for_prompt = [
                ChunkSegment(seq_index=s.seq_index, text=_effective_source_text(s)) for s in chunk
            ]
            translations = translator.translate_chunk(
                full_transcript=full_transcript,
                chunk=chunk_segments_for_prompt,
                glossary=glossary,
                target_language=project.target_language,
            )

            for segment, translated_text in zip(chunk, translations):
                session.add(
                    TranslationSegment(segment_id=segment.id, translated_text=translated_text)
                )
            session.commit()

            progress = int(((chunk_index + 1) / total_chunks) * 90) + 5
            job.progress_pct = progress
            session.add(job)
            session.commit()
            broadcast_sync(
                project_id,
                {"status": "running", "step": "translating", "progress_pct": progress},
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
