import json
import os
import subprocess
from dataclasses import dataclass


class ProbeError(Exception):
    pass


@dataclass
class VideoProbeResult:
    duration_sec: float
    resolution: str
    codec: str
    file_size_bytes: int


def probe_video(path: str) -> VideoProbeResult:
    if not os.path.exists(path):
        raise ProbeError(f"File not found: {path}")

    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-print_format", "json",
                "-show_format", "-show_streams",
                path,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise ProbeError(f"ffprobe failed for {path}: {exc}") from exc

    data = json.loads(proc.stdout)
    video_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"), None
    )
    if video_stream is None:
        raise ProbeError(f"No video stream found in {path}")

    duration_sec = float(data["format"]["duration"])
    resolution = f"{video_stream['width']}x{video_stream['height']}"
    codec = video_stream["codec_name"]
    file_size_bytes = os.path.getsize(path)

    return VideoProbeResult(
        duration_sec=duration_sec,
        resolution=resolution,
        codec=codec,
        file_size_bytes=file_size_bytes,
    )
