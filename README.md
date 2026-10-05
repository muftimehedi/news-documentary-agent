# News Documentary Deep Agent

Researches recent news → verifies it → writes narration + scene plan → renders an FFmpeg video (voiceover + visuals + subtitles) → uploads to YouTube after your approval.

## Requirements
- Python 3.12, `uv`, FFmpeg (`brew install ffmpeg`). Runs on Apple Silicon Macs and Linux.

## Run it (first time)
```bash
cd news-documentary-agent
cp .env.example .env        # fill in keys
uv sync                     # install dependencies
uv run pytest -q            # tests
uv run newsdoc run --topic ""        # fixture/live run (pauses at approval)
uv run newsdoc chat                 # chat directly with the Main Deep Agent
uv run newsdoc approve <job_id>      # approve this video
uv run newsdoc resume <job_id>       # resume a paused job (publish + record)
uv run streamlit run src/news_documentary/ui/app.py  # operator UI
```

To make a documentary in English instead of Bengali:
```bash
NARRATION_LANG=en uv run newsdoc run --topic "global oil industry history"
```
(or set `NARRATION_LANG=en` permanently in `.env` / the Streamlit sidebar).

## Keys for live mode (verified working, Oct 2026)
| Job | What you need |
|---|---|
| LLM | `NEWS_MODEL=groq:openai/gpt-oss-120b` + `GROQ_API_KEY=...` (needs `langchain-groq`; other providers work via `provider:model` + their key) |
| Live search | `TAVILY_API_KEY=...` (falls back to free RSS without it) |
| Real voiceover | `TTS_PROVIDER=gtts` (gTTS supports Bengali `bn` and English; verified) |
| Real YouTube upload | `YOUTUBE_PUBLISH_MODE=real` + `YOUTUBE_CLIENT_SECRETS=client_secrets.json`, then `uv run newsdoc auth-youtube` |

Without keys it runs in **FIXTURE** mode — outputs are labeled as test data (sample news, synthetic beeps, fake receipts), never presented as live.

## Key concepts (plain English)
- **Main Agent vs subagent vs tool**: the Main Agent plans and delegates; subagents (researcher, fact-checker, writer…) do narrow jobs with typed JSON deliverables; tools are deterministic workers (file writes, FFmpeg) — they don't think, they execute.
- **LangChain vs LangGraph vs Deep Agents**: LangChain = model + tool integrations; LangGraph = the explicit stage workflow (pause/resume, checkpoints); Deep Agents = the ready-made agent harness on top (planning, subagents, filesystem, memory). We don't reimplement its internals.
- **AGENTS.md vs checkpointer vs long-term store**: AGENTS.md = durable rules; checkpointer = short-term job/thread state for resume; store = long-term preferences, topic history, editorial knowledge.

## YouTube setup (real uploads)
1. Google Cloud project → enable YouTube Data API v3 → OAuth client (Desktop) → download `client_secrets.json`.
2. `.env`: `YOUTUBE_PUBLISH_MODE=real`, `YOUTUBE_CLIENT_SECRETS=/path/client_secrets.json`
3. `uv run newsdoc auth-youtube` → approve in browser → `data/youtube_token.json` is created (secret, never committed).
4. Approve in UI/CLI → uploads as `unlisted` (default); the receipt carries the video ID/URL.

## Facebook/Instagram
Still **unfinished (milestone 5)** — no permissions/app review verified yet, so the code raises an explicit stub error instead of claiming support.

## Where files live
- `data/jobs/<job_id>/` — research, script, audio, video, receipts (never delete published evidence).
- `data/newsdoc.sqlite` — jobs, publication intents (UNIQUE key prevents duplicates), preferences.
