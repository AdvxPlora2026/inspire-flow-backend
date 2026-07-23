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

The REST user system supports registration, login, profile updates, and
logout. See [HANDOFF_USERSYS.MD](HANDOFF_USERSYS.MD) for request examples,
credential handling, and error responses.

## Project structure

```text
.
├── migrations/      # Alembic database revisions
└── src/inspire_flow_backend/
    ├── api/          # HTTP routers and endpoint definitions
    │   └── routes/
    ├── core/         # Configuration, identity, security, and shared errors
    ├── data/         # SQLAlchemy persistence boundary
    │   ├── models/   # User and authentication-session entities
    │   └── repositories/ # Database access implementations
    ├── schemas/      # Pydantic request and response contracts
    ├── services/     # Application and business behavior
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

Keep secrets in `.env`; it is ignored by Git. `.env.example` contains only
safe defaults and remains tracked.

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
