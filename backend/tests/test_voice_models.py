from sqlmodel import Session, SQLModel, create_engine

from app.models.dubbed_segment import DubbedSegment
from app.models.project import Project
from app.models.transcript_segment import TranscriptSegment
from app.models.voice import Voice


def make_engine():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine


def test_create_voice_with_defaults():
    engine = make_engine()
    with Session(engine) as session:
        project = Project(
            user_id="u1", title="t", source_language="en", target_language="vi", audio_mode="ducking"
        )
        session.add(project)
        session.commit()
        session.refresh(project)

        voice = Voice(
            project_id=project.id,
            speaker_label="speaker_1",
            engine="edge_tts",
            voice_id="vi-VN-HoaiMyNeural",
        )
        session.add(voice)
        session.commit()
        session.refresh(voice)

        assert voice.speed == 1.0
        assert voice.pitch == 0.0


def test_create_dubbed_segment():
    engine = make_engine()
    with Session(engine) as session:
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

        dubbed = DubbedSegment(
            segment_id=seg.id, audio_storage_path="dubbed/x.mp3",
            duration_sec=2.1, status="done",
        )
        session.add(dubbed)
        session.commit()
        session.refresh(dubbed)
        assert dubbed.id is not None
