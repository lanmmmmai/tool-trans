import os
import subprocess
import sys
from dataclasses import dataclass


class DemucsError(Exception):
    pass


@dataclass
class DemucsResult:
    vocals_path: str
    accompaniment_path: str


def separate_vocals(input_audio_path: str, out_dir: str) -> DemucsResult:
    os.makedirs(out_dir, exist_ok=True)

    # Invoked as `python -m demucs` rather than relying on a bare "demucs"
    # console script being on PATH — the console script depends on the
    # venv/site's Scripts (or bin) directory being on PATH, which isn't
    # guaranteed (confirmed for real: it wasn't, even inside this project's
    # own venv, when the interpreter is invoked by its full path rather
    # than after `activate`). Using sys.executable ties this to whatever
    # Python is actually running this code, with no PATH dependency.
    subprocess.run(
        [sys.executable, "-m", "demucs", "--two-stems=vocals", "-o", out_dir, input_audio_path],
        check=True,
        capture_output=True,
    )

    basename = os.path.splitext(os.path.basename(input_audio_path))[0]
    model_dir = os.path.join(out_dir, "htdemucs", basename)
    vocals_path = os.path.join(model_dir, "vocals.wav")
    accompaniment_path = os.path.join(model_dir, "no_vocals.wav")

    if not (os.path.exists(vocals_path) and os.path.exists(accompaniment_path)):
        raise DemucsError(
            f"Demucs did not produce expected output under {model_dir}"
        )

    return DemucsResult(vocals_path=vocals_path, accompaniment_path=accompaniment_path)
