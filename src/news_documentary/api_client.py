"""Shared-mode API client: CLI <-> Express use the same backend as the browser.

Local mode (default, unchanged): `newsdoc run/chat/approve/resume` operate on
local JOB_ROOT + sqlite directly. Jobs here do NOT automatically appear in the
browser unless the API + worker share the same JOB_ROOT/DB files.

Shared mode: `newsdoc api-*` commands talk to the Express API (same as React).
A terminal-created shared job appears in the browser and vice versa, with the
same ownership + publishing rules. Requires API_BASE_URL + login token.
"""
from __future__ import annotations

import json
import os
import urllib.request


def _base() -> str:
    return os.environ.get("API_BASE_URL", "http://localhost:4000").rstrip("/")


def _token(args) -> str:
    tok = getattr(args, "token", "") or os.environ.get("NEWSDOC_TOKEN", "")
    if not tok:
        raise SystemExit("Missing auth token: `newsdoc api-login --email E --password P` first (saves NEWSDOC_TOKEN), or pass --token / set NEWSDOC_TOKEN.")
    return tok


def _req(method: str, path: str, token: str = "", payload: dict | None = None) -> dict | list:
    url = _base() + path
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode()
            return json.loads(body) if body else {}
    except Exception as e:
        # Surface server error bodies.
        try:
            import urllib.error as _e

            if isinstance(e, _e.HTTPError):
                print(e.read().decode()[:1000])
        except Exception:
            pass
        raise SystemExit(f"API error: {e}")


def token_path() -> str:
    return os.path.expanduser("~/.newsdoc_token")


def load_saved_token() -> str:
    for src in (os.environ.get("NEWSDOC_TOKEN", ""), ""):
        if src:
            return src
    try:
        with open(token_path()) as f:
            return f.read().strip()
    except OSError:
        return ""
