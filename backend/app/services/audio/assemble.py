import os
import shutil
import tempfile
from dataclasses import dataclass

from app.services.audio.atempo import apply_atempo
from app.services.audio.concat import concat_audio_pieces
from app.services.audio.duration import probe_audio_duration
from app.services.audio.silence import generate_silence

MIN_GAP_TO_PAD_SEC = 0.02
OVERFLOW_TOLERANCE_SEC = 0.05


@dataclass
class SegmentAudioPlacement:
    start_time: float
    end_time: float
    audio_path: str


def assemble_dubbed_audio_track(
    placements: list[SegmentAudioPlacement],
    total_duration: float,
    out_path: str,
) -> None:
    """Steps 2-3 of the spec's timing-sync order: place each (already
    rate-adjusted, from Phase 6) clip at its original start_time, use the
    natural gap before the next clip as padding, and apply atempo to force
    a clip that still overflows its allotted window (end_time - start_time)
    to fit exactly."""
    tmp_dir = tempfile.mkdtemp(prefix="assemble_")
    try:
        ordered = sorted(placements, key=lambda p: p.start_time)
        pieces: list[str] = []
        cursor = 0.0

        for i, placement in enumerate(ordered):
            gap = placement.start_time - cursor
            if gap > MIN_GAP_TO_PAD_SEC:
                silence_path = os.path.join(tmp_dir, f"silence_{i}.wav")
                generate_silence(gap, silence_path)
                pieces.append(silence_path)
                cursor += gap

            target = placement.end_time - placement.start_time
            actual = probe_audio_duration(placement.audio_path)

            if actual > target + OVERFLOW_TOLERANCE_SEC and target > 0:
                adjusted_path = os.path.join(tmp_dir, f"seg_{i}_atempo.wav")
                apply_atempo(placement.audio_path, adjusted_path, factor=actual / target)
                pieces.append(adjusted_path)
                cursor += target
            else:
                pieces.append(placement.audio_path)
                cursor += actual

        trailing_gap = total_duration - cursor
        if trailing_gap > MIN_GAP_TO_PAD_SEC:
            trailing_path = os.path.join(tmp_dir, "trailing_silence.wav")
            generate_silence(trailing_gap, trailing_path)
            pieces.append(trailing_path)

        concat_audio_pieces(pieces, out_path)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
