from app.services.audio.duration import probe_audio_duration
from app.services.tts.base import TTSEngine

MAX_SPEED_MULTIPLIER = 1.3


def synthesize_segment_with_rate_adjustment(
    engine: TTSEngine,
    text: str,
    voice_id: str,
    target_duration: float,
    out_path: str,
) -> float:
    """Pass 1: synthesize at normal rate, measure it. Pass 2: if the audio
    ran longer than the original segment's duration, resynthesize at a
    faster rate (capped at 1.3x to avoid unnatural-sounding speech) and
    measure again. If it's already shorter than or equal to the target,
    leave it as-is — the gap becomes slack for Phase 7's silence padding.
    Anything still too long after the cap is handled by Phase 7's atempo
    step, per spec's documented 3-step correction order."""
    engine.synthesize(text, voice_id, speed=1.0, out_path=out_path)
    natural_duration = probe_audio_duration(out_path)

    if natural_duration <= target_duration:
        return natural_duration

    speed = min(natural_duration / target_duration, MAX_SPEED_MULTIPLIER)
    engine.synthesize(text, voice_id, speed=speed, out_path=out_path)
    return probe_audio_duration(out_path)
