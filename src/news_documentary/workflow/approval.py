"""Approval binding: approval survives restarts, bound to video hash + script version."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def approve_job(job_root: str, job_id: str, destinations: tuple[str, ...] = ("youtube",), by: str = "operator") -> dict:
    jd = Path(job_root) / job_id
    script = json.loads((jd / "script.json").read_text(encoding="utf-8"))
    video = next((jd / "documentary.mp4").parent.glob("documentary.mp4"))
    vh = hashlib.sha256(video.read_bytes()).hexdigest()
    appr = {"approved": True, "video_hash": vh, "script_version": script.get("version", 1),
            "destinations": list(destinations), "by": by,
            "at": datetime.now(timezone.utc).isoformat()}
    (jd / "approval.json").write_text(json.dumps(appr, indent=2), encoding="utf-8")
    return appr
