# ContextSense

**A multi-agent, retrieval-augmented financial news intelligence system.**

ContextSense ingests live stock news, extracts structured events, combines them with technical price indicators, and produces directional predictions — verified by a dedicated Critic agent that checks every citation before anything is approved.

> Built as a hands-on exploration of multi-agent RAG architecture: retrieval grounding, structured intermediate reasoning, and adversarial self-verification, rather than a single end-to-end prompt.

---

## Why this exists

Most "AI stock prediction" projects fall into one of two weak patterns: pure technical/ML models that ignore news context entirely, or LLM chatbots that summarize sentiment with no grounding and no way to catch a confidently-stated but unsupported claim. ContextSense combines both signal types and adds a verification layer specifically designed to catch the failure mode RAG systems are known for — a plausible-sounding claim that doesn't actually trace back to real evidence.

---

## Architecture

```
                         USER QUERY / ON-DEMAND TRIGGER
                                     │
                                     ▼
                       ┌─────────────────────────┐
                       │      ORCHESTRATOR        │  resolves ticker from
                       │  (DeepSeek V4 Flash)      │  natural language query
                       └────────────┬─────────────┘
                                     ▼
                       ┌─────────────────────────┐
                       │       RETRIEVER           │  Qdrant vector search,
                       │  (DeepSeek + Qdrant +      │  payload-filtered by
                       │   Alpha Vantage)           │  ticker; cold-start
                       └────────────┬─────────────┘  ingestion fallback
                                     ▼
                       ┌─────────────────────────┐
                       │        ANALYST            │  few-shot structured
                       │  (DeepSeek V4 Flash)       │  event extraction
                       └────────────┬─────────────┘
                                     ▼
                       ┌─────────────────────────┐
                       │       PREDICTOR             │◄────────────┐
                       │  events + technical          │            │ revision
                       │  indicators → CoT reasoning   │            │ (max 2
                       └────────────┬─────────────┘              │  attempts)
                                     ▼                              │
                       ┌─────────────────────────┐                │
                       │         CRITIC             │───rejected───┘
                       │  (Gemini Flash)             │
                       │  1. deterministic citation  │
                       │     check (no LLM)          │
                       │  2. LLM reflexion critique   │
                       └────────────┬─────────────┘
                                     │ approved
                                     ▼
                       ┌─────────────────────────┐
                       │   POSTGRES (all runs) +    │
                       │   NOTION (approved only)    │
                       └─────────────────────────┘
```

## Tech stack

| Layer | Choice |
|---|---|
| Agent orchestration | LangGraph |
| Reasoning LLM (Orchestrator, Retriever, Analyst, Predictor) | DeepSeek V4 Flash |
| Verification LLM (Critic) | Gemini (Flash-class) — deliberately a separate model family to avoid correlated blind spots |
| Vector database | Qdrant (payload-filtered by ticker) |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` (local, 384-dim) |
| News + market data | Alpha Vantage (`NEWS_SENTIMENT`, `GLOBAL_QUOTE`, daily price history) |
| Structured logging | Postgres (every run, approved or rejected) |
| Human-readable log | Notion (approved predictions only) |
| Backend | FastAPI |
| Frontend | Next.js 14 + TypeScript + Tailwind + shadcn/ui |

## Key design decisions

**Two-layer hallucination prevention.** Before the Critic's LLM ever runs, a deterministic Python function checks that every cited event and source ID in a prediction actually resolves to a real object already in the pipeline state — exact membership checking, not LLM judgment. The LLM is reserved for what it's actually good at: judging whether the *reasoning* is sound, not whether references are real.

**The Critic runs on a different model than the Predictor.** If the same model both generates and grades a prediction, it's poorly positioned to catch its own reasoning failures. Gemini grading DeepSeek's output reduces that correlated-blind-spot risk.

**Bounded revision loop.** A rejected prediction gets routed back to the Predictor with the Critic's specific feedback, up to 2 attempts, before terminating. Enough room to fix a genuine inconsistency without turning into an unbounded negotiation.

**Adaptive retrieval.** If fewer than 3 relevant chunks are found for a ticker, the Retriever triggers a live ingestion pull before proceeding, rather than reasoning over near-empty evidence.

**Every run is logged, not just successes.** Rejected predictions are persisted to Postgres alongside approved ones — that's what makes it possible to eventually measure whether Critic approval actually correlates with real-world accuracy, instead of just assuming it does.

## Example: a real Critic rejection

From actual testing (not a curated example) — the Predictor called NVDA "up" while its own reasoning stated bearish technicals dominated. The Critic caught the internal contradiction and rejected it:

> *"The prediction's 'up' direction directly contradicts the explicitly stated 'neutral to slightly bearish' technical indicators without sufficient justification."*

## Status

| Component | Status |
|---|---|
| Orchestrator → Retriever → Analyst → Predictor → Critic pipeline | ✅ Implemented and verified end-to-end |
| Revision loop | ✅ Implemented and verified |
| Postgres run logging (approved + rejected) | ✅ Implemented and verified |
| Notion logging (approved) | ✅ Implemented and verified |
| Cold-start ingestion fallback | ✅ Implemented and verified |
| Frontend dashboard | ✅ Implemented |
| Backtest module | ✅ Implemented — awaiting predictions to mature past their horizon window |
| Knowledge graph persistence (Neo4j) | ⚠️ Extraction implemented; persistence not yet confirmed |
| Scheduled/multi-ticker batch mode | ⏳ Not built — currently single-ticker, on-demand |
| Deployment | Local-first; see demo recording below |

## Setup

```bash
# backend
cd backend
python -m venv .venv
./.venv/bin/pip install -e .
cp .env.example .env   # fill in your own API keys
docker run -d --name qdrant -p 6333:6333 -v qdrant_storage:/qdrant/storage qdrant/qdrant
./.venv/bin/python pipeline.py AAPL

# frontend
cd frontend
npm install
npm run dev
```

Required environment variables (see `.env.example`): `DEEPSEEK_API_KEY`, `GEMINI_API_KEY`, `ALPHA_VANTAGE_API_KEY`, `NOTION_API_KEY`, `NOTION_DATABASE_ID`, `QDRANT_URL`, `DATABASE_URL`.

## Demo

*[Screen recording / GIF here — a full run showing the reasoning trace and Critic evaluation is the most convincing 60 seconds of this whole project.]*

---

Built by [mili-virani](https://github.com/mili-virani)
