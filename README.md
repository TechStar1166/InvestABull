# InvestABull

> Multi-agent equity research platform that turns a single ticker into a synthesized institutional-style investment memo.

InvestABull fans out four specialist agents (Price, Filings, News, Macro) over a ticker, streams their progress in real-time over Server-Sent Events (SSE), and hands the structured findings to a Claude coordinator that writes the final Markdown memo.

- **Backend** — FastAPI specialist pipeline + Claude coordinator + SSE stream
- **Frontend** — Next.js 16 (App Router) live trace dashboard + Markdown memo renderer

---

## Architecture Overview

### Backend (`backend/`)
- **API layer** — `backend/main.py` (`/health`, `/research`, `/api/research/stream`, `/api/filings/ingest`)
- **Streaming orchestration bridge** — `backend/crew_logic.py`
- **Modular specialist pipeline** — `backend/app/services/pipeline.py`
- **Claude coordinator synthesis** — `backend/app/services/coordinator_synthesis.py`
- **Specialist agents (Gemini)** — `backend/app/agents/specialists.py`
- **Data tools** — `backend/app/tools/` (`yfinance_tool`, `tavily_tool`, `fred_tool`, `sec_filings_tool`)
- **RAG over SEC 10-K filings (ChromaDB)** — `backend/app/rag/`
- **Centralized configuration** — `backend/app/config.py`

### Frontend (`frontend/`)
- **App Router UI** — `frontend/src/app/page.tsx`
- **Streaming components** — `frontend/src/components/` (`TickerInput`, `AgentProgress`, `TraceLog`, `ReportViewer`)
- **SSE client** — `frontend/src/lib/api.ts`
- **Trace state derivation** — `frontend/src/lib/research.ts`
- **Styling** — TailwindCSS 4 + custom Markdown styles in `frontend/src/app/globals.css`

---

## Repository Structure

```text
InvestABull/
├── README.md
├── .gitignore
├── backend/
│   ├── main.py                # FastAPI app + middleware
│   ├── crew_logic.py          # SSE streaming bridge
│   ├── schemas.py             # Shared TraceEvent schema
│   ├── tracing.py             # SSE frame formatter
│   ├── requirements.txt
│   ├── run_dev.sh
│   ├── .env.example           # template (committed)
│   ├── .env                   # local secrets only — never committed
│   ├── app/
│   │   ├── config.py
│   │   ├── agents/            # specialist runners + Gemini client + prompts
│   │   ├── tools/             # yfinance, Tavily, FRED, SEC EDGAR wrappers
│   │   ├── services/          # pipeline + coordinator bridge + Claude synthesis
│   │   ├── schemas/           # Pydantic models (typed envelopes)
│   │   └── rag/               # 10-K ingestion + ChromaDB store + retrieval
│   └── tests/                 # pytest suite (API, pipeline, tools, RAG, schemas)
└── frontend/
    ├── package.json
    ├── next.config.ts
    ├── tsconfig.json
    ├── eslint.config.mjs
    ├── postcss.config.mjs
    ├── .env.local             # local only — never committed
    ├── public/
    └── src/
        ├── app/               # layout, page, global styles
        ├── components/        # TickerInput, AgentProgress, TraceLog, ReportViewer
        └── lib/               # SSE client + trace state helpers
```

---

## Prerequisites

- **Python 3.12** (recommended; 3.11+ should work)
- **Node.js 20+** and **npm 10+**
- API keys for Google Gemini, Anthropic Claude, and Tavily (FRED key is optional but recommended)

---

## Environment Variables

### Backend — `backend/.env`
Copy `backend/.env.example` to `backend/.env` and fill in your keys.

**Required for the full flow:**
- `GEMINI_API_KEY` — powers the four specialist agents
- `ANTHROPIC_API_KEY` — powers the Claude coordinator
- `ANTHROPIC_MODEL` — recommended: `claude-sonnet-4-6`
- `TAVILY_API_KEY` — powers the News specialist

**Recommended:**
- `FRED_API_KEY` — improves Macro specialist output
- `SEC_EDGAR_USER_AGENT` — required by SEC fair-use policy: `"Your Name <you@example.com>"`

**Optional (defaults live in `backend/app/config.py`):**
- `CHROMA_PERSIST_DIR`, `SEC_FILINGS_CACHE_DIR`, `EMBEDDING_MODEL`
- `LOG_LEVEL`, `HTTP_TIMEOUT_SECONDS`, `HTTP_MAX_RETRIES`
- `FILINGS_READ_ONLY`, `TAVILY_*`, `NEWS_LLM_*`, `FRED_*` (see `.env.example` for the full list)

### Frontend — `frontend/.env.local`
Create a single-line file:

```bash
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

---

## Backend — Step-by-Step Setup

Open a terminal in the repository root and run:

```bash
# 1. Enter the backend directory
cd backend

# 2. Create a Python 3.12 virtual environment
python3.12 -m venv .venv

# 3. Activate the virtual environment
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows PowerShell

# 4. Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 5. Configure environment variables
cp .env.example .env
# Open .env in your editor and paste your real API keys

# 6. Start the FastAPI server (auto-reloads on code changes)
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

The API is now live at `http://127.0.0.1:8000`. Quick checks:

- `GET  /health` → `{"status":"ok","service":"investabull-backend"}`
- `GET  /docs` → interactive OpenAPI UI
- `POST /research` → full specialist pipeline (JSON response)
- `POST /api/research/stream` → SSE stream of trace events + final memo

### Run the test suite

```bash
# from backend/, with .venv active
pytest -q
```

---

## Frontend — Step-by-Step Setup

Open a **second terminal** (keep the backend running) and from the repository root:

```bash
# 1. Enter the frontend directory
cd frontend

# 2. Install Node dependencies
npm install

# 3. Configure the frontend environment
echo "NEXT_PUBLIC_API_URL=http://127.0.0.1:8000" > .env.local

# 4. Start the Next.js dev server
npm run dev
```

Open `http://localhost:3000` (or the next free port if 3000 is taken) in your browser. Type a ticker (e.g. `AAPL`), click **Generate Research**, and watch the specialists complete in real time before the Markdown memo renders.

### Production build (optional)

```bash
npm run build && npm start
```

---

## Live Streaming Test (cURL)

With the backend running:

```bash
curl -N -X POST http://127.0.0.1:8000/api/research/stream \
  -H "Content-Type: application/json" \
  -d '{"ticker":"AAPL"}'
```

A successful run streams several `data:` events (one per specialist completion) and ends with a `Memo Ready` event whose `meta` includes:
- `memo` — the final Markdown investment memo
- `coordinator` — `"claude"` when Anthropic succeeds, `"fallback"` otherwise
- `anthropic_model` — the model id Claude actually answered with
- `payload` — the full structured `CoordinatorPayload` JSON

---

## Code Source Declaration

This section documents what is original work, what comes from third-party libraries, and how AI development tools were used during the build. It is provided in the spirit of academic honesty for the **CIS 4930 — Agentic AI** final project.

### 1. Original work (authored by the project team)

All of the following were designed, written, reviewed, and tested by the project author(s):

- **Multi-agent orchestration design** — the four-specialist + coordinator topology, the `CoordinatorPayload` data contract, the failure-envelope strategy, and the `ThreadPoolExecutor`-based concurrent fan-out (`backend/app/services/pipeline.py`).
- **SSE streaming bridge** — the asyncio queue + `run_coroutine_threadsafe` pattern that lets a synchronous specialist pipeline stream `TraceEvent`s out through FastAPI's `StreamingResponse` (`backend/crew_logic.py`, `backend/main.py`, `backend/tracing.py`).
- **Pydantic schema layer** — every typed envelope under `backend/app/schemas/` (`PriceMetrics`, `NewsDigest`, `MacroDigest`, `FilingsFindings`, the `SpecialistAgentOutput[T]` envelope, etc.).
- **Specialist prompt engineering** — the system prompts in `backend/app/agents/prompts/{price,news,macro,filings}.md` and the structured-output runner with self-correction (`backend/app/agents/specialists.py`, `backend/app/agents/parsers.py`).
- **Coordinator prompt assembly** — `build_coordinator_markdown_prompt`, the multi-model fallback ladder, and the deterministic Markdown fallback (`backend/app/services/coordinator_bridge.py`, `backend/app/services/coordinator_synthesis.py`).
- **Data tool wrappers** — defensive, retry-aware adapters around yfinance, Tavily, FRED, and SEC EDGAR (`backend/app/tools/`).
- **RAG pipeline for SEC 10-K filings** — section-aware chunking, ChromaDB persistence layer, and per-section retrieval (`backend/app/rag/`).
- **Frontend UX** — the live streaming dashboard, derived progress state, raw-trace panel, and Markdown memo viewer (`frontend/src/app/page.tsx`, `frontend/src/components/`, `frontend/src/lib/research.ts`, `frontend/src/lib/api.ts`).
- **Test suite** — pytest coverage for the API, pipeline, schemas, parsers, specialist runners, RAG chunking/pipeline, and each external tool (`backend/tests/`).

### 2. External libraries and APIs used

The project stands on the shoulders of these third-party tools (versions pinned in `backend/requirements.txt` and `frontend/package.json`):

**LLMs and orchestration**
- [`anthropic`](https://docs.anthropic.com/) — Claude API (coordinator agent)
- [`google-generativeai`](https://ai.google.dev/) — Gemini API (specialist agents)
- [`crewai`](https://www.crewai.com/) and [`langchain`](https://www.langchain.com/) (`langchain-core`, `langchain-community`, `langchain-google-genai`, `langchain-anthropic`) — installed as part of the agent ecosystem; this submission ultimately uses a custom thread-pool orchestrator (`pipeline.py`) rather than CrewAI's `Crew.kickoff()` for tighter latency control, but the libraries are kept in `requirements.txt` for parity with course materials and to ease swap-in experiments.

**Data providers**
- [`yfinance`](https://github.com/ranaroussi/yfinance) — Yahoo Finance price + valuation metrics
- [`tavily-python`](https://docs.tavily.com/) — financial news search
- [`fredapi`](https://github.com/mortada/fredapi) — Federal Reserve Economic Data (macro indicators)
- [`sec-edgar-downloader`](https://github.com/jadchaar/sec-edgar-downloader) + `beautifulsoup4` + `lxml` — SEC 10-K download and HTML parsing

**RAG**
- [`chromadb`](https://www.trychroma.com/) — local persistent vector store
- [`sentence-transformers`](https://www.sbert.net/) (`all-MiniLM-L6-v2`) — embedding model

**Web framework / utilities**
- [`fastapi`](https://fastapi.tiangolo.com/), [`uvicorn`](https://www.uvicorn.org/), [`pydantic`](https://docs.pydantic.dev/), `pydantic-settings`, `httpx`, `tenacity`, `python-dotenv`

**Testing**
- [`pytest`](https://docs.pytest.org/), `pytest-asyncio`

**Frontend**
- [`next`](https://nextjs.org/) (App Router), [`react`](https://react.dev/), [`react-dom`](https://react.dev/), [`react-markdown`](https://github.com/remarkjs/react-markdown)
- [`tailwindcss`](https://tailwindcss.com/), `@tailwindcss/postcss`
- [`lucide-react`](https://lucide.dev/) (icons), [`clsx`](https://github.com/lukeed/clsx) (className utility)
- TypeScript, ESLint (`eslint`, `eslint-config-next`)

All third-party packages are installed via `pip` / `npm` from public registries; nothing is vendored or copy-pasted into the source tree.

### 3. AI development tools used during authoring

The author used AI coding assistants (e.g. ChatGPT / Claude / Cursor) as **pair-programming aids** while building this project — for tasks like scaffolding boilerplate, suggesting Pydantic patterns, drafting prompt skeletons, and reviewing diffs. Every AI-suggested change was read, edited, integrated, and tested by the author; no code was committed verbatim without review. Architectural decisions (the four-specialist split, the `CoordinatorPayload` contract, the SSE bridge design, the RAG section-aware chunking strategy) and final wording of all prompts and memos are the author's own.

### 4. Data and content licensing

- Market data (yfinance / Yahoo Finance), news (Tavily), macro series (FRED), and filings (SEC EDGAR) are pulled live at runtime from their respective providers under their published terms of use. SEC EDGAR access uses a descriptive `User-Agent` per the SEC's fair-use policy.
- No proprietary datasets are bundled with this repository.

---

## Security & Operational Notes

- **Never commit `.env` or `.env.local`.** They are listed in `.gitignore`; `backend/.env.example` is the only env template that is tracked.
- **No API keys are hardcoded anywhere in the source tree.** All keys are read from environment variables via `app/config.py` (`pydantic-settings`).
- Rotate any key that is ever pasted into a shared channel, screenshot, or commit history.
- If Anthropic deprecates a model snapshot, update `ANTHROPIC_MODEL` in `backend/.env` — the synthesis layer already falls back across a small candidate list.
- For local debugging, watch the backend logs side-by-side with the frontend's **Raw events** panel to inspect the SSE frame flow.

---

## Troubleshooting

| Symptom | Likely cause / fix |
| --- | --- |
| Frontend banner stuck on `API: Unreachable` | Backend not running, or `NEXT_PUBLIC_API_URL` is missing — restart `npm run dev` after editing `frontend/.env.local`. |
| `ANTHROPIC_API_KEY not configured` in the memo | Add the key to `backend/.env` and restart `uvicorn`. The pipeline still completes; only the coordinator falls back. |
| `SEC_EDGAR_USER_AGENT` warning | Set a descriptive UA string per SEC fair-use policy. |
| Slow first run for a new ticker | First-time 10-K ingestion downloads + chunks + embeds the filing. Subsequent runs hit the ChromaDB cache. |
| `429` from Tavily | Lower `TAVILY_MAX_RESULTS` or set `TAVILY_SEARCH_DEPTH=basic` in `backend/.env`. |

---

## License

Coursework submission for **CIS 4930 — Agentic AI**. Not licensed for redistribution outside of academic evaluation.
