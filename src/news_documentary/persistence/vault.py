"""Server-side secret vault + account registry. Tokens never touch LLM, logs, browser, or git.

- Secrets live in data/tokens/<account_id>.json with 0600 perms (server filesystem only).
- Only last4 fingerprints are ever displayed/logged.
- Every account row has an owner; every operation filters by owner (authorization).
"""
from __future__ import annotations

import getpass
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import db as pdb


def current_owner(settings=None) -> str:
    env = (os.environ.get("OWNER_ID") or "").strip()
    if env:
        return env
    if settings is not None and getattr(settings, "owner_id", ""):
        return settings.owner_id  # type: ignore[attr-defined]
    try:
        return getpass.getuser() or "local-operator"
    except Exception:
        return "local-operator"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def vault_dir(db_path: str) -> Path:
    d = Path(db_path).parent / "tokens"
    d.mkdir(parents=True, exist_ok=True)
    return d


def vault_path(db_path: str, account_id: str) -> Path:
    if "/" in account_id or account_id in (".", ".."):
        raise ValueError("bad account id")
    return vault_dir(db_path) / f"{account_id}.json"


def store_secret(db_path: str, account_id: str, secret: dict) -> None:
    p = vault_path(db_path, account_id)
    p.write_text(json.dumps(secret), encoding="utf-8")
    os.chmod(p, 0o600)


def load_secret(db_path: str, account_id: str) -> dict:
    p = vault_path(db_path, account_id)
    if not p.exists():
        raise RuntimeError("credential vault entry missing (account disconnected?)")
    return json.loads(p.read_text(encoding="utf-8"))


def delete_secret(db_path: str, account_id: str) -> None:
    p = vault_path(db_path, account_id)
    if p.exists():
        p.unlink()


def fingerprint(secret: dict) -> str:
    for v in secret.values():
        if isinstance(v, str) and len(v) >= 8:
            return f"…{v[-4:]}"
    return "…n/a"


def redact(obj: object) -> object:
    """Deep-redact anything that looks like a credential for logs/UI."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            kl = k.lower()
            if any(t in kl for t in ("token", "secret", "password", "key", "auth", "credential")):
                out[k] = fingerprint({"v": v}) if isinstance(v, str) else "[redacted]"
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    return obj


def connect_account(db_path: str, owner: str, platform: str, label: str,
                    secret: dict, public_meta: dict) -> dict:
    pdb.migrate(db_path)
    acc_id = f"{platform}-{uuid.uuid4().hex[:8]}"
    store_secret(db_path, acc_id, secret)
    c = pdb.connect(db_path)
    c.execute("INSERT INTO accounts(id,owner,platform,label,status,public_meta,created_at,updated_at)"
              " VALUES(?,?,?,?,?,?,?,?)",
              (acc_id, owner, platform, label, "connected",
               json.dumps(public_meta, ensure_ascii=False), _now(), _now()))
    c.commit(); c.close()
    # NOTE: connecting stores credentials only. No publish path runs here by construction.
    return {"id": acc_id, "platform": platform, "label": label, "status": "connected",
            "credential": fingerprint(secret), "public_meta": public_meta}


def list_accounts(db_path: str, owner: str) -> list[dict]:
    pdb.migrate(db_path)
    c = pdb.connect(db_path)
    rows = c.execute("SELECT id,platform,label,status,public_meta,created_at FROM accounts"
                     " WHERE owner=? ORDER BY created_at DESC", (owner,)).fetchall()
    c.close()
    return [{"id": r[0], "platform": r[1], "label": r[2], "status": r[3],
             "public_meta": json.loads(r[4] or "{}"), "created_at": r[5]} for r in rows]


def get_account(db_path: str, owner: str, account_id: str) -> dict | None:
    pdb.migrate(db_path)
    c = pdb.connect(db_path)
    r = c.execute("SELECT id,platform,label,status,public_meta FROM accounts WHERE id=? AND owner=?",
                  (account_id, owner)).fetchone()
    c.close()
    if not r:
        return None
    return {"id": r[0], "platform": r[1], "label": r[2], "status": r[3],
            "public_meta": json.loads(r[4] or "{}")}


def disconnect_account(db_path: str, owner: str, account_id: str) -> bool:
    """Disconnect deletes the server-side secret. Disconnected accounts can never publish."""
    acc = get_account(db_path, owner, account_id)
    if not acc:
        return False
    delete_secret(db_path, account_id)
    c = pdb.connect(db_path)
    c.execute("UPDATE accounts SET status='disconnected',updated_at=? WHERE id=? AND owner=?",
              (_now(), account_id, owner))
    c.commit(); c.close()
    return True
