import mimetypes
from abc import ABC, abstractmethod
from pathlib import Path

import boto3

from app.core.config import get_settings


class BaseStorage(ABC):
    @abstractmethod
    async def save_bytes(self, key: str, content: bytes, mime_type: str = "image/jpeg") -> str:
        raise NotImplementedError

    @abstractmethod
    async def read_bytes(self, key: str) -> bytes:
        raise NotImplementedError


class LocalStorage(BaseStorage):
    def __init__(self, root: str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    async def save_bytes(self, key: str, content: bytes, mime_type: str = "image/jpeg") -> str:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return key

    async def read_bytes(self, key: str) -> bytes:
        return (self.root / key).read_bytes()


class S3Storage(BaseStorage):
    def __init__(self) -> None:
        settings = get_settings()
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            endpoint_url=settings.s3_endpoint_url,
        )

    async def save_bytes(self, key: str, content: bytes, mime_type: str = "image/jpeg") -> str:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=content, ContentType=mime_type)
        return key

    async def read_bytes(self, key: str) -> bytes:
        resp = self.client.get_object(Bucket=self.bucket, Key=key)
        return resp["Body"].read()


def detect_mime(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def build_storage() -> BaseStorage:
    settings = get_settings()
    if settings.storage_mode == "s3":
        return S3Storage()
    return LocalStorage(settings.local_storage_path)
