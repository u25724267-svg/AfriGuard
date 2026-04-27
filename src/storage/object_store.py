"""
AfriGuard — Object store abstraction.
Supports local filesystem (default) and S3-compatible backends.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

OBJECT_STORE_TYPE = os.environ.get("OBJECT_STORE_TYPE", "local")
DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))


class LocalObjectStore:
    """Simple local filesystem object store."""

    def __init__(self, base_dir: Path = DATA_DIR):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        path = self.base_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def put_json(self, key: str, data: Any) -> None:
        path = self._resolve(key)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.debug("object_store.put_json", key=key, path=str(path))

    def get_json(self, key: str) -> Any:
        path = self._resolve(key)
        if not path.exists():
            raise FileNotFoundError(f"Object not found: {key}")
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def put_text(self, key: str, text: str) -> None:
        path = self._resolve(key)
        path.write_text(text, encoding="utf-8")
        logger.debug("object_store.put_text", key=key)

    def get_text(self, key: str) -> str:
        path = self._resolve(key)
        if not path.exists():
            raise FileNotFoundError(f"Object not found: {key}")
        return path.read_text(encoding="utf-8")

    def put_bytes(self, key: str, data: bytes) -> None:
        path = self._resolve(key)
        path.write_bytes(data)

    def get_bytes(self, key: str) -> bytes:
        path = self._resolve(key)
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        return self._resolve(key).exists()

    def list_keys(self, prefix: str = "") -> list[str]:
        search_path = self.base_dir / prefix if prefix else self.base_dir
        if not search_path.exists():
            return []
        return [
            str(p.relative_to(self.base_dir))
            for p in search_path.rglob("*")
            if p.is_file()
        ]

    def delete(self, key: str) -> None:
        path = self._resolve(key)
        if path.exists():
            path.unlink()

    def copy(self, src_key: str, dst_key: str) -> None:
        shutil.copy2(self._resolve(src_key), self._resolve(dst_key))


class S3ObjectStore:
    """S3-compatible object store (AWS S3 / MinIO)."""

    def __init__(self):
        import boto3

        self.bucket = os.environ["AWS_BUCKET_NAME"]
        self.client = boto3.client(
            "s3",
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )

    def put_json(self, key: str, data: Any) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType="application/json")

    def get_json(self, key: str) -> Any:
        resp = self.client.get_object(Bucket=self.bucket, Key=key)
        return json.loads(resp["Body"].read())

    def put_text(self, key: str, text: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=text.encode("utf-8"), ContentType="text/plain")

    def get_text(self, key: str) -> str:
        resp = self.client.get_object(Bucket=self.bucket, Key=key)
        return resp["Body"].read().decode("utf-8")

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except self.client.exceptions.ClientError:
            return False

    def list_keys(self, prefix: str = "") -> list[str]:
        paginator = self.client.get_paginator("list_objects_v2")
        keys = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys


def get_object_store() -> LocalObjectStore | S3ObjectStore:
    """Factory — returns the configured object store."""
    store_type = OBJECT_STORE_TYPE.lower()
    if store_type == "local":
        return LocalObjectStore()
    elif store_type == "s3":
        return S3ObjectStore()
    else:
        raise ValueError(f"Unknown OBJECT_STORE_TYPE: {store_type}")
