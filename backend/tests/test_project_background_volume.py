from sqlmodel import Session, SQLModel, create_engine

from app.models.project import Project


def test_project_defaults_background_volume_to_point_three():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        project = Project(
            user_id="u1", title="t", source_language="en", target_language="vi", audio_mode="ducking"
        )
        session.add(project)
        session.commit()
        session.refresh(project)
        assert project.background_volume == 0.3
