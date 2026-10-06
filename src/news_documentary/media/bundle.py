"""Manual publishing path: no account needed. Assembles downloadable assets +
a metadata text file (title, description, captions, source links) for manual upload."""
from __future__ import annotations

import json
import re
from pathlib import Path


def srt_to_text(srt_path: Path) -> str:
    lines = []
    for ln in srt_path.read_text(encoding="utf-8").splitlines():
        t = ln.strip()
        if not t or t.isdigit() or "-->" in t:
            continue
        lines.append(t)
    # de-dupe consecutive repeats
    out = [l for i, l in enumerate(lines) if i == 0 or l != lines[i - 1]]
    return "\n".join(out)


def build_manual_bundle(job_root: str, job_id: str, title: str = "",
                        description: str = "") -> dict[str, str]:
    """Returns {name: absolute_path} for: video, thumbnail, subtitles, metadata file."""
    from ..publishing.service import default_meta

    jd = Path(job_root) / job_id
    meta = default_meta(job_root, job_id)
    title = title or meta.get("title", job_id)
    description = description or meta.get("description", "")
    captions_txt = ""
    if (jd / "captions.srt").exists():
        captions_txt = srt_to_text(jd / "captions.srt")
    links = "\n".join(f"- {u}" for u in meta.get("source_links", []) if u) or "- (no links recorded)"
    metadata_txt = (
        f"TITLE\n{title}\n\nDESCRIPTION\n{description}\n\n"
        f"CAPTIONS (plain text)\n{captions_txt}\n\nSOURCE LINKS\n{links}\n"
    )
    (jd / "manual_metadata.txt").write_text(metadata_txt, encoding="utf-8")
    bundle = {}
    for name, fname in (("video_mp4", "documentary.mp4"), ("thumbnail_jpg", "thumbnail.jpg"),
                        ("subtitles_srt", "captions.srt"), ("metadata_txt", "manual_metadata.txt")):
        p = jd / fname
        if p.exists():
            bundle[name] = str(p)
    if "video_mp4" not in bundle:
        raise FileNotFoundError("No rendered video for this job yet — run generation first.")
    return bundle
