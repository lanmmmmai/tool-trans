from dataclasses import dataclass


@dataclass
class SubtitleCue:
    start: float
    end: float
    text: str


def _format_timestamp(seconds: float) -> str:
    total_ms = round(seconds * 1000)
    hours, remainder_ms = divmod(total_ms, 3_600_000)
    minutes, remainder_ms = divmod(remainder_ms, 60_000)
    secs, ms = divmod(remainder_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def generate_srt(cues: list[SubtitleCue]) -> str:
    blocks = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(
            f"{index}\n"
            f"{_format_timestamp(cue.start)} --> {_format_timestamp(cue.end)}\n"
            f"{cue.text}\n\n"
        )
    return "".join(blocks)
