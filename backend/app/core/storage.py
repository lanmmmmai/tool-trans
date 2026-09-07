import boto3

from app.core.config import settings


class R2Client:
    def __init__(
        self,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket_name: str,
    ):
        self.bucket_name = bucket_name
        self._s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
        )

    def upload_file(self, local_path: str, key: str) -> str:
        self._s3.upload_file(local_path, self.bucket_name, key)
        return key

    def download_file(self, key: str, local_path: str) -> None:
        self._s3.download_file(self.bucket_name, key, local_path)

    def delete(self, key: str) -> None:
        self._s3.delete_object(Bucket=self.bucket_name, Key=key)

    def generate_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        return self._s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket_name, "Key": key},
            ExpiresIn=expires_in,
        )


def get_r2_client() -> R2Client:
    return R2Client(
        account_id=settings.r2_account_id,
        access_key_id=settings.r2_access_key_id,
        secret_access_key=settings.r2_secret_access_key,
        bucket_name=settings.r2_bucket_name,
    )
