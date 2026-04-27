import asyncio
import sys
from pathlib import Path
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.s3_storage import S3Storage
from app.config.settings import settings

async def test_s3_upload():
    print("Testing S3 Storage Service...")
    print(f"AWS Region: {settings.AWS_REGION}")
    print(f"Bucket: {settings.AWS_S3_BUCKET}")

    storage = S3Storage()
    print(f"S3 endpoint: {storage.endpoint_url}")

    test_key = f"test/{uuid.uuid4()}.txt"
    try:
        print(f"\nUploading test object to: {test_key}")
        s3_key = await storage.upload_file_bytes(
            b"This is a test file for S3 upload.\n",
            test_key,
            content_type="text/plain",
        )

        download_url = await storage.create_presigned_get_url(s3_key)
        example_put_url = await storage.create_presigned_put_url(
            f"test/{uuid.uuid4()}_put.txt",
            content_type="text/plain",
        )

        print("SUCCESS!")
        print(f"S3 key: {s3_key}")
        print(f"Presigned GET URL (open in browser): {download_url}")
        print(f"Example presigned PUT URL: {example_put_url}")
    except Exception as e:
        print(f"FAILED: {e!r}")

if __name__ == "__main__":
    asyncio.run(test_s3_upload())
