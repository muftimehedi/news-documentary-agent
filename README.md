# News Research Agent — PDF reports + social posts

Researches a topic → fact-checks it → writes a **research PDF report** and/or **platform-specific social media posts**. Explicit user review gates everything before download or connected publishing.

Two interfaces share one backend: **terminal CLI** and **browser UI** (React). A terminal-created shared job appears in the browser and vice versa.

> Scope note (Oct 2026): video documentary generation (FFmpeg/TTS/Veo/video preview/video publishing) is **disabled** in active workflows. The video code, routes, adapters, tests, and the `VideoPreviewPlayer` component are **preserved untouched for future use** — report/social jobs never import them and need no video dependencies or credentials. Old video jobs and artifacts remain viewable/downloadable.

## Requirements

- Python 3.12, `uv`, Node.js 20+.
- No FFmpeg / TTS / video keys needed for report/social workflows.
- Tested versions (Oct 2026): `deepagents==0.7.22`, `langgraph==1.2.13`, `langchain==1.4.3`, `fpdf2==2.8.9`, `pypdf==6.19.0`, `express@5.2.1`, `react@19`, `vite@7`.
- Lockfiles committed: `uv.lock`, `apps/api/package-lock.json`, `apps/web/package-lock.json`.

## Run it (shared mode: browser + terminal on the same jobs)

```bash
cd news-documentary-agent
cp .env.example .env        # fill in JWT_SECRET, WORKER_SERVICE_TOKEN, ACCOUNTS_ENCRYPTION_KEY; use ABSOLUTE JOB_ROOT/DB_PATH
uv sync

# 1) Backend API (owns auth, jobs, chat, accounts, text publishing)
cd apps/api && npm install && npm run dev      # :4000 (or API_PORT)

# 2) Python worker (owns Researcher/Fact-checker/Writer/Reviewer + doc workflow)
cd ../.. && uv run newsdoc-worker               # polls the API queue

# 3) Browser UI (React)
cd apps/web && npm install && npm run dev      # :5173

# 4) Terminal on the same jobs
uv run newsdoc api-register --email you@example.com --password 'min-8-chars'
uv run newsdoc api-login --email you@example.com --password 'min-8-chars'
uv run newsdoc api-chat --thread chat-1
uv run newsdoc api-create --topic "Dhaka metro rail fares" --job-type report --lang en
uv run newsdoc api-create --topic "Padma Bridge anniversary" --job-type social --platforms x,facebook,hikmah
uv run newsdoc api-list
uv run newsdoc api-follow <job_id>
uv run newsdoc api-download <job_id> report.pdf
uv run newsdoc api-texts <job_id>
uv run newsdoc api-revise <job_id> --note "shorter summary, focus on fares"
# explicit two-step text publish (mirrors browser):
uv run newsdoc api-social-review <job_id> --accounts <account_id>
uv run newsdoc api-social-review <job_id> --accounts <account_id> --publish  # asks for PUBLISH
```

## Run it (local standalone mode, preserved)

Local commands work without the API/DB server. Local jobs do **not** automatically appear in the browser.

```bash
uv run newsdoc run-doc --topic "..." --job-type report   # local PDF + posts
uv run newsdoc run-doc --topic "..." --job-type social --lang bn
uv run newsdoc chat                  # chat directly with the Main Deep Agent (slim, token-safe)
```

Legacy video commands (`run`, `approve`, `resume`, `api-review`, …) are preserved but the video workflow is disabled in the active scope.

To write in Bengali instead of English: `--lang bn` (or `NARRATION_LANG=bn`). Bengali **PDF** additionally needs a Unicode font: `DOC_FONT_TTF=/path/NotoSansBengali-Regular.ttf` — without it the run fails loudly instead of rendering mojibake.

## Tests

```bash
uv run --extra dev python -m pytest -q   # 26 tests: doc e2e, social limits/binding, legacy video preserved, shared interop
cd apps/api && npx tsc -p tsconfig.json --noEmit
cd ../web && npx tsc --noEmit && npm run build
```

## Keys for live mode (verified working, Oct 2026)

| Job | What you need |
|---|---|
| LLM | `NEWS_MODEL=groq:openai/gpt-oss-120b` + `GROQ_API_KEY=...` (other providers work via `provider:model` + their key) |
| Live search | `TAVILY_API_KEY=...` (falls back to free RSS without it) |
| Bengali PDF | `DOC_FONT_TTF=/path/*.ttf` with Bengali glyphs |
| Shared backend | `JWT_SECRET`, `WORKER_SERVICE_TOKEN`, `ACCOUNTS_ENCRYPTION_KEY` (all required) |
| Postgres (deploy) | `DATABASE_URL=postgres://...` (sqlite fallback when unset; Postgres code-complete, live-server unverified) |

Without keys it runs in **FIXTURE** mode — outputs are labeled as test data, never presented as live. **No paid video or audio API is ever called** in this scope (no TTS/Veo/FFmpeg code paths).

## Key concepts (plain English)

- **Writer vs Reviewer vs tools**: the Writer drafts the report + per-platform posts from verified claims only; the Reviewer checks factual consistency, platform limits, and the rendered PDF; deterministic code (PDF render, text posting) executes — it doesn't think.
- **Contracts v2** (`packages/contracts/v2.json`, `v2.ts`, `contracts_py.py`): `job_type` report|social, doc stages (discover→research→fact_check→write→review→approval→publish), post shapes with `connect_post` flags. v1 (video) stays valid for preserved history.
- **Express vs Python worker**: Express owns auth, jobs, chat API, accounts, text publishing, progress streaming. The Python worker owns agent execution, checkpoints, PDF files. Queue payloads carry job IDs + artifact references, never blobs.
- **Revisions**: `api-revise` stores your note, deletes stale approvals, and requeues — the worker **reuses research + fact-check** and reruns only write → review.

## Integration status (honest labels)

| Integration | Status | Notes |
|---|---|---|
| Facebook text posts | ✅ real code, ⚠️ token needed | `POST /{page-id}/feed` with message; Pages only (`pages_manage_posts`), Meta app review for public use |
| X text posts | ✅ real code, ⚠️ token needed | `POST /2/tweets` text-only; ≤280 chars enforced before sending |
| Hikmah text posts | ✅ real code, ⚠️ live-unverified | `POST /api/posts` `type=text` mirrors the verified video-post shape; no OAuth (token paste, as before) |
| YouTube text | ❌ disabled with reason | YouTube Data API v3 has **no** text/community-post endpoint (upload + comments only). Title/description are still generated for manual use; connected posting is refused, never faked |
| Fixture adapter | 🧪 labeled test double | `succeeded-fixture` receipts, never real posts |
| Bengali PDF | ✅ code, ⚠️ font needed | Fails loudly without `DOC_FONT_TTF` |
| Postgres / S3 | ✅ boundaries, ⚠️ live-unverified | sqlite/local-disk tested |

## Publishing rules (both interfaces enforce the same)

1. Connecting an account never publishes.
2. Two explicit steps: **Review & authorize** (binds content hash + destinations) then **Publish**. Any edit needs a new review.
3. Per-destination results; failures never erase successes; retry runs failed ones only; duplicates skipped via logical keys; ambiguous timeouts need operator resolution, never blind retry.
4. The agent prepares text but cannot approve publishing. No auto-publishing or schedules.

## Browser UI pages

- **Main Agent chat** — threads shared with `api-chat`; report/social requests queue jobs.
- **New output** — report vs social, language, platforms. No video options.
- **Job history** — all your jobs incl. legacy video rows; type shown per job.
- **Job detail** — readable events (Research started … Review ready), research/source viewer, report + posts viewer, **PDF preview** (iframe of the exact bytes offered for download, sha256 badge), social editor (edit/copy/download .txt per platform), revision-with-note, Review & Publish for social, legacy video preview kept for old jobs.
- **Connected accounts** — connect/inspect/disconnect; tokens encrypted server-side.

## Where files live

- `data/jobs/<job_id>/` — `report.pdf`, `report.md`, `posts.json`, `social_meta.json` (your edits), `social_review.json`, research, fact report, review (never delete published evidence). Legacy video files sit alongside for old jobs.
- `data/newsdoc.sqlite` — application records (Express-owned migrations `001`, `002_job_type`); `*.checkpoints.sqlite` — LangGraph short-term state.
- `packages/contracts/` — v2 active, v1 preserved. `skills/report-writing`, `skills/social-posts` — active procedures.

## Sample verification (Oct 2026, live runs)

- **Report** (`Dhaka metro rail fares`, live Tavily/RSS): 16 verified claims; review passed; `report.pdf` verified **8/8** (exists, 3 pages, A4 595.3×842, all pages extractable text, title + Sources heading, 9 embedded URLs, 877 words). Revision with note re-ran write→review reusing research and embedded the focus note.
- **Social** (`Padma Bridge anniversary`): x 228/280, facebook 416/2000, hikmah 1133/20000 chars; YouTube `connect_post=false`. Terminal review→`PUBLISH`→fixture receipt (`succeeded-fixture`).
- **Known data-quality caveat**: live RSS snippets can carry viral noise (birthday wishes/saree ads matched the query); the corroboration rule still required 2+ publishers, and everything stayed traceable to sources — but noisy queries yield noisy drafts. Prefer specific topics; review findings state what was (and wasn't) checked.

---

# বাংলা নির্দেশিকা (PDF রিপোর্ট + সোশ্যাল পোস্ট)

## সংক্ষেপে কী আছে
- **দুই ধরনের আউটপুট**: (১) গবেষণাভিত্তিক **PDF রিপোর্ট** (সুন্দর ফরম্যাট, উৎস-লিংকসহ, ব্রাউজারে প্রিভিউ, ডাউনলোড, সংশোধন); (২) প্ল্যাটফর্মভিত্তিক **সোশ্যাল পোস্ট** (X/Facebook/Hikmah + YouTube-এর জন্য হাতে-ব্যবহারের কপি) — এডিট, কপি, ডাউনলোড করা যায়।
- **ভিডিও বানানো বন্ধ**: FFmpeg/TTS/Veo/ভিডিও-প্রিভিউ/ভিডিও-পাবলিশ সক্রিয় নয়; পুরনো ভিডিও কোড ভবিষ্যতের জন্য সংরক্ষিত, পুরনো জব/ফাইল দেখা ও ডাউনলোড করা যায়।
- **টার্মিনাল ও ব্রাউজার একই জব দেখে**: `api-create --job-type report|social` দিয়ে বানানো জব ব্রাউজারের Job history-তে আসে; উল্টোটাও সত্যি।
- **নিরাপত্তা**: টোকেন শুধু সার্ভারে এনক্রিপ্ট করা থাকে; প্রতিটি জব/অ্যাকাউন্টের মালিক থাকে।
- **অ্যাকাউন্ট যুক্ত করলেই পোস্ট হয় না** — "Review & authorize" তারপর "Publish" — দুটি স্পষ্ট ধাপ। লেখা বদলালে আবার রিভিউ লাগবে।
- **YouTube-এ সংযুক্ত পোস্টিং বন্ধ**: YouTube-এর টেক্সট-পোস্ট API নেই — তাই শুধু হাতে ব্যবহারের শিরোনাম/বিবরণ দেওয়া হয়, কারণসহ।

## চালানো (ধাপে ধাপে)
```bash
cd news-documentary-agent
cp .env.example .env     # JWT_SECRET, WORKER_SERVICE_TOKEN, ACCOUNTS_ENCRYPTION_KEY বসান (ABSOLUTE path-এ JOB_ROOT/DB_PATH)
uv sync
# টার্মিনাল ১: ব্যাকএন্ড
cd apps/api && npm install && npm run dev
# টার্মিনাল ২: ওয়ার্কার (গবেষণা+লেখা)
cd ../.. && uv run newsdoc-worker
# টার্মিনাল ৩: ব্রাউজার UI
cd apps/web && npm install && npm run dev
# টার্মিনাল ৪: শেয়ার্ড CLI
uv run newsdoc api-register --email আপনি@মেইল.com --password 'কমপক্ষে-৮-অক্ষর'
uv run newsdoc api-create --topic "পদ্মা সেতু" --job-type report --lang bn
uv run newsdoc api-create --topic "পদ্মা সেতু" --job-type social
uv run newsdoc api-follow <job_id>
uv run newsdoc api-download <job_id> report.pdf
uv run newsdoc api-revise <job_id> --note "সংক্ষিপ্ত সারাংশ চাই"
```

## প্ল্যাটফর্মভেদে পোস্ট (যাচাইকৃত নিয়ম, অক্টোবর ২০২৬)
| প্ল্যাটফর্ম | অবস্থা | যা লাগবে |
|---|---|---|
| Facebook | ✅ কোড সম্পূর্ণ, ⚠️ টোকেন বাকি | Page access token → `POST /{page-id}/feed` (শুধু Page; সর্বোচ্চ ২০০০ অক্ষর) |
| X | ✅ কোড সম্পূর্ণ, ⚠️ টোকেন বাকি | user token (`tweet.write`) → `POST /2/tweets` (সর্বোচ্চ ২৮০ অক্ষর) |
| Hikmah | ✅ কোড সম্পূর্ণ, ⚠️ লাইভ-যাচাই বাকি | base URL + token → `POST /api/posts` `type=text` |
| YouTube | ❌ সংযুক্ত পোস্টিং বন্ধ | টেক্সট-পোস্ট API নেই; শিরোনাম/বিবরণ ডাউনলোড করে হাতে দিন |
| বাংলা PDF | ✅ কোড সম্পূর্ণ, ⚠️ ফন্ট বাকি | `DOC_FONT_TTF` (যেমন NotoSansBengali) না থাকলে স্পষ্ট ত্রুটি |

## আটকে থাকা বিষয় — স্পষ্ট ঘোষণা
- Facebook/X-এ ইন-অ্যাপ OAuth redirect নেই — token-paste সংযোগ।
- Hikmah-এ OAuth কখনো ছিল না — token-paste-ই একমাত্র পথ।
- Postgres/S3 কোড সম্পূর্ণ কিন্তু লাইভ সার্ভারে যাচাই হয়নি।
- কোনো "সফল" দাবি প্ল্যাটফর্মের নিশ্চিতকরণ (ID/URL) ছাড়া দেখানো হয় না; fixture অবস্থা লেবেল থাকে।
