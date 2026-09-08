import subprocess


def generate_silence(duration_sec: float, out_path: str) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
            "-t", str(duration_sec),
            out_path,
        ],
        check=True,
        capture_output=True,
    )
