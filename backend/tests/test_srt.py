from app.services.subtitle.srt import SubtitleCue, generate_srt


def test_generate_srt_formats_timestamps_and_numbering():
    cues = [
        SubtitleCue(start=0.0, end=2.5, text="Xin chào"),
        SubtitleCue(start=2.5, end=5.125, text="Thế giới"),
    ]

    srt = generate_srt(cues)

    assert srt == (
        "1\n"
        "00:00:00,000 --> 00:00:02,500\n"
        "Xin chào\n"
        "\n"
        "2\n"
        "00:00:02,500 --> 00:00:05,125\n"
        "Thế giới\n"
        "\n"
    )


def test_generate_srt_handles_hour_boundary():
    cues = [SubtitleCue(start=3661.2, end=3662.0, text="Muộn rồi")]
    srt = generate_srt(cues)
    assert "01:01:01,200 --> 01:01:02,000" in srt
