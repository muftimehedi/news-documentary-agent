# News Documentary Deep Agent (সংবাদ তথ্যচিত্র এজেন্ট)

বাংলায় সহজ গাইড — কোডের নাম ইংরেজিতে।

## এটা কী করে?
সাম্প্রতিক খবর খুঁজে → যাচাই করে → বাংলা ন্যারেশন + দৃশ্য পরিকল্পনা লেখে → কণ্ঠস্বর + ছবি + সাবটাইটেল দিয়ে FFmpeg ভিডিও বানায় → আপনি দেখে approve করলে YouTube-এ আপলোড করে।

## দরকারি জিনিস
- Python 3.12, `uv`, FFmpeg (`brew install ffmpeg`), Mac Apple Silicon / Linux দুটোতেই চলে।

## চালানো (প্রথমবার)
```bash
cd news-documentary-agent
cp .env.example .env        # প্রয়োজনীয় key বসান
uv sync                     # নির্ভরতা ইনস্টল
uv run pytest -q            # টেস্ট
uv run newsdoc run --topic ""        # ফিক্সচার/লাইভ রান (approval-এ থামবে)
uv run newsdoc chat                 # Main Deep Agent-এর সঙ্গে সরাসরি চ্যাট (পরিকল্পনা/প্রতিনিধিত্ব)
uv run newsdoc approve <job_id>      # অনুমোদন
uv run newsdoc resume <job_id>       # থেমে থাকা কাজ আবার চালু
uv run streamlit run src/news_documentary/ui/app.py  # অপারেটর UI
```

## আসল (live) চালানোর চাবি
| কাজ | কী লাগবে |
|---|---|
| LLM (আসল গবেষণা/লেখা) | `.env`-এ `NEWS_MODEL=openai:gpt-4o-mini` + `OPENAI_API_KEY=...` (অথবা google/anthropic মডেল) |
| লাইভ সার্চ | `TAVILY_API_KEY=...` (না থাকলে বিনামূল্যের RSS ব্যবহার হয়) |
| আসল বাংলা কণ্ঠ | `TTS_PROVIDER=gtts` (gTTS বাংলা `bn` সমর্থন করে; যাচাইকৃত) |
| আসল YouTube আপলোড | `YOUTUBE_PUBLISH_MODE=real` + `YOUTUBE_CLIENT_SECRETS=client_secrets.json`, তারপর `uv run newsdoc auth-youtube` |

চাবি ছাড়া চললে **FIXTURE** লেখা থাকবে — এটা পরীক্ষার ভুয়া খবর/কণ্ঠ/রসিদ, আসল নয়।

## গুরুত্বপূর্ণ ধারণা (সহজ ভাষায়)
- **Main Agent বনাম subagent বনাম tool**: Main Agent পরিকল্পনা করে ও ভাগ করে দেয়; subagent (গবেষক, যাচাইকারী, লেখক…) ছোট নির্দিষ্ট কাজ করে; tool হলো নিশ্চিত যন্ত্র (ফাইল লেখা, FFmpeg চালানো) — যন্ত্র ভুল করে না, ভাবেও না।
- **LangChain বনাম LangGraph বনাম Deep Agents**: LangChain = মডেল ও tool-এর সংযোগ; LangGraph = ধাপে ধাপে কাজের মানচিত্র (থামা/আবার শুরু সহ); Deep Agents = LangChain/LangGraph-এর ওপর তৈরি প্রস্তুত এজেন্ট কাঠামো (পরিকল্পনা, subagent, ফাইল, স্মৃতি)। আমরা ভেতরের চাকা নতুন করে বানাইনি।
- **AGENTS.md বনাম checkpoint বনাম long-term store**: AGENTS.md = স্থায়ী নিয়মের খাতা; checkpoint = চলমান কাজের সাময়িক স্মৃতি (বন্ধ করে আবার শুরু); long-term store = পছন্দ, পুরোনো বিষয়, সম্পাদকীয় জ্ঞানের স্থায়ী ভান্ডার।

## YouTube সেটআপ (আসল আপলোড)
1. Google Cloud-এ প্রজেক্ট → YouTube Data API v3 চালু → OAuth client (Desktop) → `client_secrets.json` ডাউনলোড।
2. `.env`: `YOUTUBE_PUBLISH_MODE=real`, `YOUTUBE_CLIENT_SECRETS=/পথ/client_secrets.json`
3. `uv run newsdoc auth-youtube` → ব্রাউজারে অনুমতি → `data/youtube_token.json` তৈরি (গোপন, কমিট নয়)।
4. UI/CLI-তে approve → `unlisted` (ডিফল্ট) দিয়ে আপলোড; রসিদে ভিডিও ID/URL থাকবে।

## Facebook/Instagram
এখনো **অসমাপ্ত (milestone 5)** — Page অনুমতি/app review যাচাই না করে দাবি করা হয়নি। কোডে স্পষ্ট stub ত্রুটি দেখায়।

## ফাইল কোথায় থাকে?
- `data/jobs/<job_id>/` — গবেষণা, স্ক্রিপ্ট, অডিও, ভিডিও, রসিদ (প্রকাশিত প্রমাণ মুছবেন না)।
- `data/newsdoc.sqlite` — কাজ, প্রকাশনার intent (ডুপ্লিকেট রোধে UNIQUE), পছন্দ।
