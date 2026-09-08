import subprocess


def embed_soft_subtitles(video_path: str, srt_path: str, out_path: str) -> None:
    """Adds the SRT as a toggleable subtitle track (mov_text, MP4-compatible)
    without altering the video/audio streams."""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", srt_path,
            "-map", "0:v", "-map", "0:a", "-map", "1:s",
            "-c:v", "copy", "-c:a", "copy",
            "-c:s", "mov_text",
            "-metadata:s:s:0", "language=vie",
            out_path,
        ],
        check=True,
        capture_output=True,
    )
