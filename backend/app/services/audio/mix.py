import shutil
import subprocess
import tempfile

from app.services.audio.demucs import separate_vocals
from app.services.audio.ducking import duck_and_mix


def mix_background_with_voice(
    background_path: str, voice_path: str, out_path: str, background_volume: float
) -> None:
    filter_complex = (
        f"[0:a]volume={background_volume}[bg];"
        f"[bg][1:a]amix=inputs=2:duration=first:weights=1 1[out]"
    )
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", background_path,
            "-i", voice_path,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            out_path,
        ],
        check=True,
        capture_output=True,
    )


def build_final_audio(
    audio_mode: str,
    voice_track_path: str,
    original_audio_path: str,
    background_volume: float,
    out_path: str,
) -> None:
    if audio_mode == "silent":
        shutil.copyfile(voice_track_path, out_path)
        return

    if audio_mode == "ducking":
        duck_and_mix(original_audio_path, voice_track_path, out_path, background_volume)
        return

    if audio_mode == "music_separated":
        tmp_dir = tempfile.mkdtemp(prefix="demucs_")
        demucs_result = separate_vocals(original_audio_path, tmp_dir)
        mix_background_with_voice(
            demucs_result.accompaniment_path, voice_track_path, out_path, background_volume
        )
        return

    raise ValueError(f"Unknown audio_mode: {audio_mode}")
