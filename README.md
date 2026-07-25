# Inspire Flow Backend

A layered FastAPI starter application with its Python interpreter,
dependencies, virtual environment, and lockfile managed by
[uv](https://docs.astral.sh/uv/).

## Requirements

- uv 0.11 or newer

The project pins Python 3.13 in `.python-version`. uv downloads a compatible
interpreter automatically when one is not already available.

## Quick start

Install the project and development dependencies:

```bash
uv sync --locked --dev
```

Create an optional local settings file:

```bash
cp .env.example .env
```

Create or upgrade the SQLite database:

```bash
uv run alembic upgrade head
```

Start the development server:

```bash
uv run uvicorn inspire_flow_backend.main:app --reload
```

The API is available at <http://127.0.0.1:8000>. Interactive documentation is
available at <http://127.0.0.1:8000/docs>.

## API endpoints

```bash
curl http://127.0.0.1:8000/api/v1/health
```

```json
{
  "status": "degraded",
  "services": {
    "database": "ok",
    "model": "not_configured",
    "injective": "not_configured"
  },
  "version": "dev",
  "service": "Inspire Flow Backend",
  "environment": "development"
}
```

The endpoint performs a real database probe without calling the model provider.
Missing optional model or Injective configuration returns `200` with
`status: "degraded"`. A database failure returns `503` with the same typed
response shape and `status: "unavailable"`.

The REST API supports registration, login, creator profiles, encrypted
long-term memories, durable Agent conversations, user-owned creative projects,
multi-project inspirations, creator Public Workshops, brand organizations,
brand discovery and engagement, and logout. Authenticated business writes use
24-hour idempotency keys. See [HANDOFF.md](docs/HANDOFF.md) for the complete
API contract and curl examples.

Projects can be entered manually or prepared as an editable, unsaved draft
from a natural-language description. The Agent can also list, inspect, edit,
create, and delete the current user's projects with explicit confirmation
before creation and deletion. Projects may carry an optional HTTP(S) icon URL;
unset icons are returned as `null`. See
[Project API and Agent handoff](docs/HANDOFF_PROJECTS.md).

Inspirations support an inbox workflow, manual or voice capture, Agent
provenance, multi-project links, keyword search, filters, and safe deletion
confirmation when a project or conversation would leave orphaned records. See
[Inspiration API and Agent handoff](docs/HANDOFF_INSPIRATIONS.md).

The InspireFlow Agent includes date/time, no-key web search, safe webpage
fetching, local rolling context compression, user-scoped memory, and internal
tools for explicitly requested identity changes and durable user-profile
summaries. The conversation UUID returned by the API is the persistent Agent
session ID and is always resolved together with the bearer-authenticated user.
Both request/response JSON and SSE streaming conversation endpoints are
available; streaming runs continue in the background if the client
disconnects. See [Agent service handoff](docs/prompt.md) for its prompt, tools,
provider configuration, limits, and security boundaries.

Public Workshop publishing uses editable drafts and immutable published
snapshots. Each profile field, social account, contact, and featured project
has an explicit audience. Contact values are encrypted and only returned after
server-side brand membership and creator authorization checks. Brand members
can discover visible creators, follow them, send collaboration interests, and
surface those events in the creator inbox.

Authenticated asynchronous speech transcription is available through an
isolated Celery worker and the pinned Replicate incredibly-fast-whisper model
through the Hack Club AI proxy. Provider failures do not terminate the API.
Successful results include clean text and detected language; the retained
`emotions` and `audio_events` compatibility fields are empty arrays. See the
[Replicate STT handoff](docs/HANDOFF_STT.md) for provider, Redis, worker, and
REST usage.

## Project structure

```text
.
├── migrations/      # Alembic database revisions
└── src/inspire_flow_backend/
    ├── api/          # HTTP routers and endpoint definitions
    │   └── routes/
    ├── core/         # Configuration, identity, security, and shared errors
    ├── data/         # SQLAlchemy persistence boundary
    │   ├── models/   # Users, content, workshops, brands, engagement, and idempotency
    │   └── repositories/ # Database access implementations
    ├── schemas/      # Pydantic request and response contracts
    ├── services/     # Application behavior, including users and Agent tools
    └── main.py       # FastAPI application factory and module-level app
```

The API layer validates and transports data. Services own application
behavior and transaction boundaries. Schemas own API contracts. Repositories
encapsulate SQLAlchemy queries, while Alembic manages schema changes.

## Configuration

Settings are loaded from environment variables and an optional `.env` file.

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_NAME` | `Inspire Flow Backend` | OpenAPI application name and service identity |
| `APP_VERSION` | `dev` | Deployment version, release identifier, or Git SHA |
| `APP_ENVIRONMENT` | `development` | Runtime environment label |
| `APP_DEBUG` | `false` | FastAPI debug mode |
| `APP_API_V1_PREFIX` | `/api/v1` | Prefix for version 1 endpoints |
| `APP_DATABASE_URL` | `sqlite:///./inspire_flow.db` | SQLAlchemy database URL |
| `APP_SESSION_TTL_HOURS` | `24` | Login session lifetime in hours |
| `APP_CONTEXT_ENCRYPTION_KEY` | blank | Fernet key supplied by deployment secret storage |
| `APP_CONTEXT_ENCRYPTION_KEY_FILE` | `.inspireflow-context.key` | Local context-key path used when the environment key is blank |
| `APP_AGENT_CONTEXT_TRIGGER_CHARACTERS` | `24000` | Unsummarized-history size that triggers compaction |
| `APP_AGENT_CONTEXT_MAX_CHARACTERS` | `48000` | Hard model-facing context budget |
| `APP_AGENT_CONTEXT_RECENT_TURNS` | `8` | Complete recent turns retained after compaction |
| `APP_AGENT_CONTEXT_SUMMARY_MAX_CHARACTERS` | `6000` | Maximum rolling-summary size |
| `APP_AGENT_MEMORY_MAX_ITEMS` | `30` | Maximum active memories injected per turn |
| `APP_AGENT_MEMORY_MAX_CHARACTERS` | `8000` | Memory-section character budget |
| `APP_AGENT_RUN_LOCK_TTL_SECONDS` | `600` | Stale conversation-run lock timeout |
| `APP_STT_ENABLED` | `false` | Enable asynchronous transcription submissions |
| `APP_STT_BROKER_URL` | `redis://127.0.0.1:6379/0` | Celery Redis broker |
| `APP_STT_QUEUE` | `stt` | Dedicated Celery queue |
| `APP_STT_SPOOL_DIR` | `.inspireflow-stt-spool` | Temporary raw-audio directory |
| `APP_STT_API_KEY` | blank | Hack Club AI bearer key; required by the enabled worker |
| `APP_STT_BASE_URL` | `https://ai.hackclub.com/proxy/v1/replicate` | Replicate-compatible proxy root |
| `APP_STT_MODEL` | `vaibhavs10/incredibly-fast-whisper:3ab86df6...` | Pinned Replicate model version |
| `APP_STT_REQUEST_TIMEOUT_SECONDS` | `70` | Per-request provider timeout |
| `APP_STT_PREDICTION_TIMEOUT_SECONDS` | `540` | Overall provider prediction deadline |
| `APP_STT_POLL_INTERVAL_SECONDS` | `1` | Poll interval after synchronous wait expires |
| `APP_STT_MAX_UPLOAD_MIB` | `64` | Maximum upload size |
| `APP_STT_MAX_DURATION_SECONDS` | `300` | Maximum decoded audio duration |
| `APP_STT_SOFT_TIME_LIMIT_SECONDS` | `600` | Celery soft task timeout |
| `APP_STT_HARD_TIME_LIMIT_SECONDS` | `660` | Celery child replacement timeout |
| `APP_STT_MAX_ATTEMPTS` | `3` | Worker-loss attempt bound |
| `APP_STT_READY_TTL_SECONDS` | `30` | Worker provider-readiness heartbeat TTL |
| `MODEL_API_KEY` | blank | OpenAI-compatible Chat Completions API credential |
| `MODEL_NAME` | blank | Model name used by the Agent, compactor, and extractor |
| `MODEL_BASE_URL` | blank | API root or complete `/chat/completions` endpoint |

Keep secrets in `.env`; it is ignored by Git. `.env.example` contains only
safe defaults and remains tracked. In local development, the first encrypted
context operation creates `.inspireflow-context.key` with owner-only
permissions. The file is ignored by Git. Back it up securely: losing this key
makes existing encrypted messages, summaries, and memories unreadable. In
deployment, inject `APP_CONTEXT_ENCRYPTION_KEY` from a secret manager instead
of relying on a local file.

## Quality checks

Run the test suite:

```bash
uv run pytest
```

Lint the project:

```bash
uv run ruff check .
```

Verify formatting:

```bash
uv run ruff format --check .
```

To format locally, run `uv run ruff format .`.

## Managing dependencies

Use uv rather than invoking pip directly:

```bash
uv add package-name
uv add --dev development-package
uv remove package-name
uv sync --dev
```

Commit both `pyproject.toml` and `uv.lock` whenever dependencies change.
