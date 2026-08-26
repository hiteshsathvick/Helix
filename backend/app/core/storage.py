import hashlib
from typing import BinaryIO

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.errors import PayloadTooLargeError


def get_s3_client():
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


async def ensure_bucket_exists() -> None:
    """MinIO doesn't create the bucket on its own — called once at app
    startup (see app.main's lifespan)."""
    settings = get_settings()

    def _ensure() -> None:
        client = get_s3_client()
        try:
            client.head_bucket(Bucket=settings.s3_bucket)
        except ClientError:
            client.create_bucket(Bucket=settings.s3_bucket)

    await run_in_threadpool(_ensure)


class _HashingReader:
    """Wraps an upload's file object, computing a running SHA-256 digest as
    boto3 reads through it during the upload — checksums the file in the
    same pass instead of buffering it whole to hash separately (SPEC.md
    §25: large files are streamed, not loaded whole)."""

    def __init__(self, fileobj: BinaryIO, max_bytes: int) -> None:
        self._fileobj = fileobj
        self._hasher = hashlib.sha256()
        self._max_bytes = max_bytes
        self._bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._fileobj.read(size)
        self._bytes_read += len(chunk)
        if self._bytes_read > self._max_bytes:
            raise PayloadTooLargeError(
                f"file exceeds the {self._max_bytes} byte upload limit",
            )
        self._hasher.update(chunk)
        return chunk

    @property
    def checksum(self) -> str:
        return self._hasher.hexdigest()


async def upload_object(fileobj: BinaryIO, key: str) -> str:
    """Streams fileobj to the bucket under `key`; returns its SHA-256 hex checksum."""
    settings = get_settings()
    hashing_reader = _HashingReader(fileobj, settings.documents_max_upload_bytes)

    def _upload() -> None:
        client = get_s3_client()
        client.upload_fileobj(hashing_reader, settings.s3_bucket, key)

    await run_in_threadpool(_upload)
    return hashing_reader.checksum


async def delete_object(key: str) -> None:
    settings = get_settings()

    def _delete() -> None:
        client = get_s3_client()
        client.delete_object(Bucket=settings.s3_bucket, Key=key)

    await run_in_threadpool(_delete)


async def download_object(key: str) -> bytes:
    settings = get_settings()

    def _download() -> bytes:
        client = get_s3_client()
        response = client.get_object(Bucket=settings.s3_bucket, Key=key)
        return response["Body"].read()

    return await run_in_threadpool(_download)
