from app.models.transcript_segment import TranscriptSegment
from app.services.translation.chunker import chunk_segments


def make_segment(i: int) -> TranscriptSegment:
    return TranscriptSegment(
        project_id="p1", seq_index=i, start_time=i, end_time=i + 1,
        speaker_label="speaker_1", source_text=f"sentence {i}",
    )


def test_chunk_segments_splits_into_groups_of_chunk_size():
    segments = [make_segment(i) for i in range(32)]
    chunks = chunk_segments(segments, chunk_size=15)

    assert len(chunks) == 3
    assert len(chunks[0]) == 15
    assert len(chunks[1]) == 15
    assert len(chunks[2]) == 2
    assert chunks[0][0].seq_index == 0
    assert chunks[2][-1].seq_index == 31


def test_chunk_segments_handles_empty_list():
    assert chunk_segments([], chunk_size=15) == []
