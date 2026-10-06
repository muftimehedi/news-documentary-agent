"""Common publishing adapter interface + platform implementations.

Publishing stays separate from video generation and the Deep Agent reasoning loop:
adapters only receive file paths + metadata + server-side credentials, never LLM
objects. A successful real upload is reported ONLY on platform confirmation.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AdapterError(Exception):
    def __init__(self, message: str, permanent: bool = False):
        super().__init__(message)
        self.permanent = permanent


class BaseAdapter:
    platform: str = ""
    display: str = ""
    # real = live platform API; fixture = labeled test double (offline)
    mode: str = "real"
    setup_help: str = ""

    def verify(self, creds: dict) -> dict:
        """Check credentials without publishing. Returns public account info."""
        raise NotImplementedError

    def validate(self, video: Path, title: str, description: str, visibility: str) -> list[str]:
        return []

    def upload(self, video: Path, title: str, description: str, visibility: str,
               creds: dict, job_id: str = "") -> dict:
        raise NotImplementedError

    # -- shared helpers -----------------------------------------------------
    @staticmethod
    def _need(cond: bool, msg: str, out: list[str]) -> None:
        if not cond:
            out.append(msg)

    @staticmethod
    def _size_mb(p: Path) -> float:
        return p.stat().st_size / (1024 * 1024)


# ---------------------------------------------------------------- YouTube ---
class YouTubeAdapter(BaseAdapter):
    platform = "youtube"
    display = "YouTube"
    setup_help = ("Google Cloud → enable YouTube Data API v3 → OAuth client (Desktop) → "
                  "`newsdoc auth-youtube --account LABEL` → token stored server-side. "
                  "Scope: youtube.upload. Docs: developers.google.com/youtube/v3/docs.")

    VALID_VIS = ("unlisted", "private", "public")

    def verify(self, creds: dict) -> dict:
        token_file = creds.get("token_file", "")
        if not token_file or not Path(token_file).exists():
            raise AdapterError("YouTube token missing. Run `newsdoc auth-youtube --account LABEL` first.",
                               permanent=True)
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            c = Credentials.from_authorized_user_file(
                token_file, ["https://www.googleapis.com/auth/youtube.upload"])
            ch = build("youtube", "v3", credentials=c).channels().list(
                part="snippet", mine=True).execute()
            title = (ch.get("items") or [{}])[0].get("snippet", {}).get("title", "YouTube channel")
            return {"account": title}
        except Exception as e:
            raise AdapterError(f"YouTube verify failed: {e}", permanent="invalid_grant" in str(e))

    def validate(self, video, title, desc, visibility) -> list[str]:
        errs: list[str] = []
        self._need(video.suffix.lower() in (".mp4", ".mov"), "YouTube: need MP4/MOV", errs)
        self._need(visibility in self.VALID_VIS, f"YouTube visibility must be one of {self.VALID_VIS}", errs)
        self._need(1 <= len(title) <= 100, "YouTube title: 1–100 chars", errs)
        self._need(len(desc) <= 5000, "YouTube description: max 5000 chars", errs)
        return errs

    def upload(self, video, title, desc, visibility, creds, job_id="") -> dict:
        from googleapiclient.http import MediaFileUpload

        svc_builder = creds.get("_service")
        if svc_builder is None:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            tf = creds.get("token_file", "")
            if not tf or not Path(tf).exists():
                raise AdapterError("YouTube token missing (account disconnected?).", permanent=True)
            c = Credentials.from_authorized_user_file(
                tf, ["https://www.googleapis.com/auth/youtube.upload"])
            svc = build("youtube", "v3", credentials=c)
        else:
            svc = svc_builder()
        body = {"snippet": {"title": title[:100], "description": desc[:5000], "categoryId": "25"},
                "status": {"privacyStatus": visibility, "selfDeclaredMadeForKids": False}}
        last: Exception | None = None
        for attempt in range(3):
            try:
                req = svc.videos().insert(part="snippet,status", body=body,
                                          media_body=MediaFileUpload(str(video), resumable=True))
                resp = req.execute()
                rid = resp.get("id", "")
                if not rid:
                    raise AdapterError("YouTube: upload returned no video id", permanent=True)
                return {"destination": "youtube", "remote_id": rid,
                        "url": f"https://youtu.be/{rid}", "visibility": visibility,
                        "status": "succeeded", "timestamp": _now(), "fixture": False}
            except AdapterError:
                raise
            except Exception as e:
                last = e
                if any(k in str(e) for k in ("invalid_grant", "invalid_client", "HttpError 40")):
                    raise AdapterError(f"YouTube auth/validation error: {e}", permanent=True)
                time.sleep(min(30, 2 ** attempt))
        raise AdapterError(f"YouTube upload failed after retries: {last}")


# --------------------------------------------------------------- Facebook ---
class FacebookAdapter(BaseAdapter):
    """Real Meta Video API for Facebook Pages (official flow, verified Oct 2026):
    Resumable Upload API -> video handle -> POST /{PAGE_ID}/videos.
    Requires: Page access token (person with CREATE_CONTENT task) + permissions
    pages_show_list, pages_read_engagement, pages_manage_posts.
    No personal-profile publishing via API. App review needed for public use.
    Docs: developers.facebook.com/docs/video-api/guides/publishing
    """

    platform = "facebook"
    display = "Facebook"
    API_VERSION = "v21.0"
    setup_help = ("Meta app + Facebook Login (pages_show_list, pages_read_engagement, "
                  "pages_manage_posts) → long-lived User token → GET /me/accounts → paste the "
                  "Page access token. Only Pages (CREATE_CONTENT task); no profile uploads. "
                  "Public use needs Meta app review.")

    def _api(self, path: str, token: str, data: dict | None = None,
             files: dict | None = None) -> dict:
        import requests

        if path.startswith("http"):
            url = path
        else:
            url = f"https://graph.facebook.com/{self.API_VERSION}/{path.lstrip('/')}"
        params = {"access_token": token}
        if files:
            r = requests.post(url, params=params, data=data or {}, files=files, timeout=120)
        elif data is not None:
            r = requests.post(url, params=params, data=data, timeout=60)
        else:
            r = requests.get(url, params=params, timeout=30)
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:300]}
        if r.status_code >= 400 or "error" in body:
            err = (body.get("error") or {})
            raise AdapterError(f"Facebook: {err.get('message', body)}",
                               permanent=r.status_code in (400, 401, 403))
        return body

    def verify(self, creds: dict) -> dict:
        token = creds.get("page_token", "")
        page_id = creds.get("page_id", "")
        if not token or not page_id:
            raise AdapterError("Facebook: page_id + page access token required.", permanent=True)
        me = self._api(str(page_id), token, None)
        return {"account": me.get("name", page_id), "id": me.get("id", page_id)}

    def validate(self, video, title, desc, visibility) -> list[str]:
        # Limits per Meta Video API docs family: MP4/MOV, <=10GB, <=240min; our renders are far smaller.
        errs: list[str] = []
        self._need(video.suffix.lower() in (".mp4", ".mov"), "Facebook: need MP4/MOV", errs)
        self._need(self._size_mb(video) <= 10 * 1024, "Facebook: max 10GB", errs)
        self._need(1 <= len(title) <= 255, "Facebook title: 1–255 chars", errs)
        self._need(visibility in ("public", "unlisted", "private"),
                   "Facebook visibility must be public/unlisted/private", errs)
        return errs

    def upload(self, video, title, desc, visibility, creds, job_id="") -> dict:
        import requests

        token = creds.get("page_token", "")
        page_id = creds.get("page_id", "")
        if not token or not page_id:
            raise AdapterError("Facebook account disconnected or incomplete.", permanent=True)
        size = video.stat().st_size
        # 1) start resumable session (official Resumable Upload API)
        sess = self._api("app/uploads", token,
                         {"file_name": video.name, "file_length": str(size), "file_type": "video/mp4"})
        session_id = sess.get("id", "")
        if not session_id:
            raise AdapterError(f"Facebook: upload session failed: {sess}")
        # 2) transfer bytes
        url = f"https://graph.facebook.com/{self.API_VERSION}/{session_id}"
        with open(video, "rb") as f:
            r = requests.post(url, headers={"Authorization": f"OAuth {token}",
                                            "file_offset": "0"},
                              data=f, timeout=600)
        try:
            up = r.json()
        except Exception:
            up = {}
        handle = up.get("h", "")
        if r.status_code >= 400 or not handle:
            raise AdapterError(f"Facebook: upload transfer failed: {str(up)[:300]}")
        # 3) publish to the Page
        pub = self._api(f"{page_id}/videos", token,
                        {"title": title[:255], "description": desc,
                         "fbuploader_video_file_chunk": handle})
        vid = pub.get("id", "")
        if not vid:
            raise AdapterError(f"Facebook: publish returned no id: {pub}", permanent=True)
        return {"destination": "facebook", "remote_id": vid,
                "url": f"https://www.facebook.com/{vid}", "visibility": visibility,
                "status": "succeeded", "timestamp": _now(), "fixture": False}


# ---------------------------------------------------------------------- X ---
class XAdapter(BaseAdapter):
    """Real X API v2 chunked media upload (verified Oct 2026, docs.x.com):
    INIT -> APPEND (<=5MB chunks) -> FINALIZE -> STATUS poll -> POST /2/tweets.
    Needs user-context token with scopes tweet.write + media.write (+ users.read).
    Note: X bills media-upload requests (~$0.010/req on pay-per-use tiers).
    Our renders (<=90s, few MB) fit default caps (20min/8GB, 1 video/post).
    """

    platform = "x"
    display = "X"
    setup_help = ("X developer app → OAuth 2.0 (PKCE) user tokens with scopes tweet.read "
                  "tweet.write users.read offline.access media.write → paste access token "
                  "(+ refresh token). Posting user needs no Premium for <=20min video.")

    def _req(self, method: str, url: str, token: str, **kw) -> dict:
        import requests

        r = requests.request(method, url,
                             headers={"Authorization": f"Bearer {token}"}, timeout=kw.pop("timeout", 60), **kw)
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:300]}
        if r.status_code >= 400 or (isinstance(body, dict) and body.get("errors")):
            raise AdapterError(f"X: {str(body)[:300]}",
                               permanent=r.status_code in (400, 401, 403))
        return body if isinstance(body, dict) else {"data": body}

    def verify(self, creds: dict) -> dict:
        token = creds.get("access_token", "")
        if not token:
            raise AdapterError("X: user access token required.", permanent=True)
        me = self._req("GET", "https://api.x.com/2/users/me", token)
        u = (me.get("data") or {})
        return {"account": "@" + u.get("username", "?"), "id": u.get("id", "")}

    def validate(self, video, title, desc, visibility) -> list[str]:
        import subprocess

        errs: list[str] = []
        self._need(video.suffix.lower() == ".mp4", "X: need MP4", errs)
        self._need(self._size_mb(video) <= 8 * 1024, "X: max 8GB (default accounts)", errs)
        try:
            r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
                               capture_output=True, text=True, timeout=30)
            dur = float(r.stdout.strip())
            self._need(dur <= 20 * 60, "X: max 20min video (default accounts)", errs)
        except Exception:
            pass
        text = f"{title} {desc}".strip()
        self._need(len(text) <= 280, f"X post text: max 280 chars (got {len(text)})", errs)
        return errs

    def upload(self, video, title, desc, visibility, creds, job_id="") -> dict:
        import requests

        token = creds.get("access_token", "")
        if not token:
            raise AdapterError("X account disconnected.", permanent=True)
        size = video.stat().st_size
        init = self._req("POST", "https://api.x.com/2/media/upload/initialize", token,
                         json={"media_type": "video/mp4", "total_bytes": size,
                               "media_category": "tweet_video"})
        mid = ((init.get("data") or {}).get("id")) or init.get("id", "")
        if not mid:
            raise AdapterError(f"X: INIT failed: {str(init)[:200]}")
        with open(video, "rb") as f:
            idx = 0
            while True:
                chunk = f.read(4 * 1024 * 1024)
                if not chunk:
                    break
                last = None
                for _ in range(3):
                    try:
                        requests.post(f"https://api.x.com/2/media/upload/{mid}/append",
                                      headers={"Authorization": f"Bearer {token}"},
                                      files={"media": (f"chunk{idx}.mp4", chunk, "video/mp4")},
                                      data={"segment_index": str(idx)}, timeout=300).raise_for_status()
                        last = None
                        break
                    except Exception as e:
                        last = e
                        time.sleep(2)
                if last is not None:
                    raise AdapterError(f"X: APPEND chunk {idx} failed: {last}")
                idx += 1
        fin = self._req("POST", f"https://api.x.com/2/media/upload/{mid}/finalize", token)
        info = ((fin.get("data") or {}).get("processing_info")) or fin.get("processing_info")
        for _ in range(30):
            if not info or info.get("state") == "succeeded":
                break
            if info.get("state") == "failed":
                raise AdapterError(f"X: media processing failed: {info}", permanent=True)
            time.sleep(max(1, int(info.get("check_after_secs", 2))))
            st = self._req("GET", "https://api.x.com/2/media/upload", token,
                           params={"command": "STATUS", "media_id": mid})
            info = (st.get("processing_info")) or ((st.get("data") or {}).get("processing_info"))
        tw = self._req("POST", "https://api.x.com/2/tweets", token,
                       json={"text": f"{title} {desc}".strip()[:280], "media": {"media_ids": [str(mid)]}})
        tid = ((tw.get("data") or {}).get("id")) or ""
        if not tid:
            raise AdapterError(f"X: tweet create returned no id: {str(tw)[:200]}", permanent=True)
        return {"destination": "x", "remote_id": tid,
                "url": f"https://x.com/i/status/{tid}", "visibility": visibility,
                "status": "succeeded", "timestamp": _now(), "fixture": False}


# ----------------------------------------------------------------- Hikmah ---
class HikmahAdapter(BaseAdapter):
    """Real Hikmah API (verified from hikmah-web repo, Oct 2026):
    POST {base}/api/posts, Laravel Sanctum Bearer, multipart
    type=video + content + items[0]=@file. Response data.uuid/data.slug.
    Limits (config/post.php): 1 video/post, flv/mp4/wmv/3gp/mov/avi/ts,
    100MB/video, content <=20000 chars. Privacy 1=Everyone/2=Followers/3=OnlyMe.
    Auth gap (verified): Hikmah exposes NO public OAuth; personal access tokens
    are issued server-side. Connect = paste base URL + token obtained from your
    Hikmah account/server admin.
    """

    platform = "hikmah"
    display = "Hikmah"
    setup_help = ("Hikmah has no public OAuth (verified in hikmah-web source). Paste your "
                  "instance base URL (e.g. https://hikmah.net) and a Sanctum personal "
                  "access token with post permission, obtained from your Hikmah account "
                  "or server admin. Posting creates type=video via POST /api/posts.")
    PRIVACY = {"public": "1", "unlisted": "2", "private": "3"}

    def _req(self, method: str, url: str, token: str, **kw) -> dict:
        import requests

        r = requests.request(method, url, headers={"Authorization": f"Bearer {token}",
                                                  "Accept": "application/json"},
                             timeout=kw.pop("timeout", 120), **kw)
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:300]}
        if r.status_code >= 400:
            raise AdapterError(f"Hikmah ({r.status_code}): {str(body)[:300]}",
                               permanent=r.status_code in (400, 401, 403, 422))
        return body if isinstance(body, dict) else {"data": body}

    def verify(self, creds: dict) -> dict:
        base = (creds.get("base_url", "") or "").rstrip("/")
        token = creds.get("token", "")
        if not base or not token:
            raise AdapterError("Hikmah: base URL + API token required.", permanent=True)
        me = self._req("GET", f"{base}/api/user/me", token)
        data = me.get("data", me)
        name = data.get("user_name") or data.get("name") or data.get("email") or "Hikmah user"
        return {"account": name}

    def validate(self, video, title, desc, visibility) -> list[str]:
        errs: list[str] = []
        self._need(video.suffix.lower().lstrip(".") in
                   ("flv", "mp4", "wmv", "3gp", "mov", "avi", "ts"),
                   "Hikmah: video must be flv/mp4/wmv/3gp/mov/avi/ts", errs)
        self._need(self._size_mb(video) <= 100, "Hikmah: max 100MB/video", errs)
        content = f"{title}\n\n{desc}".strip()
        self._need(len(content) <= 20000, "Hikmah content: max 20000 chars", errs)
        self._need(visibility in self.PRIVACY, "Hikmah visibility: public/unlisted/private", errs)
        return errs

    def upload(self, video, title, desc, visibility, creds, job_id="") -> dict:
        base = (creds.get("base_url", "") or "").rstrip("/")
        token = creds.get("token", "")
        if not base or not token:
            raise AdapterError("Hikmah account disconnected.", permanent=True)
        import requests

        content = f"{title}\n\n{desc}".strip()[:20000]
        with open(video, "rb") as f:
            body = self._req("POST", f"{base}/api/posts", token, timeout=600,
                             data={"type": "video", "content": content,
                                   "privacy": self.PRIVACY[visibility]},
                             files={"items[0]": (video.name, f, "video/mp4")})
        data = body.get("data", {}) or {}
        uuid_ = data.get("uuid", "")
        slug = data.get("slug", "")
        if not uuid_:
            raise AdapterError(f"Hikmah: post created without uuid: {str(body)[:200]}", permanent=True)
        url = f"{base}/posts/{slug}" if slug else ""
        return {"destination": "hikmah", "remote_id": uuid_, "url": url,
                "visibility": visibility, "status": "succeeded",
                "timestamp": _now(), "fixture": False}


# ---------------------------------------------------------------- Fixture ---
class FixtureAdapter(BaseAdapter):
    """Labeled test double. NEVER reports a real upload."""

    platform = "fixture"
    display = "Fixture (test)"
    mode = "fixture"
    setup_help = "No setup. For offline tests only."

    def verify(self, creds: dict) -> dict:
        return {"account": "fixture-test-account"}

    def upload(self, video, title, desc, visibility, creds, job_id="") -> dict:
        import hashlib

        h = hashlib.sha256(video.read_bytes()).hexdigest()[:10]
        return {"destination": "fixture", "remote_id": f"FIXTURE-{h}",
                "url": "fixture://no-upload-performed", "visibility": visibility,
                "status": "succeeded-fixture", "timestamp": _now(), "fixture": True}


ADAPTERS: dict[str, BaseAdapter] = {
    "youtube": YouTubeAdapter(),
    "facebook": FacebookAdapter(),
    "x": XAdapter(),
    "hikmah": HikmahAdapter(),
    "fixture": FixtureAdapter(),
}


def get_adapter(platform: str) -> BaseAdapter:
    try:
        return ADAPTERS[platform]
    except KeyError:
        raise AdapterError(f"Unsupported platform: {platform} (supported: youtube, facebook, x, hikmah)",
                           permanent=True)


def _json_safe(o):
    return json.loads(json.dumps(o, default=str))
