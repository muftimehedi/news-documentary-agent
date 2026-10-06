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

To make a documentary in Bengali instead of English:
```bash
NARRATION_LANG=bn uv run newsdoc run --topic "..."
```
(or set `NARRATION_LANG=bn` permanently in `.env` / the Streamlit sidebar).

## Keys for live mode (verified working, Oct 2026)
| Job | What you need |
|---|---|
| LLM | `NEWS_MODEL=groq:openai/gpt-oss-120b` + `GROQ_API_KEY=...` (needs `langchain-groq`; other providers work via `provider:model` + their key) |
| Live search | `TAVILY_API_KEY=...` (falls back to free RSS without it) |
| Real voiceover | `TTS_PROVIDER=gtts` (gTTS: English + Bengali `bn`; verified) |
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

---

# বাংলা নির্দেশিকা (নতুন: অ্যাকাউন্ট সংযোগ ও পাবলিশিং)

## কী বদলেছে (সংক্ষেপে)
- **অ্যাকাউন্ট ছাড়াই** ডকুমেন্টারি বানানো, দেখা ও ডাউনলোড করা যায় (Generate পাতা)।
- **দুইভাবে পাবলিশ**: (১) Manual — MP4, থাম্বনেইল, সাবটাইটেল ও তথ্য-ফাইল ডাউনলোড করে নিজে আপলোড; (২) Connected — অ্যাকাউন্ট যুক্ত করে অ্যাপ থেকেই পাবলিশ।
- **Connected Accounts পাতা**: YouTube, Facebook, Hikmah, X — একাধিক অ্যাকাউন্ট যুক্ত/বিচ্ছিন্ন করা যায়।
- **নিরাপত্তা**: টোকেন শুধু সার্ভারের `data/tokens/` ফাইলে (0600 অনুমতি) থাকে; লগ, ব্রাউজার, LLM বা git-এ কখনো যায় না। প্রতিটি সংযোগের মালিক (owner) থাকে; অন্যের অ্যাকাউন্ট ব্যবহার করা যায় না।
- **অ্যাকাউন্ট যুক্ত করলেই পাবলিশ হয় না** — পাবলিশে দুটি স্পষ্ট ক্লিক লাগে: "Review & authorize" (ভিডিও+তথ্য+গন্তব্য স্থির) তারপর "Publish"। ভিডিও বা তথ্য বদলালে আবার রিভিউ লাগবে।
- একটি প্ল্যাটফর্ম ব্যর্থ হলেও অন্যটির সফল ফলাফল মুছে না; ব্যর্থ গন্তব্য শুধু সেটাই আবার চেষ্টা করা যায়।

## চালানো (ধাপে ধাপে)
```bash
cd news-documentary-agent
cp .env.example .env
uv sync
uv run pytest -q
uv run streamlit run src/news_documentary/ui/app.py
```
1. **Generate** পাতা: বিষয় লিখে Run → ভিডিও তৈরি (approval-এ থামবে)।
2. **Review & Publish** পাতা: ভিডিও দেখুন, শিরোনাম/বিবরণ ঠিক করুন → Manual হলে ফাইলগুলো ডাউনলোড করুন; Connected হলে অ্যাকাউন্ট টিক দিন, visibility বেছে "Review & authorize" → "Publish" চাপুন।
3. **Connected Accounts** পাতা: নিচের ছক অনুযায়ী প্রতিটি প্ল্যাটফর্ম যুক্ত করুন।

## প্ল্যাটফর্মভেদে যা লাগবে (যাচাইকৃত, অক্টোবর ২০২৬)
| প্ল্যাটফর্ম | অবস্থা | যা লাগবে |
|---|---|---|
| YouTube | ✅ সম্পূর্ণ (real API) | Google Cloud → YouTube Data API v3 → OAuth Desktop client → `uv run newsdoc auth-youtube --account <নাম>` (scope: `youtube.upload`) |
| Facebook | ✅ কোড সম্পূর্ণ, ⚠️ অ্যাপ রিভিউ বাকি | Meta app + Facebook Login অনুমতি (`pages_show_list`, `pages_read_engagement`, `pages_manage_posts`) → User token → `GET /me/accounts` → **Page access token** (শুধু Page, CREATE_CONTENT task; প্রোফাইলে API দিয়ে ভিডিও যায় না; public ব্যবহারে Meta app review লাগে) |
| X | ✅ কোড সম্পূর্ণ, ⚠️ টোকেন হাতে আনতে হবে | X developer app → OAuth 2.0 user token (scope: `tweet.write`, `media.write`) → পেস্ট করে Verify। নোট: X মিডিয়া-আপলোড প্রতি অনুরোধে ~$0.010 চার্জ করতে পারে; ≤20 মিনিট ভিডিও Premium ছাড়াই যায় |
| Hikmah | ✅ কোড সম্পূর্ণ, ⚠️ OAuth নেই (সোর্সে যাচাইকৃত) | Hikmah-এর কোনো public OAuth নেই (hikmah-web সোর্সে `getAuthUrl` = "no OAuth needed")। base URL (যেমন `https://hikmah.net`) + Sanctum personal API token পেস্ট করুন (টোকেন Hikmah অ্যাকাউন্ট/সার্ভার-অ্যাডমিনের কাছ থেকে নিন)। আপলোড: `POST /api/posts`, `type=video`, সর্বোচ্চ ১ ভিডিও/100MB, কনটেন্ট ≤20000 অক্ষর |

## আটকে থাকা (blocked) বিষয় — স্পষ্ট ঘোষণা
- Facebook/X-এ ইন-অ্যাপ OAuth redirect লগইন নেই — Meta/X app + redirect URL সেটআপ ব্যবহারকারীর করতে হবে; তাই আপাতত token-paste সংযোগ (সার্ভারে সংরক্ষিত)।
- Hikmah-এ OAuth কখনো ছিল না — token-paste-ই একমাত্র পথ; টোকেন ইস্যু সার্ভার-পক্ষে হয়।
- Facebook/Instagram ব্যক্তিগত প্রোফাইলে API পাবলিশিং সমর্থিত নয় (শুধু Page)।
- কোনো "সফল" দাবি প্ল্যাটফর্মের নিশ্চিতকরণ (ID/URL) ছাড়া দেখানো হয় না; fixture/অসংযুক্ত/অসমর্থিত অবস্থা UI-তে লেবেল থাকে।

