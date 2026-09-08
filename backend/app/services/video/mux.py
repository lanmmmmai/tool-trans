import subprocess


def mux_video_with_audio(video_path: str, audio_path: str, out_path: str) -> None:
    """Copies the video stream unchanged (no re-encode, no quality loss —
    per spec's default resolution-copy behavior) and replaces the audio
    with the given track, re-encoded to AAC for MP4 compatibility."""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            out_path,
        ],
        check=True,
        capture_output=True,
    )
