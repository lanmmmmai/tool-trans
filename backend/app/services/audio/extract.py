import os
import subprocess


class AudioExtractionError(Exception):
    pass


def extract_audio(video_path: str, out_path: str) -> None:
    if not os.path.exists(video_path):
        raise AudioExtractionError(f"File not found: {video_path}")

    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", video_path,
                "-vn", "-ac", "1", "-ar", "16000", "-f", "wav",
                out_path,
            ],
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise AudioExtractionError(
            f"ffmpeg failed extracting audio from {video_path}: {exc.stderr.decode(errors='replace')}"
        ) from exc
