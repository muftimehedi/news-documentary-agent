"""TTS adapters. Fixture = offline beeps (labeled). gTTS = real Bengali-capable voice."""
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from typing import Protocol


class TtsAdapter(Protocol):
    name: str
    def synthesize(self, text: str, lang: str, out_path: Path) -> dict: ...


class FixtureTtsAdapter:
    """Offline fixture: deterministic tone whose duration scales with text length.
    Output is clearly labeled FIXTURE (not a real voice)."""

    name = "fixture"

    def synthesize(self, text: str, lang: str, out_path: Path) -> dict:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # ~12 chars/sec Bengali estimate, clamp 10..85s
        dur = max(10.0, min(85.0, len(text) / 12.0))
        sr = 22050
        n = int(sr * dur)
        with wave.open(str(out_path), "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            buf = bytearray()
            for i in range(n):
                t = i / sr
                # gentle two-tone so scenes are audible but obviously synthetic
                f = 440.0 if (i // (sr * 2)) % 2 == 0 else 330.0
                v = int(9000 * math.sin(2 * math.pi * f * t) * math.exp(-0.0001 * i))
                buf += struct.pack("<h", v)
            w.writeframes(bytes(buf))
        return {"path": str(out_path), "duration_s": round(dur, 2), "fixture": True, "lang": lang}


class GttsAdapter:
    """Real TTS via gTTS. Verified: gTTS supports Bengali lang code 'bn'."""

    name = "gtts"

    def synthesize(self, text: str, lang: str, out_path: Path) -> dict:
        from gtts import gTTS

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        code = "bn" if lang in ("bn", "bangla", "bengali") else "en"
        tts = gTTS(text=text, lang=code)
        mp3 = out_path.with_suffix(".mp3")
        tts.save(str(mp3))
        # probe duration via ffprobe
        import subprocess

        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(mp3)],
                capture_output=True, text=True, timeout=30,
            )
            dur = float(r.stdout.strip())
        except Exception:
            dur = max(10.0, len(text) / 12.0)
        # convert to wav for uniform downstream handling
        wav = out_path.with_suffix(".wav")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mp3), str(wav)], check=False, timeout=120)
        return {"path": str(wav if wav.exists() else mp3), "duration_s": round(dur, 2), "fixture": False, "lang": code}


def get_tts_adapter(name: str) -> TtsAdapter:
    return GttsAdapter() if name == "gtts" else FixtureTtsAdapter()
