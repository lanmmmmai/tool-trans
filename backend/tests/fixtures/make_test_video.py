"""Run manually to (re)generate the 2-second test fixture used by
test_ffprobe.py: `python tests/fixtures/make_test_video.py`"""
import subprocess
from pathlib import Path

OUT = Path(__file__).parent / "tiny.mp4"


def main() -> None:
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-shortest",
            str(OUT),
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
