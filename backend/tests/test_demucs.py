import os
import sys
from unittest.mock import patch

import pytest

from app.services.audio.demucs import DemucsError, separate_vocals


def test_separate_vocals_invokes_demucs_and_resolves_output_paths(tmp_path):
    input_path = str(tmp_path / "input.wav")
    with open(input_path, "wb") as f:
        f.write(b"fake-audio")
    out_dir = str(tmp_path / "out")

    def fake_run(cmd, **kwargs):
        # Simulate demucs writing its standard nested output structure.
        model_dir = os.path.join(out_dir, "htdemucs", "input")
        os.makedirs(model_dir, exist_ok=True)
        open(os.path.join(model_dir, "vocals.wav"), "wb").close()
        open(os.path.join(model_dir, "no_vocals.wav"), "wb").close()

        class FakeResult:
            returncode = 0

        return FakeResult()

    with patch("app.services.audio.demucs.subprocess.run", side_effect=fake_run) as mock_run:
        result = separate_vocals(input_path, out_dir)

    called_cmd = mock_run.call_args.args[0]
    assert called_cmd[0:3] == [sys.executable, "-m", "demucs"]
    assert "--two-stems=vocals" in called_cmd
    assert input_path in called_cmd

    assert result.vocals_path.endswith("vocals.wav")
    assert result.accompaniment_path.endswith("no_vocals.wav")
    assert os.path.exists(result.vocals_path)
    assert os.path.exists(result.accompaniment_path)


def test_separate_vocals_raises_on_missing_output(tmp_path):
    input_path = str(tmp_path / "input.wav")
    with open(input_path, "wb") as f:
        f.write(b"fake-audio")
    out_dir = str(tmp_path / "out")

    with patch("app.services.audio.demucs.subprocess.run"):
        with pytest.raises(DemucsError):
            separate_vocals(input_path, out_dir)
