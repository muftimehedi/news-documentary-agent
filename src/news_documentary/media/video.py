"""Media helpers: captions (SRT, Bengali-capable), FFmpeg render, verification."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def write_srt(scenes: list[dict], total_s: float, out_path: Path) -> Path:
    out_path = Path(out_path)
    per = total_s / max(1, len(scenes))
    def ts(s: float) -> str:
        h, r = divmod(max(0, s), 3600); m, sec = divmod(r, 60)
        return f"{int(h):02d}:{int(m):02d}:{int(sec):02d},{int((sec % 1) * 1000):03d}"
    lines = []
    for i, sc in enumerate(scenes):
        lines += [str(i + 1), f"{ts(i * per)} --> {ts((i + 1) * per)}", sc.get("narration", "")[:160], ""]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def render_documentary(job_dir: Path, scenes: list[dict], audio_path: Path, size: tuple[int, int],
                       srt_path: Path, stills: list[Path]) -> dict:
    """FFmpeg still-image documentary. Argument-list subprocess (no model-generated shell)."""
    job_dir = Path(job_dir)
    w, h = size
    seg = job_dir / "segments.txt"
    outs = []
    # per-scene clip from still; duration from scene or equal split
    import json as _j
    audio_dur = _probe_duration(audio_path)
    per = audio_dur / max(1, len(scenes))
    for i, still in enumerate(stills):
        d = float(scenes[i].get("duration_s", 0) or per)
        seg_out = job_dir / f"seg_{i}.mp4"
        _run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(still),
              "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},format=yuv420p",
              "-t", f"{d:.2f}", "-r", "30", str(seg_out)])
        outs.append(seg_out)
    seg.write_text("\n".join(f"file '{Path(o).resolve()}'" for o in outs), encoding="utf-8")
    concat = job_dir / "video_nocap.mp4"
    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(seg),
          "-i", str(audio_path), "-c:v", "libx264", "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-shortest", str(concat)])
    final = job_dir / "documentary.mp4"
    # Prefer stream captions (mov_text: reliable, keeps Bengali shaping in players).
    # Burn-in via libass is attempted only when safe; any failure falls back to mov_text.
    font = _find_bengali_font()
    burned = False
    if font:
        try:
            esc = str(srt_path).replace(":", "\\:").replace("'", "")
            _run(["ffmpeg", "-y", "-v", "error", "-i", str(concat),
                  "-vf", f"subtitles='{esc}'",
                  "-c:a", "copy", str(final)])
            burned = True
        except RuntimeError:
            burned = False
    if not burned:
        if final.exists():
            final.unlink()
        _run(["ffmpeg", "-y", "-v", "error", "-i", str(concat), "-i", str(srt_path),
              "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text", str(final)])
        font = "mov_text-fallback"
    thumb = job_dir / "thumbnail.jpg"
    _run(["ffmpeg", "-y", "-v", "error", "-ss", "1", "-i", str(final),
          "-frames:v", "1", "-q:v", "3", str(thumb)])
    meta = {"video": str(final), "thumbnail": str(thumb), "duration_s": _probe_duration(final),
            "size": size, "font": font or "mov_text-fallback", "mode": "still-image-fixture" if _is_fixture(job_dir) else "still-image"}
    (job_dir / "render_meta.json").write_text(_j.dumps(meta, indent=2), encoding="utf-8")
    return meta


def _is_fixture(job_dir: Path) -> bool:
    try:
        r = json.loads((job_dir / "fact_report.json").read_text())
        return False
    except Exception:
        return True


def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(cmd[:6])}... :: {r.stderr[-800:]}")


def _probe_duration(p: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", str(p)],
                       capture_output=True, text=True, timeout=30)
    return float(r.stdout.strip())


def _find_bengali_font() -> str | None:
    import shutil

    if shutil.which("fc-list") is None:
        return None
    try:
        r = subprocess.run(["fc-list", ":lang=bn", "family"], capture_output=True, text=True, timeout=15)
        for line in r.stdout.splitlines():
            fam = line.split(",")[0].strip()
            if fam:
                return fam
    except Exception:
        pass
    return None


def verify_media(video: Path, srt: Path, audio: Path, size: tuple[int, int]) -> list[dict]:
    findings = []
    def add(area, checked, passed, detail=""):
        findings.append({"area": area, "checked": checked, "passed": passed, "detail": detail})

    if not Path(video).exists():
        add("output-exists", True, False, "documentary.mp4 missing"); return findings
    add("output-exists", True, True, str(video))
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height", "-of", "csv=p=0", str(video)],
                           capture_output=True, text=True, timeout=30)
        dims = r.stdout.strip()
        add("dimensions", True, dims == f"{size[0]},{size[1]}", f"got {dims}, want {size}")
    except Exception as e:
        add("dimensions", True, False, str(e))
    for label, stream in (("audio-presence", "a"), ("video-stream", "v")):
        try:
            r = subprocess.run(["ffprobe", "-v", "error", f"-select_streams", f"{stream}",
                                "-show_entries", "stream=index", "-of", "csv=p=0", str(video)],
                               capture_output=True, text=True, timeout=30)
            add(label, True, bool(r.stdout.strip()), r.stdout.strip() or "missing")
        except Exception as e:
            add(label, True, False, str(e))
    try:
        add("caption-timing", True, Path(srt).exists() and "-->" in Path(srt).read_text(encoding="utf-8"), "SRT cue markers present")
    except Exception as e:
        add("caption-timing", True, False, str(e))
    # representative frame layout: extract a frame and check it is non-black
    try:
        from PIL import Image

        frame = Path(video).parent / "_check_frame.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "2", "-i", str(video),
                        "-frames:v", "1", str(frame)], check=True, timeout=60)
        im = Image.open(frame).convert("L")
        hist = im.histogram()
        dark_ratio = sum(hist[:16]) / max(1, sum(hist))
        add("frame-layout", True, dark_ratio < 0.95, f"dark-pixel ratio {dark_ratio:.2f}")
    except Exception as e:
        add("frame-layout", False, False, f"could not check: {e}")
    return findings
