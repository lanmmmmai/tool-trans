from app.models.transcript_segment import TranscriptSegment


def chunk_segments(
    segments: list[TranscriptSegment], chunk_size: int = 15
) -> list[list[TranscriptSegment]]:
    return [segments[i : i + chunk_size] for i in range(0, len(segments), chunk_size)]
