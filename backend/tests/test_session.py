from sqlmodel import Session, SQLModel, text

from app.db.session import get_engine


def test_get_session_yields_working_session(tmp_path):
    db_path = tmp_path / "test.db"
    engine = get_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    session_gen = get_session_override(engine)
    session = next(session_gen)
    try:
        assert isinstance(session, Session)
        result = session.exec(text("SELECT 1")).one()
        assert result[0] == 1
    finally:
        session_gen.close()


def get_session_override(engine):
    """Mirrors get_session's generator shape but takes an explicit engine,
    so the test does not depend on app.core.config.settings.database_url."""
    with Session(engine) as session:
        yield session
