# InvestABull

Multi-agent equity research platform with:
- **FastAPI backend** (specialist pipeline + coordinator synthesis + SSE stream)
- **Next.js frontend** (live trace dashboard + markdown memo rendering)

Input a ticker (for example, `AAPL`) and the system runs specialist analysis across price, filings, news, and macro context, then synthesizes a final investment memo.

---

## Architecture Overview

### Backend (`backend/`)
- **API layer**: `backend/main.py` (health, research, and SSE endpoints)
- **Streaming orchestration bridge**: `backend/crew_logic.py`
- **Modular pipeline**: `backend/app/services/pipeline.py`
- **Coordinator synthesis**: `backend/app/services/coordinator_synthesis.py`
- **Configuration**: `backend/app/config.py`

### Frontend (`frontend/`)
- **App Router UI**: `frontend/src/app/page.tsx`
- **SSE client**: `frontend/src/lib/api.ts`
- **Styling**: Tailwind + custom markdown styles in `frontend/src/app/globals.css`

---

## Repository Structure

```text
InvestABull/
├── README.md
├── backend/
│   ├── main.py
│   ├── crew_logic.py
│   ├── requirements.txt
│   ├── .env.example
│   ├── .env                # local only; do not commit
│   ├── app/
│   │   ├── config.py
│   │   ├── agents/
│   │   ├── tools/
│   │   ├── services/
│   │   ├── schemas/
│   │   └── rag/
│   └── tests/
└── frontend/
    ├── package.json
    ├── .env.local          # local only; do not commit
    ├── src/
    │   ├── app/
    │   └── lib/
    └── public/
```

---

## Environment Variables

### Backend env file
Create `backend/.env` from `backend/.env.example` and populate keys.

Required for full flow:
- `GEMINI_API_KEY`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL` (recommended: `claude-sonnet-4-6`)
- `TAVILY_API_KEY`

Recommended:
- `FRED_API_KEY` (improves macro specialist output)

Common optional settings (defaults in `backend/app/config.py`):
- `SEC_EDGAR_USER_AGENT`
- `CHROMA_PERSIST_DIR`
- `SEC_FILINGS_CACHE_DIR`
- `EMBEDDING_MODEL`
- `LOG_LEVEL`
- `HTTP_TIMEOUT_SECONDS`
- `HTTP_MAX_RETRIES`

### Frontend env file
Create `frontend/.env.local`:

```bash
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

---

## Backend Quickstart

From repo root:

```bash
cd backend

# Python 3.12 recommended
python3.12 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

# First-time setup
cp .env.example .env
# edit .env and add your real keys

python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Backend should be available at `http://127.0.0.1:8000`.

---

## Frontend Quickstart

From repo root (separate terminal):

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:3000` (or next available port if 3000 is in use).

---

## Live Streaming Test (SSE)

With backend running:

```bash
curl -N -X POST http://127.0.0.1:8000/api/research/stream \
  -H "Content-Type: application/json" \
  -d '{"ticker":"AAPL"}'
```

A successful run streams multiple `data:` events and ends with a `Memo Ready` event whose `meta` includes:
- `memo` (markdown report)
- `coordinator` (expected `"claude"` when Anthropic model succeeds)

---

## Production Notes

- Never commit `.env` or `.env.local` files with secrets.
- Keep API keys provider-scoped and rotate if exposed.
- If Anthropic model IDs change, update `ANTHROPIC_MODEL` in `backend/.env`.
- For local debugging, use backend logs plus frontend raw trace panel to inspect event flow.
