from pathlib import Path
import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError
import inspect
from app.config.settings import settings
from app.config.logger import logger

class S3Storage:
    def __init__(self):
        session_kwargs = {"region_name": settings.AWS_REGION}
        if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
            session_kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
            session_kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY

        self.session = aioboto3.Session(**session_kwargs)
        self.bucket = settings.AWS_S3_BUCKET
        self.region = settings.AWS_REGION
        self.presign_expires_seconds = settings.AWS_S3_PRESIGN_EXPIRES_SECONDS
        self.endpoint_url = f"https://s3.{self.region}.amazonaws.com"
        self._client_config = Config(signature_version="s3v4")

    def _client_kwargs(self) -> dict:
        return {"endpoint_url": self.endpoint_url, "config": self._client_config}

    async def upload_file_path(
        self,
        local_path: Path,
        bucket_path: str,
        *,
        content_type: str = "audio/mpeg",
    ) -> str:
        logger.info(f"Uploading {local_path} to S3 bucket {self.bucket} at {bucket_path}")
        try:
            async with self.session.client("s3", **self._client_kwargs()) as s3_client:
                extra_args = {"ContentType": content_type}
                await s3_client.upload_file(
                    str(local_path),
                    self.bucket,
                    bucket_path,
                    ExtraArgs=extra_args
                )
            return bucket_path
        except ClientError as e:
            logger.error(f"Failed to upload {local_path} to S3: {e}")
            raise

    async def upload_file_bytes(
        self,
        file_bytes: bytes,
        bucket_path: str,
        content_type: str = "audio/mpeg",
    ) -> str:
        logger.info(f"Uploading bytes to S3 bucket {self.bucket} at {bucket_path}")
        try:
            async with self.session.client("s3", **self._client_kwargs()) as s3_client:
                kwargs = {
                    "Bucket": self.bucket,
                    "Key": bucket_path,
                    "Body": file_bytes,
                    "ContentType": content_type,
                }
                await s3_client.put_object(
                    **kwargs
                )
            return bucket_path
        except ClientError as e:
            logger.error(f"Failed to upload bytes to S3: {e}")
            raise

    async def create_presigned_get_url(self, bucket_path: str, *, expires_in: int | None = None) -> str:
        # Works for private buckets, assuming caller credentials have s3:GetObject permissions.
        if expires_in is None:
            expires_in = self.presign_expires_seconds
        async with self.session.client("s3", **self._client_kwargs()) as s3_client:
            res = s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": bucket_path},
                ExpiresIn=int(expires_in),
            )
            if inspect.isawaitable(res):
                res = await res
            return res

    async def file_exists(self, bucket_path: str) -> bool:
        try:
            async with self.session.client("s3", **self._client_kwargs()) as s3_client:
                await s3_client.head_object(Bucket=self.bucket, Key=bucket_path)
            return True
        except ClientError as e:
            status_code = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            error_code = e.response.get("Error", {}).get("Code")
            if status_code == 404 or error_code in {"404", "NoSuchKey", "NotFound"}:
                return False
            logger.error(f"Failed to check S3 object exists at {bucket_path}: {e}")
            raise

    async def create_presigned_put_url(
        self,
        bucket_path: str,
        *,
        content_type: str = "application/octet-stream",
        expires_in: int | None = None,
    ) -> str:
    
        if expires_in is None:
            expires_in = self.presign_expires_seconds
        async with self.session.client("s3", **self._client_kwargs()) as s3_client:
            res = s3_client.generate_presigned_url(
                "put_object",
                Params={"Bucket": self.bucket, "Key": bucket_path, "ContentType": content_type},
                ExpiresIn=int(expires_in),
            )
            if inspect.isawaitable(res):
                res = await res
            return res

    async def download_file(self, bucket_path: str, local_path: Path):
        logger.info(f"Downloading {bucket_path} from S3 to {local_path}")
        try:
            async with self.session.client("s3", **self._client_kwargs()) as s3_client:
                await s3_client.download_file(self.bucket, bucket_path, str(local_path))
        except ClientError as e:
            logger.error(f"Failed to download {bucket_path} from S3: {e}")
            raise
