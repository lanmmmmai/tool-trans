from unittest.mock import patch

from app.services.audio.mix import build_final_audio


def test_silent_mode_just_copies_voice_track(tmp_path):
    voice_path = str(tmp_path / "voice.wav")
    with open(voice_path, "wb") as f:
        f.write(b"voice-bytes")
    out_path = str(tmp_path / "out.wav")

    build_final_audio(
        audio_mode="silent",
        voice_track_path=voice_path,
        original_audio_path=str(tmp_path / "unused.wav"),
        background_volume=0.3,
        out_path=out_path,
    )

    with open(out_path, "rb") as f:
        assert f.read() == b"voice-bytes"


def test_ducking_mode_calls_duck_and_mix(tmp_path):
    voice_path = str(tmp_path / "voice.wav")
    original_path = str(tmp_path / "original.wav")
    out_path = str(tmp_path / "out.wav")

    with patch("app.services.audio.mix.duck_and_mix") as mock_duck:
        build_final_audio(
            audio_mode="ducking",
            voice_track_path=voice_path,
            original_audio_path=original_path,
            background_volume=0.4,
            out_path=out_path,
        )

    mock_duck.assert_called_once_with(original_path, voice_path, out_path, 0.4)


def test_music_separated_mode_calls_demucs_then_mixes(tmp_path):
    voice_path = str(tmp_path / "voice.wav")
    original_path = str(tmp_path / "original.wav")
    out_path = str(tmp_path / "out.wav")

    with patch("app.services.audio.mix.separate_vocals") as mock_separate, patch(
        "app.services.audio.mix.mix_background_with_voice"
    ) as mock_mix:
        from app.services.audio.demucs import DemucsResult

        mock_separate.return_value = DemucsResult(
            vocals_path="/tmp/vocals.wav", accompaniment_path="/tmp/no_vocals.wav"
        )

        build_final_audio(
            audio_mode="music_separated",
            voice_track_path=voice_path,
            original_audio_path=original_path,
            background_volume=0.5,
            out_path=out_path,
        )

    mock_separate.assert_called_once()
    mock_mix.assert_called_once_with("/tmp/no_vocals.wav", voice_path, out_path, 0.5)
