import os

import yt_dlp


def download_from_url(url: str, dest_dir: str) -> str:
    os.makedirs(dest_dir, exist_ok=True)
    opts = {
        "outtmpl": os.path.join(dest_dir, "%(id)s.%(ext)s"),
        "format": "bv*[filesize<2G]+ba/b[filesize<2G]/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)
