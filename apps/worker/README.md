# apps/worker — Python Deep Agent worker (implementation lives in `src/news_documentary/`)

The worker is the Python Deep Agent implementation; this directory holds the
run documentation so the suggested `apps/worker/` location exists without
moving the preserved `src/news_documentary/` package.

## What runs here

- `src/news_documentary/service_worker.py` — shared-mode bridge: polls the
  Express queue (`POST /api/jobs/internal/next` with `WORKER_SERVICE_TOKEN`),
  executes the outer LangGraph workflow + Main Deep Agent (`create_deep_agent`),
  posts readable progress events and artifact references.
- `src/news_documentary/workflow/graph.py` — outer production workflow
  (discover → research → fact_check → script → prepare_media → render →
  review → approval → publish → record_result) with durable checkpoints.
- `src/news_documentary/agents/` — Main Deep Agent + 5 specialist subagents.
- `src/news_documentary/cli.py` — local CLI (standalone) + `api-*` shared CLI.

## Run

```bash
# shared mode (same jobs as the browser)
uv sync
export API_BASE_URL=http://localhost:4000 WORKER_SERVICE_TOKEN=...
uv run newsdoc-worker            # poll forever
uv run newsdoc-worker --once     # claim + run a single job, then exit
```
