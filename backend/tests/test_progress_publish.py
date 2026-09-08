import json
from unittest.mock import MagicMock, patch

from app.core.ws_manager import PROGRESS_CHANNEL_PREFIX, publish_progress_sync


def test_publish_progress_sync_publishes_json_to_correct_channel():
    with patch("app.core.ws_manager.redis.Redis.from_url") as mock_from_url:
        mock_client = MagicMock()
        mock_from_url.return_value = mock_client

        publish_progress_sync("project-123", {"status": "running", "progress_pct": 50})

        mock_client.publish.assert_called_once_with(
            f"{PROGRESS_CHANNEL_PREFIX}project-123",
            json.dumps({"status": "running", "progress_pct": 50}),
        )
        mock_client.close.assert_called_once()
