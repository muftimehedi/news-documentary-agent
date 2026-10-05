---
name: media-production
description: Prepare licensed assets, TTS, captions, render manifest; verify with FFmpeg.
version: 1.0.0
---
# Media production procedure
1. Use generated/owned stills only; record source/license/attribution; label synthetic.
2. TTS via configured adapter (gtts real voice / fixture labeled). Time from audio, not word count.
3. SRT captions + render_manifest.json; render with FFmpeg arg-lists; verify streams/duration/dims/audio/captions/frames.
