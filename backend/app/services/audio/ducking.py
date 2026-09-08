import subprocess


def duck_and_mix(
    original_audio_path: str, voice_path: str, out_path: str, background_volume: float
) -> None:
    """Sidechain-compresses the original audio against the voice track (so
    it automatically quiets down while the new voice is speaking), then
    mixes the two together. `background_volume` sets the original track's
    baseline gain before compression."""
    filter_complex = (
        f"[0:a]volume={background_volume}[bg];"
        f"[bg][1:a]sidechaincompress=threshold=0.05:ratio=8:attack=5:release=200[ducked];"
        f"[ducked][1:a]amix=inputs=2:duration=first:weights=1 1[out]"
    )
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", original_audio_path,
            "-i", voice_path,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            out_path,
        ],
        check=True,
        capture_output=True,
    )
