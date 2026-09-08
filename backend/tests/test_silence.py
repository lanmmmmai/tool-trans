from app.services.audio.duration import probe_audio_duration
from app.services.audio.silence import generate_silence


def test_generate_silence_produces_correct_duration(tmp_path):
    out_path = str(tmp_path / "silence.wav")
    generate_silence(1.5, out_path)
    duration = probe_audio_duration(out_path)
    assert 1.4 <= duration <= 1.6
