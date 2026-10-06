"""Media storage adapter boundary: local disk for dev, S3-compatible for deploy.

- LocalStorage: JOB_ROOT on local filesystem (development default).
- S3Storage: S3-compatible bucket via boto3 (deployment). Reports `unconfigured`
  with exact env needed when boto3/credentials are missing — never silent.
- Graph/worker code uses `get_storage()` and artifact *references* (keys),
  keeping large media out of queue payloads and LLM messages.
"""
from __future__ import annotations

import os
from pathlib import Path


class LocalStorage:
    name = "local"

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def job_dir(self, job_id: str) -> Path:
        p = self.root / job_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def ref(self, job_id: str, filename: str) -> str:
        return f"{job_id}/{filename}"


class S3Storage:
    """S3-compatible object storage (AWS S3, R2, MinIO)."""

    name = "s3"

    def __init__(self, bucket: str, prefix: str = ""):
        if not bucket:
            raise RuntimeError(
                "Object storage unconfigured: set STORAGE_BACKEND=s3, S3_BUCKET=<bucket>, "
                "S3_REGION, S3_ENDPOINT_URL (for R2/MinIO), AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY."
            )
        try:
            import boto3  # type: ignore[import-not-found]
        except Exception as e:
            raise RuntimeError(f"Object storage unconfigured: boto3 missing ({e}); pip install boto3.") from e
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self._s3 = boto3.client(
            "s3",
            region_name=os.environ.get("S3_REGION", "auto"),
            endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None,
        )

    def job_dir(self, job_id: str) -> Path:
        # Staging dir: render locally, then upload. Keeps FFmpeg local.
        p = Path(os.environ.get("JOB_ROOT", "data/jobs")) / job_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def ref(self, job_id: str, filename: str) -> str:
        key = f"{self.prefix + '/' if self.prefix else ''}{job_id}/{filename}"
        return f"s3://{self.bucket}/{key}"

    def upload_file(self, local: Path, job_id: str, filename: str) -> str:
        key = f"{self.prefix + '/' if self.prefix else ''}{job_id}/{filename}"
        self._s3.upload_file(str(local), self.bucket, key)
        return self.ref(job_id, filename)


def get_storage(root: str | Path = ""):
    backend = os.environ.get("STORAGE_BACKEND", "local")
    if backend == "s3":
        return S3Storage(os.environ.get("S3_BUCKET", ""), os.environ.get("S3_PREFIX", ""))
    return LocalStorage(root or os.environ.get("JOB_ROOT", "data/jobs"))
