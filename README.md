# Executive Assistant Copilot — Multi-Agent System

Production-oriented backend that combines **Google ADK** (Gemini Flash), **FastAPI**, **MCP-style clients** (BigQuery, Google Maps, Google Calendar, Google Tasks), and an **AlloyDB-compatible** SQL layer (PostgreSQL in production, SQLite for local development).

This is not a single chatbot: a root **orchestrator** agent delegates to specialist sub-agents via `AgentTool`, runs a **reflection** tool for risky plans, and uses **durable long-term memory** (preferences, notes, conversation turns, workflow history) plus **short-term** ADK session state.

## Product USP

The prototype now emphasizes a stronger, real-world use case than a generic assistant: **Chief-of-Staff Autopilot**.

- It does not just answer questions. It builds an execution-ready **daily brief** from calendar events, open tasks, saved notes, user preferences, and travel constraints.
- It persists **conversation memory** and **workflow runs** into SQL, so future turns can recover context even when the runtime session is recreated.
- It exposes that memory via API for debugging and demo evidence, which makes the multi-agent behavior inspectable.

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
- **Memory** (`app/db/memory.py`): long-term DB context, persisted conversation turns, and workflow history; ADK `InMemorySessionService` for turn-local state.
- **External tools** (`app/tools/mcp_clients.py`): BigQuery, Maps, Google Calendar, and Google Tasks with MCP, direct REST, or mock modes.
- **Daily brief workflow** (`app/workflows/daily_brief.py`): a high-value workflow that converts fragmented data into a plan for the day.

### Repository layout

The UI lives under **`backend/frontend/`** on purpose: it is **static files** (HTML/CSS/JS) served by the same FastAPI process via `StaticFiles` at **`/ui/`**. That gives one process to run locally, no separate dev server, and no CORS setup for the debug console. For production you might move to **`frontend/`** at the repo root and build with Vite/React, or serve assets from Cloud Storage—update `app/main.py` if you relocate the folder.

```
hackathon/
├── .gitignore
└── backend/
    ├── .env                 # local secrets (not committed)
    ├── env.sample           # variable names template (copy to .env)
    ├── scripts/deploy_cloud_run.sh
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
        └── workflows/         # executor + daily brief workflow
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
# export MCP_CALENDAR_SSE_URL="https://..."
# export MCP_TASKS_SSE_URL="https://..."
# Optional: direct Google Workspace REST access
# export GOOGLE_WORKSPACE_ACCESS_TOKEN="ya29..."
# export GOOGLE_CALENDAR_ID="primary"
# export GOOGLE_TASKS_LIST_ID="@default"
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

Python version, whether the MCP SDK can load, `adk_app_name`, `gemini_model`, Calendar / Tasks mode (`mock`, `rest`, `mcp`), **`bigquery_mode`** and **`maps_mode`** (`mcp` vs `mock`), and **`database_mode`** (`sqlite` vs `postgresql`) for hackathon demos.

### `GET /api/users/{user_id}/memory`

Returns persisted conversation turns and workflow runs for a user. This is useful for demoing agent memory continuity and verifying that workflows are being stored in the database.

## Hackathon judge demo (one scripted flow)

Use this to show **multi-agent coordination**, **tools**, **DB memory**, and **API** in under five minutes.

1. **Seed data** (optional but makes the brief rich): `PYTHONPATH=. python -m app.workflows.sample_workflows`
2. **Open** `/ui/`, enable **Full trace**.
3. **Killer prompt** (or paste into `curl` as `query`):

   > *Build my daily brief for today: pull my calendar, open tasks, and any notes tagged “board”; call out conflicts and suggest one focus block. If the plan is busy, use reflection.*

   Expect **`build_daily_brief_impl`** and/or multiple **`calendar_agent`**, **`task_agent`**, **`notes_agent`** tool calls in **Tools** / **Timeline**, plus a coherent **Response**.
4. **Proof of persistence:** `GET /api/users/demo-user/memory` — conversation turns and workflow runs after the query.
5. **Proof of stack:** `GET /api/meta` — confirm `adk_app_name`, `bigquery_mode` / `maps_mode` / Calendar / Tasks modes, and `database_mode`.

**One-liner against a deployed base URL** (`$BASE` = `https://….run.app`, no trailing slash):

```bash
BASE=https://YOUR-SERVICE-XXXX.us-central1.run.app
curl -s "$BASE/health" && curl -s "$BASE/api/meta" | jq .
curl -s "$BASE/query?debug=true" -H "Content-Type: application/json" \
  -d '{"user_id":"demo-user","query":"Build my daily brief for today: calendar, open tasks, notes about the board; flag conflicts and suggest a focus block."}' | jq '.status, (.actions | length)'
curl -s "$BASE/api/users/demo-user/memory" | jq .
```

## Example `curl` calls

```bash
curl -s http://127.0.0.1:8080/health

curl -s http://127.0.0.1:8080/api/meta | jq .

curl -s http://127.0.0.1:8080/api/users/demo-user/memory | jq .

curl -s http://127.0.0.1:8080/query \
  -H "Content-Type: application/json" \
  -d '{"user_id":"demo-user","query":"Create a daily brief for today and protect a deep work block."}' | jq .

curl -s "http://127.0.0.1:8080/query?debug=true" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"demo-user","query":"Check my Google Calendar this afternoon and add a follow-up item to Google Tasks."}' | jq .
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

## Deployment (frontend + backend)

The UI is static files under `frontend/` served by the **same** FastAPI process at `/ui/` — you deploy **one** container or process.

### Google Cloud Run — FastAPI + UI (redeploy)

From **`backend/`**, using Artifact Registry + Cloud Build:

```bash
export PROJECT=your-gcp-project-id
export REGION=us-central1
export SERVICE=executive-assistant
export GOOGLE_API_KEY=your-gemini-key   # or omit and set secrets in Console

./scripts/deploy_cloud_run.sh
```

The script creates the docker repo if missing, runs `gcloud builds submit`, then `gcloud run deploy`. Override **`PROJECT`**, **`REGION`**, **`SERVICE`**, **`ARTIFACT_REPO`** as needed.

**Secrets (recommended):** create `GOOGLE_API_KEY` in [Secret Manager](https://cloud.google.com/secret-manager/docs/creating-and-accessing-secrets), grant the Cloud Run service account **`roles/secretmanager.secretAccessor`**, then deploy with:

```bash
gcloud run deploy "${SERVICE}" \
  --image "${IMAGE}" \
  --region "${REGION}" \
  --set-secrets="GOOGLE_API_KEY=GOOGLE_API_KEY:latest"
```

Add more env or secrets for **`DATABASE_URL`**, **`MCP_*_SSE_URL`**, **`GOOGLE_WORKSPACE_ACCESS_TOKEN`**, etc. Template variables: **[`env.sample`](env.sample)** (copy to `.env` locally; never commit `.env`).

### Live MCP and Workspace (not only mocks)

`/api/meta` shows **`mcp`** when SSE URLs are set, **`rest`** when **`GOOGLE_WORKSPACE_ACCESS_TOKEN`** is set (Calendar/Tasks), or **`mock`** otherwise.

- Set **`MCP_BIGQUERY_SSE_URL`**, **`MCP_MAPS_SSE_URL`**, **`MCP_CALENDAR_SSE_URL`**, **`MCP_TASKS_SSE_URL`** to your MCP gateway base URLs (see [`app/tools/mcp_clients.py`](app/tools/mcp_clients.py)).
- Or set **`GOOGLE_WORKSPACE_ACCESS_TOKEN`** for direct Calendar/Tasks REST without MCP.

On Cloud Run, add the same names as environment variables or secrets.

### Cloud SQL (PostgreSQL) for durable demos on Cloud Run

SQLite on Cloud Run is **ephemeral**; instances scale out or restart and you lose local files.

1. Create a [Cloud SQL Postgres](https://cloud.google.com/sql/docs/postgres/connect-run) instance and user.
2. Set:

   ```text
   DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@/DBNAME?host=/cloudsql/PROJECT:REGION:INSTANCE
   ```

   (Use the Cloud Run **Cloud SQL connection** add-on; see Google’s “Connect from Cloud Run” guide for the exact socket host string.)

3. Redeploy. **`GET /api/meta`** → `"database_mode": "postgresql"`. **`GET /api/users/.../memory`** survives restarts.

### Google Cloud — ADK `deploy cloud_run` (agents API)

This repo exposes **`root_agent`** in the **`backend/`** package for the official ADK CLI ([Cloud Run deploy docs](https://google.github.io/adk-docs/deploy/cloud-run/)).

Prerequisites: [Google Cloud SDK](https://cloud.google.com/sdk/docs/install), `pip install google-adk`, `gcloud auth login`, `gcloud config set project YOUR_PROJECT`.

**Auth / GenAI (pick one):**

- **Vertex AI** (typical on GCP):

  ```bash
  export GOOGLE_CLOUD_PROJECT="your-project-id"
  export GOOGLE_CLOUD_LOCATION="us-central1"
  export GOOGLE_GENAI_USE_VERTEXAI=True
  ```

- **AI Studio API key** (store in Secret Manager for Cloud Run):

  ```bash
  export GOOGLE_CLOUD_PROJECT="your-project-id"
  export GOOGLE_CLOUD_LOCATION="us-central1"
  export GOOGLE_GENAI_USE_VERTEXAI=False
  echo "your-key" | gcloud secrets create GOOGLE_API_KEY --data-file=- --project=your-project-id
  # Grant the Cloud Run runtime service account secretAccessor on GOOGLE_API_KEY
  ```

From **`backend/`** (this directory must be the agent folder so `app/`, `requirements.txt`, and `agent.py` are included):

```bash
cd backend
adk deploy cloud_run \
  --project="${GOOGLE_CLOUD_PROJECT}" \
  --region="${GOOGLE_CLOUD_LOCATION}" \
  --app_name="${APP_NAME:-agents}" \
  --service_name="executive-assistant" \
  --port=8000 \
  .
```

Optional: add **`--with_ui`** to ship the ADK web dev UI alongside the API (your custom HTML UI is still on **`app.main`** / Docker, not this command).

**Environment on Cloud Run:** set **`DATABASE_URL`** for AlloyDB or Cloud SQL (`postgresql+asyncpg://…`), and any **`MCP_*_SSE_URL`** / Workspace tokens as needed. SQLite on Cloud Run’s ephemeral disk is only OK for demos.

**FastAPI + static `/ui/` on GCP:** use **`Dockerfile`** + **`gcloud run deploy --source .`** from `backend/`, or the “Docker” section below— that path keeps **`POST /query`** and the Assistant UI.

### Docker (recommended)

From the `backend/` directory (Docker Desktop or any host with Docker):

```bash
docker build -t executive-assistant .
docker run --rm -p 8080:8080 \
  -e GOOGLE_API_KEY="your-key" \
  executive-assistant
```

Open **http://localhost:8080/** (redirects to `/ui/`). Override port with `-e PORT=3000` if needed.

**Compose** (SQLite persisted in a volume; set `GOOGLE_API_KEY` in `.env` or the shell):

```bash
cd backend
docker compose up --build
```

For **PostgreSQL** (e.g. managed DB), set `DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db?ssl=require` in the environment and drop the SQLite volume if unused.

### Render

1. New **Web Service** → connect the repo whose root is `backend/` (or set root directory to `backend` in the dashboard).
2. **Runtime**: Docker (uses `Dockerfile`).
3. Add environment variable **`GOOGLE_API_KEY`** (required for `/query`).
4. Optional: replace **`DATABASE_URL`** with a Render Postgres URL (`postgresql+asyncpg://…`).

If you use [Infrastructure as Code](https://render.com/docs/blueprint-spec), a sample `render.yaml` is included in this folder; adjust the service name and DB as needed.

### Fly.io

From `backend/` after [installing `flyctl`](https://fly.io/docs/hands-on/install-flyctl/):

```bash
fly launch --no-deploy   # choose app name & region
fly secrets set GOOGLE_API_KEY=your-key
fly deploy
```

Ensure the machine exposes **8080** (Fly sets `PORT`; the image CMD respects it).

### Railway / other PaaS

Use **Dockerfile** deploy, set **`GOOGLE_API_KEY`**, and assign **`PORT`** if the platform injects it (the start command uses `${PORT:-8080}`).

## License

Apache-2.0 (same family as Google ADK samples).
