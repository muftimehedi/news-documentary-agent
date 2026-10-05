"""Licensed-safe media assets: generate original placeholder stills (PIL).
Never hotlink news footage; every asset records source/license/attribution."""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw


def make_still(out_path: Path, title: str, size: tuple[int, int], index: int = 0) -> dict:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    palette = [(30, 60, 120), (120, 40, 40), (30, 110, 80), (90, 70, 140), (140, 100, 30)]
    bg = palette[index % len(palette)]
    img = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(img)
    # simple banner + label (original generated illustration, not news footage)
    d.rectangle([0, size[1] - 220, size[0], size[1]], fill=(0, 0, 0))
    d.text((60, size[1] - 180), f"Scene {index + 1}", fill=(255, 210, 80))
    d.text((60, size[1] - 120), title[:60], fill=(255, 255, 255))
    d.text((60, 60), "GENERATED ILLUSTRATION", fill=(255, 255, 255))
    img.save(out_path, "PNG")
    return {
        "path": str(out_path),
        "source": "generated",
        "license": "original-generated",
        "attribution": "Generated placeholder by news-documentary-agent",
        "usage": "free to use in this documentary",
        "synthetic": True,
    }
