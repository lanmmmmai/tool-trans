import os
import subprocess

POSITION_ALIGNMENT = {
    "bottom_center": 2,  # libass \an alignment codes
    "top_center": 8,
    "middle_center": 5,
}


def burn_subtitles(
    video_path: str,
    srt_path: str,
    out_path: str,
    font_size: int = 28,
    font_color: str = "white",
    position: str = "bottom_center",
) -> None:
    alignment = POSITION_ALIGNMENT.get(position, 2)
    # TikTok-style default: large text, black outline, centered.
    force_style = (
        f"FontSize={font_size},PrimaryColour=&H{_color_to_ass_hex(font_color)},"
        f"OutlineColour=&H000000,BorderStyle=1,Outline=2,Alignment={alignment}"
    )

    # ffmpeg's `subtitles` filter parses its own argument string by
    # splitting on ":" to separate key=value options — a Windows drive
    # letter's colon (e.g. "C:") collides with that parser even when
    # backslash-escaped (confirmed for real: it still misparsed the path
    # and errored on an unrelated "original_size" option). The robust,
    # well-known workaround is to avoid the drive-letter colon entirely by
    # running ffmpeg with its cwd set to the subtitle file's directory and
    # referencing it by filename only.
    srt_dir = os.path.dirname(os.path.abspath(srt_path)) or "."
    srt_filename = os.path.basename(srt_path)
    video_abspath = os.path.abspath(video_path)
    out_abspath = os.path.abspath(out_path)

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", video_abspath,
            "-vf", f"subtitles={srt_filename}:force_style='{force_style}'",
            "-c:a", "copy",
            out_abspath,
        ],
        check=True,
        capture_output=True,
        cwd=srt_dir,
    )


def _color_to_ass_hex(color_name: str) -> str:
    # ASS colors are &HBBGGRR (reverse byte order from typical RGB names).
    named = {
        "white": "FFFFFF",
        "yellow": "00FFFF",
        "black": "000000",
    }
    return named.get(color_name, "FFFFFF")
