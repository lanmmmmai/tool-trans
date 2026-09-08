import subprocess


def concat_audio_pieces(piece_paths: list[str], out_path: str) -> None:
    """Uses filter_complex concat (not the concat demuxer) since pieces may
    come from different encoders (edge-tts mp3, Gemini TTS wav, generated
    silence) and are re-decoded into a uniform PCM stream before joining."""
    if not piece_paths:
        raise ValueError("piece_paths must not be empty")

    inputs: list[str] = []
    for path in piece_paths:
        inputs += ["-i", path]

    stream_labels = "".join(f"[{i}:a]" for i in range(len(piece_paths)))
    filter_complex = f"{stream_labels}concat=n={len(piece_paths)}:v=0:a=1[out]"

    subprocess.run(
        [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            out_path,
        ],
        check=True,
        capture_output=True,
    )
