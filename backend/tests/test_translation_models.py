from sqlmodel import Session, SQLModel, create_engine

from app.models.glossary_term import GlossaryTerm
from app.models.project import Project
from app.models.transcript_segment import TranscriptSegment
from app.models.translation_segment import TranslationSegment


def make_engine():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine


def test_create_translation_segment_linked_to_transcript_segment():
    engine = make_engine()
    with Session(engine) as session:
        project = Project(
            user_id="u1", title="t", source_language="en", target_language="vi", audio_mode="ducking"
        )
        session.add(project)
        session.commit()
        session.refresh(project)

        transcript_seg = TranscriptSegment(
            project_id=project.id, seq_index=0, start_time=0, end_time=1,
            speaker_label="speaker_1", source_text="Hello",
        )
        session.add(transcript_seg)
        session.commit()
        session.refresh(transcript_seg)

        translation_seg = TranslationSegment(
            segment_id=transcript_seg.id, translated_text="Xin chào"
        )
        session.add(translation_seg)
        session.commit()
        session.refresh(translation_seg)

        assert translation_seg.translated_text_edited is None
        assert translation_seg.segment_id == transcript_seg.id


def test_create_glossary_term():
    engine = make_engine()
    with Session(engine) as session:
        term = GlossaryTerm(user_id="u1", source_term="Claude", target_term="Claude")
        session.add(term)
        session.commit()
        session.refresh(term)
        assert term.id is not None
