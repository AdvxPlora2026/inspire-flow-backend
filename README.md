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
  "status": "ok",
  "service": "Inspire Flow Backend",
  "environment": "development"
}
```

The REST API supports registration, login, creator profiles, encrypted
long-term memories, durable Agent conversations, and logout. See
[HANDOFF_USERSYS.MD](docs/HANDOFF_USERSYS.MD) for authentication and profile
examples, then [HANDOFF_AGENT_MEMORY.md](docs/HANDOFF_AGENT_MEMORY.md) for
conversation and memory integration.

The InspireFlow Agent includes date/time, no-key web search, safe webpage
fetching, local rolling context compression, and user-scoped memory. See
[Agent service handoff](docs/prompt.md) for its prompt, tools, provider
configuration, limits, and security boundaries.

## Project structure

```text
.
├── migrations/      # Alembic database revisions
└── src/inspire_flow_backend/
    ├── api/          # HTTP routers and endpoint definitions
    │   └── routes/
    ├── core/         # Configuration, identity, security, and shared errors
    ├── data/         # SQLAlchemy persistence boundary
    │   ├── models/   # Users, profiles, conversations, messages, and memories
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
