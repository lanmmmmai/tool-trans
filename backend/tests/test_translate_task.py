from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.glossary_term import GlossaryTerm
from app.models.job import Job
from app.models.project import Project
from app.models.transcript_segment import TranscriptSegment
from app.models.translation_segment import TranslationSegment


def make_engine():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine


def seed(session):
    project = Project(
        user_id="u1", title="t", source_language="en", target_language="vi",
        audio_mode="ducking", translate_engine="gemini",
    )
    session.add(project)
    session.commit()
    session.refresh(project)

    for i, text in enumerate(["Hello", "World"]):
        session.add(
            TranscriptSegment(
                project_id=project.id, seq_index=i, start_time=i, end_time=i + 1,
                speaker_label="speaker_1", source_text=text,
            )
        )
    session.add(GlossaryTerm(user_id="u1", source_term="Claude", target_term="Claude"))

    job = Job(project_id=project.id, job_type="translate")
    session.add(job)
    session.commit()
    session.refresh(job)

    project_id, job_id = project.id, job.id
    return project_id, job_id


def test_translate_task_writes_translation_segments_and_marks_job_done():
    engine = make_engine()
    with Session(engine) as session:
        project_id, job_id = seed(session)

    with patch("app.workers.translate.get_session_for_worker", return_value=Session(engine)), patch(
        "app.workers.translate.GeminiTranslator"
    ) as MockGemini, patch("app.workers.translate.broadcast_sync"):
        MockGemini.return_value.translate_chunk.return_value = ["Xin chào", "Thế giới"]

        from app.workers.translate import translate_task

        translate_task.run(project_id=project_id, engine_name="gemini")

    with Session(engine) as session:
        refreshed_job = session.get(Job, job_id)
        assert refreshed_job.status == "done"

        translations = session.exec(select(TranslationSegment)).all()
        assert len(translations) == 2
        texts = {t.translated_text for t in translations}
        assert texts == {"Xin chào", "Thế giới"}


def test_translate_task_marks_job_failed_on_exception():
    engine = make_engine()
    with Session(engine) as session:
        project_id, job_id = seed(session)

    with patch("app.workers.translate.get_session_for_worker", return_value=Session(engine)), patch(
        "app.workers.translate.GeminiTranslator"
    ) as MockGemini, patch("app.workers.translate.broadcast_sync"):
        MockGemini.return_value.translate_chunk.side_effect = RuntimeError("api down")

        from app.workers.translate import translate_task

        translate_task.run(project_id=project_id, engine_name="gemini")

    with Session(engine) as session:
        refreshed_job = session.get(Job, job_id)
        assert refreshed_job.status == "failed"
        assert "api down" in refreshed_job.error_message
