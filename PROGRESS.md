# ContextSense Project Progress

This document describes the **current state of the repo** for someone picking up the project fresh. It is based on reading the code under `backend/` and `frontend/`, plus a small set of checks run locally (pytest, import/compile). It does **not** treat “file exists” as “feature done.”

---

## 1. What Has Been Built

The project is a monorepo: a **Python backend** (FastAPI + LangGraph agents) and a **Next.js frontend** (still boilerplate). Most real logic lives in standalone Python scripts that can be run from the terminal.

### Ingestion pipeline

| File | What it does |
|------|--------------|
| `backend/ingestion/ingest.py` | CLI script: fetches ticker news from Alpha Vantage `NEWS_SENTIMENT` (last 7 days), tokenizes/chunks text with `all-MiniLM-L6-v2`, embeds chunks, and upserts them into the Qdrant `news_chunks` collection. Usage: `python backend/ingestion/ingest.py AAPL`. |

### Notion client (`backend/mcp_clients/`)

Despite the folder name, these are **direct Notion REST API** clients — not Model Context Protocol servers.

| File | What it does |
|------|--------------|
| `backend/mcp_clients/notion_mcp_client.py` | `NotionClient` class: parses `NOTION_DATABASE_ID` from a URL or raw ID, then POSTs a new page row with columns Name, Ticker, Date, Direction, Confidence, and Key Citation. |
| `backend/mcp_clients/test_notion.py` | CLI smoke test that appends a dummy `TEST` ticker row and prints the created page URL. |

### Agents (`backend/agents/`)

Each agent is importable as a library function and also has a `if __name__ == "__main__"` block for manual testing.

| File | What it does |
|------|--------------|
| `backend/agents/orchestrator.py` | Resolves a ticker from a direct symbol or natural-language query (DeepSeek JSON extraction, with a regex/keyword fallback), sets request priority, and returns a route (`ticker_analysis` or `invalid`). |
| `backend/agents/retriever.py` | LangGraph agent: vector-searches Qdrant for ticker news (top 8), cold-starts by subprocess-calling `ingest.py` if fewer than 3 chunks, extracts KG relations via DeepSeek, and fetches live quote data from Alpha Vantage `GLOBAL_QUOTE`. |
| `backend/agents/analyst.py` | Async agent: runs DeepSeek over news chunks concurrently to extract structured `Event` objects, with Pydantic validation retries and keyword-based mock fallback on API failure. |
| `backend/agents/predictor.py` | Fetches daily OHLCV from Alpha Vantage, computes technical features (momentum, RSI, volume change, MA cross) with Pandas, then calls DeepSeek with a chain-of-thought prompt to produce a `Prediction`; falls back to heuristic mock data on API/rate-limit errors. |
| `backend/agents/critic.py` | Runs a deterministic Python citation check (cited event IDs must resolve to known events/chunks), then calls Gemini with a reflexion-style critique prompt to produce a `CriticVerdict`; falls back to heuristic mock verdict if Gemini is unavailable. |

### Pipeline coordinator

| File | What it does |
|------|--------------|
| `backend/pipeline.py` | Top-level LangGraph workflow wiring **Orchestrator → Retriever → Analyst → Predictor → Critic**, with up to 2 Critic-rejection retries back to Predictor. Approved runs go to `log_to_notion`; rejected runs terminate at `end_rejected`. After every run (approved or rejected), builds a `RunLog` and attempts a Postgres insert via `persist_run_log()`. Runnable as `python backend/pipeline.py [TICKER or query]`. |

### Schemas (`backend/schemas/`)

| File | What it does |
|------|--------------|
| `backend/schemas/retrieved_chunk.py` | Pydantic model for a Qdrant news chunk (ticker, source, date, text, optional id/score). |
| `backend/schemas/event.py` | Pydantic model for an extracted market event (type, description, sentiment, confidence, source chunk IDs). |
| `backend/schemas/prediction.py` | Pydantic model for a price forecast (direction, confidence, horizon_days, reasoning_summary, cited_event_ids). |
| `backend/schemas/critic_verdict.py` | Pydantic model for Critic output (approved, flags, final_confidence, revision_notes). |
| `backend/schemas/run_log.py` | Pydantic model for persisting every pipeline run; includes `from_pipeline_state()` builder and `persist_run_log()` async Postgres writer (asyncpg). |
| `backend/schemas/__init__.py` | Re-exports the above schema classes. |
| `backend/schemas/migrations/001_create_run_logs.sql` | SQL migration to create the `run_logs` table and indexes. Must be applied manually before Postgres logging works. |

### Backend server & placeholders

| File | What it does |
|------|--------------|
| `backend/main.py` | Minimal FastAPI app with `/` and `/health` only — no agent or pipeline endpoints yet. |
| `backend/tests/test_main.py` | Two pytest tests asserting the root and health endpoints return 200. |
| `backend/api/.gitkeep` | Empty placeholder; no API routes implemented here yet. |

### Frontend

| Path | What it does |
|------|--------------|
| `frontend/` | Next.js 14 App Router project with Tailwind and one shadcn `Button` component. `src/app/page.tsx` is still the default create-next-app landing page — no ContextSense UI or backend integration. |

### Infrastructure

| File | What it does |
|------|--------------|
| `infra/docker-compose.yml` | Local Docker services for PostgreSQL (`contextsense` DB on port 5432) and Qdrant (ports 6333/6334). |

---

## 2. Verification Status

### Confirmed working (checked in this environment)

- **FastAPI smoke tests**: `backend/.venv/bin/python -m pytest backend/tests/` — 2 tests pass (`/` and `/health`).
- **Pipeline graph compiles**: `create_pipeline()` imports and builds without error.
- **RunLog model logic**: `RunLog.from_pipeline_state()` can be constructed from in-memory pipeline state objects (unit-level, no DB).

### Reported working during prior development (CLI harnesses exist; not re-run end-to-end for this doc)

These scripts have dedicated terminal entry points and were exercised during earlier development. They **do run real external API calls** when keys and services are configured, but several agents **silently fall back to mock/heuristic output** when DeepSeek returns billing errors or keys are missing (see Known Issues).

| Component | How to run | Caveat |
|-----------|------------|--------|
| News ingestion | `python backend/ingestion/ingest.py AAPL` | Requires Alpha Vantage + Qdrant reachable. |
| Notion write | `python backend/mcp_clients/test_notion.py` | Requires Notion integration token + database ID with matching column names. |
| Retriever agent | `python backend/agents/retriever.py AAPL` | KG extraction falls back to a stub relation on DeepSeek failure. |
| Analyst agent | `python backend/agents/analyst.py` | Chains Retriever → Analyst; may use mock events on DeepSeek 402/balance errors. |
| Predictor agent | `python backend/agents/predictor.py` | Chains Retriever → Analyst → Predictor; may use mock indicators/prediction on API limits. |
| Critic agent | `python backend/agents/critic.py` | Full Retriever → Analyst → Predictor → Critic chain; may use mock verdict without `GEMINI_API_KEY`. |
| Orchestrator | `python backend/agents/orchestrator.py` | Runs canned test inputs; LLM path depends on DeepSeek. |

### Exists as code but not verified end-to-end

| Component | Status |
|-----------|--------|
| **Full multi-agent pipeline** (`backend/pipeline.py`) | Graph is wired and compiles, but a complete run through Orchestrator → … → Notion/Postgres has **not been confirmed** in a fresh terminal session for this doc. |
| **Postgres run logging** | `persist_run_log()` and migration SQL exist; migration must be applied with `psql "$DATABASE_URL" -f backend/schemas/migrations/001_create_run_logs.sql`. Insert path not verified against a live database. |
| **Notion logging from pipeline** | `log_to_notion_node` only runs when Critic approves; not verified as part of a full pipeline run. |
| **FastAPI pipeline endpoints** | `backend/api/` is empty; no HTTP trigger for agent runs. |
| **Frontend** | Boilerplate only; no backend calls, no prediction UI. |
| **Outcome backfill** | `RunLog.actual_outcome` is always `NULL`; no job exists yet to fill it after `horizon_days`. |
| **Docker Compose infra** | Config exists; whether local containers are currently running depends on the developer's machine. |

---

## 3. Environment Setup

### Python virtual environment

| Item | Value |
|------|-------|
| Location | `backend/.venv/` |
| Activate | `source backend/.venv/bin/activate` |
| Python | `./backend/.venv/bin/python` (currently Python 3.13 in this workspace) |
| Install deps | From repo root: `cd backend && uv pip install -e .` (or equivalent pip install) |

Environment variables are loaded from a `.env` file at the **workspace root** (most scripts walk up to find it). Copy `.env.example` to `.env` and fill in real values.

### Required environment variables

| Variable | Used by |
|----------|---------|
| `ALPHA_VANTAGE_API_KEY` | Ingestion, Retriever live quotes, Predictor technical features |
| `QDRANT_URL` | Ingestion, Retriever vector search (defaults to `http://localhost:6333` if unset) |
| `DEEPSEEK_API_KEY` | Orchestrator, Retriever KG extraction, Analyst, Predictor |
| `GEMINI_API_KEY` | Critic agent (falls back to mock without it) |
| `NOTION_API_KEY` | Notion client / pipeline Notion logging |
| `NOTION_DATABASE_ID` | Notion client (URL or 32-char hex ID) |
| `DATABASE_URL` | Postgres run logging (`postgresql://…` connection string) |

### Optional environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI-compatible DeepSeek endpoint |
| `DEEPSEEK_MODEL` | `deepseek-chat` | Model name for Orchestrator ticker extraction |
| `HF_TOKEN` | — | Suppresses Hugging Face Hub warnings during embedding model download |

### External services

| Service | Role |
|---------|------|
| **Qdrant** | Vector store for embedded news chunks (`news_chunks` collection). Local via Docker Compose or Qdrant Cloud. |
| **PostgreSQL** | Stores pipeline run logs in `run_logs` (Supabase or local Docker). |
| **Alpha Vantage** | News sentiment feed, global quotes, daily time series. Free tier is rate-limited (25 calls/day). |
| **DeepSeek API** | LLM for orchestration, KG extraction, event extraction, and prediction reasoning. |
| **Google Gemini API** | LLM for Critic self-critique/reflexion. |
| **Notion API** | Human-readable prediction log for approved forecasts. |

### Running common commands

```bash
# Start local databases (optional if using cloud Qdrant/Postgres)
docker compose -f infra/docker-compose.yml up -d

# Ingest news for a ticker
backend/.venv/bin/python backend/ingestion/ingest.py AAPL

# Run the full agent pipeline
backend/.venv/bin/python backend/pipeline.py AAPL

# Start the API (health checks only today)
cd backend && uv run uvicorn backend.main:app --reload

# Frontend dev server (boilerplate page)
cd frontend && npm install && npm run dev
```

---

## 4. Known Issues & Unresolved Items

- **DeepSeek billing / balance errors**: Analyst, Predictor, and Retriever KG extraction catch `402` / “Insufficient Balance” and fall back to mock/heuristic output. Runs may appear to succeed while not using real LLM reasoning.
- **Mock fallbacks mask failures**: Analyst, Predictor, and Critic all have keyword-based or rule-based mock paths when API keys are missing or calls fail. Terminal output may not make it obvious which path ran.
- **Alpha Vantage rate limits**: Predictor caches daily time series, but repeated runs can still hit free-tier limits; technical features then fall back to mock values.
- **Postgres migration not automated**: The `run_logs` table is defined in SQL but nothing in the app creates it at startup. Logging fails silently (warning printed) if the table is missing or `DATABASE_URL` is unset.
- **`actual_outcome` never populated**: The field exists for future backtesting but no outcome-tracking job has been built.
- **Retriever KG relations unused downstream**: KG relations are extracted but the Analyst/Predictor/Critic pipeline works from raw chunks and events, not the KG output.
- **Notion folder naming**: `mcp_clients/` contains a plain REST client, not an MCP server implementation.
- **`.env.example` contains example credentials**: Treat as a template only; rotate any keys that were committed or shared.

---

## 5. Next Steps

Ordered by what the architecture still needs, based on what is **not built or not verified** yet:

1. **Verify the full pipeline end-to-end** — Run `backend/pipeline.py AAPL` with valid API keys, apply the `run_logs` migration, and confirm both Notion (on approval) and Postgres (always) receive rows.
2. **Expose pipeline via FastAPI** — Add routes under `backend/api/` (e.g. `POST /analyze`) that call `async_run_pipeline()` and return prediction + verdict JSON.
3. **Build the frontend** — Replace the Next.js boilerplate with views to submit a ticker/query, show prediction direction/confidence/reasoning, Critic flags, and approval status.
4. **Outcome backfill job** — After `horizon_days`, compare predicted direction to actual price movement and write `actual_outcome` on matching `run_logs` rows (enables Critic calibration analysis).
5. **Reduce silent mock fallbacks** — Make API/billing failures loud (fail the run or surface a clear “degraded mode” flag) so logged runs accurately reflect LLM vs heuristic paths.
6. **Integration tests** — Beyond the two health-check tests, add tests for schema builders, citation validation, and pipeline routing logic (mocking external APIs).

---

*Last updated: July 5, 2026 — reflects repo state including `run_log` Postgres logging and the wired multi-agent `pipeline.py`.*
