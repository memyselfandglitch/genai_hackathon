# Executive Assistant — Multi-Agent System

Production-oriented backend that combines **Google ADK** (Gemini Flash), **FastAPI**, **MCP-style clients** (BigQuery, Google Maps), and an **AlloyDB-compatible** SQL layer (PostgreSQL in production, SQLite for local development).

This is not a single chatbot: a root **orchestrator** agent delegates to specialist sub-agents via `AgentTool`, runs a **reflection** tool for risky plans, and uses **long-term memory** (preferences + notes) plus **short-term** ADK session state.

## Architecture

```
Client
  → POST /query (FastAPI)
    → WorkflowExecutor (ADK Runner + trace + retries)
      → executive_orchestrator (LlmAgent, Gemini Flash)
          → AgentTool(calendar_agent | task_agent | notes_agent | location_agent)
          → FunctionTool(load_memory_context, bigquery_analytics, reflect_on_plan)
              → SQLAlchemy (users, tasks, events, notes, preferences)
              → MCP clients (mock or HTTP SSE gateway)
```

- **Orchestrator** (`app/agents/orchestrator.py`): planning, delegation, MCP tool contracts, reflection.
- **Sub-agents** (`calendar_agent`, `task_agent`, `notes_agent`, `location_agent`): domain `LlmAgent`s with `FunctionTool`s.
- **Workflows** (`app/workflows/executor.py`): drains `Runner.run_async`, aggregates tool calls, handles retries with fresh sessions.
- **Memory** (`app/db/memory.py`): long-term DB context; ADK `InMemorySessionService` for conversation state.
- **MCP** (`app/tools/mcp_clients.py`): BigQuery + Maps tool schemas; mocks when URLs are unset.

### Repository layout

The UI lives under **`backend/frontend/`** on purpose: it is **static files** (HTML/CSS/JS) served by the same FastAPI process via `StaticFiles` at **`/ui/`**. That gives one process to run locally, no separate dev server, and no CORS setup for the debug console. For production you might move to **`frontend/`** at the repo root and build with Vite/React, or serve assets from Cloud Storage—update `app/main.py` if you relocate the folder.

```
hackathon/
├── .gitignore
└── backend/
    ├── .env                 # local secrets (not committed)
    ├── requirements.txt
    ├── README.md
    ├── exec_assistant.db      # SQLite if using default DATABASE_URL
    ├── frontend/              # debug UI → http://localhost:8080/ui/
    │   ├── index.html
    │   ├── styles.css
    │   └── app.js
    └── app/
        ├── main.py            # FastAPI app, mounts /ui, lifespan
        ├── env_bootstrap.py
        ├── api/routes.py      # /query, /health, /api/meta
        ├── agents/            # ADK orchestrator + sub-agents
        ├── core/              # config, logging, runtime
        ├── db/                # models, session, memory
        ├── tools/mcp_clients.py
        └── workflows/executor.py
```

## Setup

### Requirements

- **Python 3.10+** installs the official **`mcp`** package from `requirements.txt`. On older Python, ADK still runs, but you get a startup warning and BigQuery/Maps use **mocks/HTTP adapters** only.

### ADK `app_name` (session namespace)

The default **`APP_NAME=agents`** matches how ADK infers the root agent origin for stock `LlmAgent` (under `google/adk/agents/…`). That removes **“App name mismatch”** warnings. The product name is still “Executive Assistant”; `APP_NAME` is only the ADK session namespace. Override with env **`APP_NAME`** if you change your agent layout.

### Debug UI

Open **http://127.0.0.1:8080/** → redirects to **`/ui/`**. The page calls `POST /query?debug=true` and shows **tool calls**, **responses**, and an **event timeline**. **`GET /api/meta`** returns Python version, MCP SDK availability, and `adk_app_name`.

### Install steps

1. Create a virtualenv and install dependencies:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

2. Configure environment (copy and edit):

```bash
export GOOGLE_API_KEY="your-gemini-api-key"
export DATABASE_URL="sqlite+aiosqlite:///./exec_assistant.db"
# Production AlloyDB (PostgreSQL wire protocol):
# export DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/dbname?ssl=require"
export GEMINI_MODEL="gemini-flash-latest"
# Optional: real MCP gateways
# export MCP_BIGQUERY_SSE_URL="https://..."
# export MCP_MAPS_SSE_URL="https://..."
```

3. Seed demo data (optional):

```bash
cd backend
PYTHONPATH=. python -m app.workflows.sample_workflows
```

4. Run the API:

```bash
cd backend
PYTHONPATH=. uvicorn app.main:app --reload --port 8080
```

### If you see `API_KEY_INVALID`

- Store the key in **`backend/.env`** as `GOOGLE_API_KEY=...` (no spaces around `=`).
- In Google AI Studio, use **Copy key** and paste once. A single typo (**`0` vs `O`**, **`1` vs `l`**) invalidates the key.
- This project forces **`GOOGLE_GENAI_USE_VERTEXAI=0`** when a Studio key is loaded so requests go to `generativelanguage.googleapis.com` (same as the REST quickstart), not Vertex.

## API

### `POST /query`

**Request:**

```json
{
  "user_id": "demo-user",
  "query": "What meetings do I have this week and do any conflict?"
}
```

**Response:**

```json
{
  "status": "ok",
  "actions": [
    {
      "type": "function_call",
      "name": "calendar_agent",
      "args": { "request": "..." }
    },
    { "type": "function_response", "name": "calendar_agent", "response": "..." }
  ],
  "result": "Natural language answer from the orchestrator.",
  "trace": null,
  "error": null
}
```

With `?debug=true` (or `DEBUG=true` in settings), `trace` includes per-event metadata.

### `GET /health`

Liveness check.

### `GET /api/meta`

Python version, whether the MCP SDK can load, `adk_app_name`, and `gemini_model` (for the debug UI and operators).

## Example `curl` calls

```bash
curl -s http://127.0.0.1:8080/health

curl -s http://127.0.0.1:8080/api/meta | jq .

curl -s http://127.0.0.1:8080/query \
  -H "Content-Type: application/json" \
  -d '{"user_id":"demo-user","query":"Suggest a free hour tomorrow morning for a deep work block."}' | jq .

curl -s "http://127.0.0.1:8080/query?debug=true" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"demo-user","query":"Add a task to call CFO about margins."}' | jq .
```

## End-to-end check (API + UI + agents)

1. **`backend/.env`**: `GOOGLE_API_KEY` set; optional `DATABASE_URL`, `GEMINI_MODEL`.
2. **Install & run** (from `backend/`): `pip install -r requirements.txt`, then `PYTHONPATH=. uvicorn app.main:app --reload --port 8080`.
3. **`GET /health`** → `{"status":"ok"}`.
4. **`GET /api/meta`** → JSON with `python_version`, `mcp_package_installed`, `adk_app_name` (expect `agents`).
5. **Seed DB** (optional): `PYTHONPATH=. python -m app.workflows.sample_workflows`.
6. **Browser**: open **http://127.0.0.1:8080/** → should redirect to **`/ui/`**; confirm the header loads meta from `/api/meta`.
7. **Run a query** in the UI (or `curl` with `?debug=true`): `status` should be `ok`, **Result** has text, **Tool calls** lists `function_call` / `function_response`, **Timeline** shows events when debug is on.

If `/query` errors on the model, fix the API key; if the UI is 404, ensure `backend/frontend/` exists and you started uvicorn with `cwd` = `backend/` (or `PYTHONPATH` includes `app`).

## Observability

- Structured JSON lines via `app.core.logging.trace_event` (`TRACE` lines in logs).
- Enable `DEBUG=true` for SQL echo and ADK event traces.

## Extending

- Add a new specialist: implement `create_*_agent()` with tools, then register `AgentTool` on the orchestrator.
- Swap MCP mocks for real servers: set `MCP_*_SSE_URL` and align `HttpSSEMCPClient` with your gateway’s JSON-RPC shape.
- Replace `InMemorySessionService` with `DatabaseSessionService` from ADK for durable multi-instance sessions.

## License

Apache-2.0 (same family as Google ADK samples).
