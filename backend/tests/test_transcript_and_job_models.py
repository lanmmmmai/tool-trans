from sqlmodel import Session, SQLModel, create_engine, select

from app.models.job import Job
from app.models.project import Project
from app.models.transcript_segment import TranscriptSegment


def make_engine():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine


def make_project(session):
    project = Project(
        user_id="u1", title="t", source_language="en", target_language="vi", audio_mode="ducking"
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def test_create_transcript_segment():
    engine = make_engine()
    with Session(engine) as session:
        project = make_project(session)
        seg = TranscriptSegment(
            project_id=project.id,
            seq_index=0,
            start_time=0.0,
            end_time=2.5,
            speaker_label="speaker_1",
            source_text="Hello world",
        )
        session.add(seg)
        session.commit()
        session.refresh(seg)
        assert seg.id is not None
        assert seg.source_text_edited is None


def test_create_job_defaults():
    engine = make_engine()
    with Session(engine) as session:
        project = make_project(session)
        job = Job(project_id=project.id, job_type="transcribe")
        session.add(job)
        session.commit()
        session.refresh(job)
        assert job.status == "queued"
        assert job.progress_pct == 0

        fetched = session.exec(select(Job).where(Job.project_id == project.id)).one()
        assert fetched.job_type == "transcribe"
