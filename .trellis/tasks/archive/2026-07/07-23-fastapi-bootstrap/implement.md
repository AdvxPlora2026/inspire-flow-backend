# FastAPI Bootstrap Implementation Plan

> **For agentic workers:** Follow this plan task-by-task. Use
> `trellis-before-dev` before edits and preserve the red-green-refactor order.

**Goal:** Create a uv-managed, layered FastAPI starter application with a
tested health endpoint and repository hygiene.

**Architecture:** Install a packaged `src/inspire_flow_backend` application.
Routes delegate to services, Pydantic schemas own response contracts, core
owns settings, and data packages reserve persistence boundaries.

**Tech Stack:** Python 3.13, uv, FastAPI, Pydantic Settings, Uvicorn, pytest,
HTTPX2, Ruff.

---

### Task 1: Initialize uv project metadata

**Files:**

- Create: `.python-version`
- Create: `pyproject.toml`
- Create: `uv.lock`

- [ ] **Step 1: Initialize metadata without generated application code**

```bash
uv init --bare --name inspire-flow-backend --python 3.13 \
  --vcs none --author-from none .
uv python pin 3.13
```

Expected: `pyproject.toml` and `.python-version` exist; no generated Python
function precedes the first failing test.

- [ ] **Step 2: Configure the package and quality tools**

Add the uv build backend, a project description, and these tool settings:

```toml
[build-system]
requires = ["uv_build>=0.11.28,<0.12.0"]
build-backend = "uv_build"

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

- [ ] **Step 3: Resolve dependencies with uv**

```bash
uv add --no-sync fastapi pydantic-settings "uvicorn[standard]"
uv add --dev --no-sync httpx2 pytest ruff
uv sync --dev --no-install-project
```

Expected: uv creates `.venv`, installs third-party dependencies, and writes
`uv.lock`. The local package is intentionally absent until the first RED test
has run.

### Task 2: Implement validated application settings with TDD

**Files:**

- Create: `tests/test_config.py`
- Create: `src/inspire_flow_backend/__init__.py`
- Create: `src/inspire_flow_backend/core/__init__.py`
- Create: `src/inspire_flow_backend/core/config.py`

- [ ] **Step 1: Write the failing settings test**

```python
from importlib import import_module


def test_settings_read_prefixed_environment_variables(monkeypatch):
    monkeypatch.setenv("APP_NAME", "Configured Service")
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("APP_DEBUG", "true")
    monkeypatch.setenv("APP_API_V1_PREFIX", "/custom/v1")

    config = import_module("inspire_flow_backend.core.config")
    config.get_settings.cache_clear()
    settings = config.get_settings()

    assert settings.name == "Configured Service"
    assert settings.environment == "test"
    assert settings.debug is True
    assert settings.api_v1_prefix == "/custom/v1"

    config.get_settings.cache_clear()
```

- [ ] **Step 2: Verify the expected red state**

```bash
uv run pytest tests/test_config.py -v
```

Expected: FAIL because `inspire_flow_backend.core.config` does not exist.

- [ ] **Step 3: Add the minimal settings implementation**

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="APP_",
        extra="ignore",
    )

    name: str = "Inspire Flow Backend"
    environment: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

Package `__init__.py` files remain free of side effects.

- [ ] **Step 4: Verify green**

```bash
uv sync --dev
uv run pytest tests/test_config.py -v
```

Expected: PASS.

### Task 3: Add the versioned health API with TDD

**Files:**

- Create: `tests/api/test_health.py`
- Create: `src/inspire_flow_backend/schemas/health.py`
- Create: `src/inspire_flow_backend/services/health.py`
- Create: `src/inspire_flow_backend/api/routes/health.py`
- Create: `src/inspire_flow_backend/api/router.py`
- Create: `src/inspire_flow_backend/main.py`
- Create: package `__init__.py` files under `api/`, `api/routes/`, `schemas/`,
  and `services/`

- [ ] **Step 1: Write the failing endpoint test**

```python
from importlib import import_module

from fastapi.testclient import TestClient


def test_health_check_returns_service_metadata():
    main = import_module("inspire_flow_backend.main")

    with TestClient(main.app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Inspire Flow Backend",
        "environment": "development",
    }
    assert "/api/v1/health" in main.app.openapi()["paths"]
```

- [ ] **Step 2: Verify the expected red state**

```bash
uv run pytest tests/api/test_health.py -v
```

Expected: FAIL because `inspire_flow_backend.main` does not exist.

- [ ] **Step 3: Add the response contract and service**

```python
# schemas/health.py
from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    environment: str
```

```python
# services/health.py
from inspire_flow_backend.core.config import Settings
from inspire_flow_backend.schemas.health import HealthResponse


def build_health_response(settings: Settings) -> HealthResponse:
    return HealthResponse(
        service=settings.name,
        environment=settings.environment,
    )
```

- [ ] **Step 4: Add routing and application construction**

```python
# api/routes/health.py
from typing import Annotated

from fastapi import APIRouter, Depends

from inspire_flow_backend.core.config import Settings, get_settings
from inspire_flow_backend.schemas.health import HealthResponse
from inspire_flow_backend.services.health import build_health_response

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health_check(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    return build_health_response(settings)
```

```python
# api/router.py
from fastapi import APIRouter

from inspire_flow_backend.api.routes.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
```

```python
# main.py
from fastapi import FastAPI

from inspire_flow_backend.api.router import api_router
from inspire_flow_backend.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title=settings.name, debug=settings.debug)
    application.include_router(api_router, prefix=settings.api_v1_prefix)
    return application


app = create_app()
```

- [ ] **Step 5: Verify green and regressions**

```bash
uv run pytest -v
```

Expected: both settings and endpoint tests PASS.

### Task 4: Establish data boundaries and developer documentation

**Files:**

- Create: `src/inspire_flow_backend/data/__init__.py`
- Create: `src/inspire_flow_backend/data/models/__init__.py`
- Create: `src/inspire_flow_backend/data/repositories/__init__.py`
- Create: `.env.example`
- Create: `README.md`
- Modify: `.gitignore`

- [ ] **Step 1: Add structural persistence packages**

Create side-effect-free packages documenting that `models` owns persistence
entities and `repositories` owns storage access. Do not add an ORM or fake
repository behavior.

- [ ] **Step 2: Add a safe environment template**

```dotenv
APP_NAME=Inspire Flow Backend
APP_ENVIRONMENT=development
APP_DEBUG=false
APP_API_V1_PREFIX=/api/v1
```

- [ ] **Step 3: Expand `.gitignore`**

Preserve the existing local-agent entries, add standard Python/uv, cache,
coverage, secrets, logs, IDE, and OS exclusions, and explicitly keep
`.env.example` trackable. Do not ignore `uv.lock`.

- [ ] **Step 4: Document developer workflow**

Document:

```bash
uv sync --dev
uv run uvicorn inspire_flow_backend.main:app --reload
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Also document `GET /api/v1/health`, interactive docs at `/docs`, environment
variables, and each application layer.

### Task 5: Quality and runtime verification

- [ ] **Step 1: Format and lint**

```bash
uv run ruff format .
uv run ruff check . --fix
uv run ruff check .
uv run ruff format --check .
```

Expected: both final check commands exit 0.

- [ ] **Step 2: Run the full test suite**

```bash
uv run pytest -v
```

Expected: all tests PASS without warnings.

- [ ] **Step 3: Verify package import and runtime endpoint**

```bash
uv run python -c \
  "from inspire_flow_backend.main import app; assert '/api/v1/health' in app.openapi()['paths']"
```

Expected: exit 0.

- [ ] **Step 4: Verify ignore and lockfile behavior**

```bash
git check-ignore .venv .env .pytest_cache .ruff_cache
git check-ignore -q uv.lock && exit 1 || true
git check-ignore -q .env.example && exit 1 || true
```

Expected: generated/local paths are ignored; `uv.lock` and `.env.example` are
not ignored.
