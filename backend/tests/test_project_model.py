from sqlmodel import Session, SQLModel, create_engine, select

from app.models.project import Project
from app.models.video import Video


def make_engine():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine


def test_create_project_and_video():
    engine = make_engine()
    with Session(engine) as session:
        project = Project(
            user_id="user-1",
            title="My video",
            source_language="en",
            target_language="vi",
            audio_mode="ducking",
        )
        session.add(project)
        session.commit()
        session.refresh(project)

        assert project.status == "draft"
        assert project.id is not None

        video = Video(
            project_id=project.id,
            source_type="upload",
            storage_path="videos/abc.mp4",
            duration_sec=120.5,
            resolution="1920x1080",
            codec="h264",
            file_size_bytes=1024,
        )
        session.add(video)
        session.commit()

        fetched = session.exec(select(Video).where(Video.project_id == project.id)).one()
        assert fetched.storage_path == "videos/abc.mp4"
