from unittest.mock import MagicMock, patch

from app.services.video.downloader import download_from_url


def test_download_from_url_invokes_yt_dlp_and_returns_path():
    with patch("app.services.video.downloader.yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_ydl = MagicMock()
        mock_ydl.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = {"id": "abc123", "ext": "mp4"}
        mock_ydl.prepare_filename.return_value = "/tmp/dest/abc123.mp4"
        mock_ydl_cls.return_value = mock_ydl

        path = download_from_url("https://www.youtube.com/watch?v=abc123", "/tmp/dest")

        assert path == "/tmp/dest/abc123.mp4"
        mock_ydl.extract_info.assert_called_once_with(
            "https://www.youtube.com/watch?v=abc123", download=True
        )
