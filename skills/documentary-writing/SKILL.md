---
name: documentary-writing
description: Write original Bengali narration + scene plan grounded in verified claims.
version: 1.0.0
---
# Documentary writing procedure
1. Use only verified claims; link every factual sentence to claim IDs.
2. Hook (5s), context, 3-5 scenes, ending. Mark unknowns explicitly.
3. Output Script JSON {title, narration_full, scenes[{narration, claim_ids, visual, on_screen_text, duration_s}], version}.
