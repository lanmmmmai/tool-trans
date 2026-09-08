import json
import subprocess


def probe_audio_duration(path: str) -> float:
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-print_format", "json", "-show_format",
            path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(proc.stdout)
    return float(data["format"]["duration"])
