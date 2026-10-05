"""Publishing adapters. YouTube real via official Data API; FB/IG are explicit stubs (milestone 5)."""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(65536), b""):
            h.update(b)
    return h.hexdigest()


class FixturePublisher:
    """Labeled fake receipt for offline tests. Never claims a real upload."""
    destination = "youtube"

    def upload(self, video: Path, title: str, description: str, visibility: str = "unlisted") -> dict:
        return {"destination": self.destination, "remote_id": f"FIXTURE-{sha256_file(video)[:10]}",
                "url": "fixture://no-upload-performed", "visibility": visibility,
                "status": "succeeded-fixture",
                "timestamp": datetime.now(timezone.utc).isoformat(), "fixture": True}


class YoutubePublisher:
    """Real YouTube upload via google-api-python-client (OAuth desktop flow).
    Setup: create OAuth client (Desktop) in Google Cloud, enable YouTube Data API v3,
    download client_secrets.json, set YOUTUBE_CLIENT_SECRETS + run `newsdoc auth-youtube` once."""

    destination = "youtube"

    def __init__(self, client_secrets: str, token_file: str):
        self.client_secrets = client_secrets
        self.token_file = token_file

    def _service(self):
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        if not Path(self.token_file).exists():
            raise RuntimeError("YouTube token missing. Run `newsdoc auth-youtube` first.")
        creds = Credentials.from_authorized_user_file(
            self.token_file, ["https://www.googleapis.com/auth/youtube.upload"])
        return build("youtube", "v3", credentials=creds)

    def upload(self, video: Path, title: str, description: str, visibility: str = "unlisted",
               retries: int = 3) -> dict:
        from googleapiclient.http import MediaFileUpload

        body = {"snippet": {"title": title[:100], "description": description[:4000], "categoryId": "25"},
                "status": {"privacyStatus": visibility, "selfDeclaredMadeForKids": False}}
        last = None
        for attempt in range(retries):
            try:
                svc = self._service()
                req = svc.videos().insert(part="snippet,status", body=body,
                                          media_body=MediaFileUpload(str(video), resumable=True))
                resp = req.execute()
                rid = resp.get("id", "")
                return {"destination": "youtube", "remote_id": rid,
                        "url": f"https://youtu.be/{rid}" if rid else "",
                        "visibility": visibility, "status": "succeeded",
                        "timestamp": datetime.now(timezone.utc).isoformat(), "fixture": False}
            except Exception as e:  # classify: auth/validation permanent; others retryable
                msg = str(e)
                last = e
                if "invalid_grant" in msg or "invalid_client" in msg or "HttpError 40" in msg:
                    raise  # permanent auth/validation: do not blind-retry
                time.sleep(min(30, 2 ** attempt))
        raise RuntimeError(f"YouTube upload failed after {retries} retries: {last}")


class FacebookStub:
    destination = "facebook"
    def upload(self, *a, **k) -> dict:
        raise RuntimeError("Facebook integration NOT implemented (milestone 5). Verify Page permissions + app review first.")


class InstagramStub:
    destination = "instagram"
    def upload(self, *a, **k) -> dict:
        raise RuntimeError("Instagram integration NOT implemented (milestone 5). Verify Business account + container API eligibility first.")


def get_publisher(settings, destination: str):
    mode = getattr(settings, "youtube_publish_mode", "fixture")
    if destination == "youtube":
        if mode == "real":
            return YoutubePublisher(settings.youtube_client_secrets, settings.youtube_token_file)
        return FixturePublisher()
    if destination == "facebook":
        return FacebookStub()
    return InstagramStub()


def publish_with_reconciliation(settings, db_path: str, job_id: str, destination: str,
                                video: Path, title: str, description: str, visibility: str,
                                artifact_hash: str) -> dict:
    """Idempotent publish: persist intent -> upload -> reconcile ambiguous timeouts.

    - UNIQUE(logical_key) prevents duplicates (job+destination+hash).
    - On ambiguous failure, receipt stays 'unknown-timeout' for operator resolution
      instead of blind retry. Resume skips destinations already 'succeeded'."""
    from . import manager_helpers as _mh  # local import to keep module light
    return _mh.publish_with_reconciliation(settings, db_path, job_id, destination, video,
                                           title, description, visibility, artifact_hash)
