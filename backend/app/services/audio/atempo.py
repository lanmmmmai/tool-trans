import subprocess

ATEMPO_MAX_PER_STAGE = 2.0
ATEMPO_MIN_PER_STAGE = 0.5


def build_atempo_filter_chain(factor: float) -> str:
    """ffmpeg's atempo filter only accepts [0.5, 2.0] per instance, so a
    factor outside that range must be split across chained instances."""
    if ATEMPO_MIN_PER_STAGE <= factor <= ATEMPO_MAX_PER_STAGE:
        return f"atempo={factor}"

    stages: list[float] = []
    remaining = factor
    while remaining > ATEMPO_MAX_PER_STAGE:
        stages.append(ATEMPO_MAX_PER_STAGE)
        remaining /= ATEMPO_MAX_PER_STAGE
    stages.append(round(remaining, 4))

    return ",".join(f"atempo={stage}" for stage in stages)


def apply_atempo(input_path: str, out_path: str, factor: float) -> None:
    filter_chain = build_atempo_filter_chain(factor)
    subprocess.run(
        ["ffmpeg", "-y", "-i", input_path, "-filter:a", filter_chain, out_path],
        check=True,
        capture_output=True,
    )
