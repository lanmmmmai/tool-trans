from unittest.mock import MagicMock, patch

from app.services.tts.sync import synthesize_segment_with_rate_adjustment


def test_no_resynthesis_needed_when_first_pass_fits():
    mock_engine = MagicMock()

    with patch("app.services.tts.sync.probe_audio_duration", return_value=2.0):
        final_duration = synthesize_segment_with_rate_adjustment(
            engine=mock_engine,
            text="Xin chào",
            voice_id="vi-VN-HoaiMyNeural",
            target_duration=2.5,  # natural audio (2.0s) already fits inside target
            out_path="/tmp/out.mp3",
        )

    assert final_duration == 2.0
    assert mock_engine.synthesize.call_count == 1
    assert mock_engine.synthesize.call_args.kwargs["speed"] == 1.0


def test_resynthesizes_faster_when_too_long():
    mock_engine = MagicMock()

    with patch(
        "app.services.tts.sync.probe_audio_duration", side_effect=[4.0, 2.6]
    ):
        final_duration = synthesize_segment_with_rate_adjustment(
            engine=mock_engine,
            text="Một câu khá dài",
            voice_id="vi-VN-HoaiMyNeural",
            target_duration=2.5,
            out_path="/tmp/out.mp3",
        )

    assert final_duration == 2.6
    assert mock_engine.synthesize.call_count == 2
    first_speed = mock_engine.synthesize.call_args_list[0].kwargs["speed"]
    second_speed = mock_engine.synthesize.call_args_list[1].kwargs["speed"]
    assert first_speed == 1.0
    assert second_speed == 1.3  # 4.0 / 2.5 = 1.6, clamped to the 1.3 cap


def test_does_not_slow_down_when_shorter_than_target():
    mock_engine = MagicMock()

    with patch("app.services.tts.sync.probe_audio_duration", return_value=1.0):
        final_duration = synthesize_segment_with_rate_adjustment(
            engine=mock_engine,
            text="Ngắn",
            voice_id="vi-VN-HoaiMyNeural",
            target_duration=3.0,
            out_path="/tmp/out.mp3",
        )

    assert final_duration == 1.0
    assert mock_engine.synthesize.call_count == 1  # left for silence padding in Phase 7
