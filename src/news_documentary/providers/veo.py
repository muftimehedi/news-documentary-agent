"""Video-generation adapter with Google Veo as the intended initial integration.

Verified Oct 2026 (ai.google.dev/gemini-api/docs/veo):
- Gemini API model ids: `veo-3.1-generate-preview` (default), `veo-3.1-fast-generate-preview`.
- Generates ~8s clips (720p/1080p, 16:9 or 9:16); NOT a full documentary in one call.
- Our pipeline generates per-scene clips and assembles with FFmpeg narration/captions.
- Requires GOOGLE_API_KEY or GEMINI_API_KEY + billing; SDK: `google-genai`.

Status contract (never silent):
- VEO_ENABLED=1 + key present -> attempt real generation (labeled synthetic).
- Otherwise -> raise UnconfiguredVeo with exact setup steps (caller falls back
  to stills ONLY when settings allow, and labels the manifest accordingly).
"""
from __future__ import annotations

import os
from pathlib import Path


class UnconfiguredVeo(RuntimeError):
    pass


def veo_model_id(settings=None) -> str:
    if settings is not None and getattr(settings, "veo_model", ""):
        return str(settings.veo_model)
    return os.environ.get("VEO_MODEL", "veo-3.1-generate-preview")


def veo_enabled(settings=None) -> bool:
    if settings is not None and getattr(settings, "video_provider", "stills") != "veo":
        if os.environ.get("VEO_ENABLED", "") != "1":
            return False
    if os.environ.get("VEO_ENABLED", "") == "0":
        return False
    has_key = bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
                   or (settings is not None and getattr(settings, "google_api_key", "")))
    want = (settings is not None and getattr(settings, "video_provider", "") == "veo") \
        or os.environ.get("VEO_ENABLED", "") == "1"
    return bool(want and has_key)


def _require_key(settings=None) -> str:
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") \
        or (getattr(settings, "google_api_key", "") if settings else "")
    if not key:
        raise UnconfiguredVeo(
            "Veo unconfigured: set VEO_ENABLED=1, VEO_MODEL=%s, and GOOGLE_API_KEY (or GEMINI_API_KEY) "
            "with billing enabled. See https://ai.google.dev/gemini-api/docs/veo. "
            "Falling back to stills only when video_provider=stills." % veo_model_id(settings)
        )
    return key


def generate_scene_clip(prompt: str, out_path: Path, aspect: str = "vertical",
                        settings=None) -> dict:
    """Generate one ~8s scene clip via Veo. Returns {path, model, synthetic}."""
    key = _require_key(settings)
    model = veo_model_id(settings)
    try:
        from google import genai  # type: ignore[import-not-found]
    except Exception as e:
        raise UnconfiguredVeo(
            f"Veo SDK missing (pip install google-genai): {e}. "
            "Set video_provider=stills for offline renders."
        ) from e
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    client = genai.Client(api_key=key)
    aspect_ratio = "9:16" if aspect == "vertical" else "16:9"
    operation = client.models.generate_videos(
        model=model, prompt=f"Documentary reconstruction (clearly synthetic, not real footage): {prompt}",
        config={"aspect_ratio": aspect_ratio} if hasattr(__import__("google.genai.types", fromlist=["x"]), "GenerateVideosConfig") else None,
    )
    # Poll until done (SDK long-running operation).
    result = operation.result() if hasattr(operation, "result") else operation
    videos = getattr(getattr(result, "response", result), "generated_videos", None) or getattr(result, "generated_videos", [])
    if not videos:
        raise RuntimeError(f"Veo returned no videos (model={model}).")
    video = videos[0].video if hasattr(videos[0], "video") else videos[0]
    if hasattr(video, "save"):
        video.save(str(out_path))
    elif hasattr(client.files, "download"):
        client.files.download(file=video, path=str(out_path))
    else:
        raise RuntimeError("Veo SDK: unknown video payload shape; cannot save clip.")
    return {"path": str(out_path), "model": model, "synthetic": True,
            "label": "GENERATED RECONSTRUCTION (Veo, synthetic — not authentic footage)"}
