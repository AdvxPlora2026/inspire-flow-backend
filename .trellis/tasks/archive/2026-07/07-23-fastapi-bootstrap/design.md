# FastAPI Bootstrap Technical Design

## Architecture

The project uses a packaged `src` layout installed into a `uv`-managed virtual
environment. FastAPI is the delivery boundary: routes validate and serialize
HTTP traffic, services own application behavior, schemas define transport
contracts, core owns process configuration, and data packages reserve the
persistence boundary without choosing an ORM prematurely.

```text
HTTP request
  -> api/routes/health.py
  -> services/health.py
  -> schemas/health.py
  -> HTTP response

Environment / .env
  -> core/config.py
  -> main.py and service dependency
```

## Directory Layout

```text
.
├── .env.example
├── .python-version
├── README.md
├── pyproject.toml
├── uv.lock
├── src/
│   └── inspire_flow_backend/
│       ├── __init__.py
│       ├── main.py
│       ├── api/
│       │   ├── __init__.py
│       │   ├── router.py
│       │   └── routes/
│       │       ├── __init__.py
│       │       └── health.py
│       ├── core/
│       │   ├── __init__.py
│       │   └── config.py
│       ├── data/
│       │   ├── __init__.py
│       │   ├── models/
│       │   │   └── __init__.py
│       │   └── repositories/
│       │       └── __init__.py
│       ├── schemas/
│       │   ├── __init__.py
│       │   └── health.py
│       └── services/
│           ├── __init__.py
│           └── health.py
└── tests/
    ├── test_config.py
    └── api/
        └── test_health.py
```

## Contracts

### Settings

`Settings` reads environment variables with the `APP_` prefix and optional
local `.env` file. Defaults are:

- `name = "Inspire Flow Backend"`
- `environment = "development"`
- `debug = false`
- `api_v1_prefix = "/api/v1"`

`get_settings()` is cached so one validated settings object is shared during
normal process execution. Tests explicitly clear the cache when mutating the
environment.

### Health API

`GET {api_v1_prefix}/health` has no request body. It responds with:

```json
{
  "status": "ok",
  "service": "Inspire Flow Backend",
  "environment": "development"
}
```

The route obtains settings through FastAPI dependency injection, calls
`build_health_response()`, and declares `HealthResponse` as its response model.

### Application construction

`create_app()` reads settings, constructs FastAPI with the configured name and
debug flag, and includes the shared API router under the configured prefix.
`app = create_app()` supports the conventional
`inspire_flow_backend.main:app` server import.

## Dependency Strategy

Runtime:

- `fastapi`
- `pydantic-settings`
- `uvicorn[standard]`

Development:

- `httpx2` for FastAPI/Starlette `TestClient`
- `pytest`
- `ruff`

`uv add` chooses compatible lower bounds and `uv.lock` records the exact
resolution. Before the first RED test creates the package, dependencies are
installed with `uv sync --no-install-project`; normal `uv sync` installs the
local package after its first `__init__.py` exists. The lockfile is
source-controlled; `.venv` is local-only.

## Trade-offs

- The initial data layer contains package boundaries but no database code.
  This makes ownership explicit without committing to an ORM before a real
  persistence requirement exists.
- A service function for the small health payload adds one hop, but it provides
  a concrete example of keeping application behavior out of routes.
- Python 3.13 is pinned for developer reproducibility while project metadata
  permits later supported Python releases.

## Compatibility and Rollback

There is no existing application API to migrate. Rollback consists of removing
the newly created Python project files and restoring the original `.gitignore`;
no persistent data or external system is affected.
