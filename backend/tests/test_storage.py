from unittest.mock import MagicMock, patch

from app.core.storage import R2Client


def test_upload_file_calls_boto3_upload_file():
    with patch("app.core.storage.boto3.client") as mock_boto_client:
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3

        client = R2Client(
            account_id="acc",
            access_key_id="key",
            secret_access_key="secret",
            bucket_name="my-bucket",
        )
        key = client.upload_file("/tmp/local.mp4", "videos/local.mp4")

        mock_s3.upload_file.assert_called_once_with(
            "/tmp/local.mp4", "my-bucket", "videos/local.mp4"
        )
        assert key == "videos/local.mp4"


def test_generate_presigned_url_calls_boto3():
    with patch("app.core.storage.boto3.client") as mock_boto_client:
        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = "https://signed.example/url"
        mock_boto_client.return_value = mock_s3

        client = R2Client(
            account_id="acc",
            access_key_id="key",
            secret_access_key="secret",
            bucket_name="my-bucket",
        )
        url = client.generate_presigned_url("videos/local.mp4", expires_in=600)

        assert url == "https://signed.example/url"
        mock_s3.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "my-bucket", "Key": "videos/local.mp4"},
            ExpiresIn=600,
        )
