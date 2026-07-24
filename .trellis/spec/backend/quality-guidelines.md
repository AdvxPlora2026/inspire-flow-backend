# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

Python and dependency state are managed with uv. Ruff owns formatting and
static lint checks; pytest owns executable behavior checks. New behavior
follows red-green-refactor and the final suite must be free of warnings.

---

## Forbidden Patterns

- Do not invoke `pip` directly or hand-edit `uv.lock`.
- Do not commit `.venv`, `.env`, caches, coverage output, or generated build
  products.
- Do not assemble typed API payloads as ad-hoc dictionaries in routes.
- Do not suppress warnings globally to make tests appear clean.
- Do not use the legacy `httpx` package with Starlette's current
  `TestClient`; it emits a deprecation warning.

---

## Required Patterns

- Pin the development Python line in `.python-version`.
- Declare dependencies in `pyproject.toml` through `uv add` / `uv remove` and
  commit the resulting `uv.lock`.
- During test-first initialization of a new packaged `src` project, use
  `uv sync --no-install-project` until the package `__init__.py` exists; then
  run normal `uv sync`.
- Use absolute imports from `inspire_flow_backend`.
- Keep package `__init__.py` files free of import side effects.
- Keep `.trellis` tracked for shared workflow context, but exclude its bundled
  scripts from Ruff because they are versioned workflow infrastructure rather
  than application source.
- Declare Pydantic response models on FastAPI routes.
- Run these checks before handoff:

```bash
uv lock --check
uv sync --locked --dev
uv run ruff check .
uv run ruff format --check .
uv run pytest -W error
```

---

## Testing Requirements

- Write the failing behavior test before production code.
- Test settings through real environment parsing with pytest's `monkeypatch`.
- Test HTTP contracts through FastAPI's `TestClient`.
- Use `httpx2` as the development dependency required by the currently locked
  Starlette 1.3.1. Installing only `httpx` works as a fallback in that version
  but emits `StarletteDeprecationWarning`.
- Clear `get_settings()`'s cache after tests that mutate the environment.
- Runtime smoke checks should start Uvicorn, make a real local HTTP request,
  and terminate the server process.
- Persistence changes must run Alembic against a fresh file-backed temporary
  SQLite database. Exercise both `upgrade head` and the supported downgrade.
- Authentication handoffs must use placeholders or shell variables for
  credentials. Scan documentation for accidental long bearer values or secret
  literals before delivery.
- Agent, compaction, extraction, conversation, and API tests must use fake
  model components. Stable automated tests never require a provider key, DNS,
  DuckDuckGo, or another public network.
- Context-persistence tests must prove encryption at rest, cross-user
  isolation, compaction cursor monotonicity, and raw-row preservation.
- Stable STT tests use fake engines and publishers. They must not install the
  `stt` group, start Redis, download weights, or import FunASR/Torch.
- Real STT inference and prefork crash-recovery checks are explicit opt-in
  operational smoke tests using the separate `.venv-stt` environment.
- Worker ORM tests must include an isolated subprocess that imports the worker
  entry point and calls `configure_mappers()` without relying on the main
  pytest process's model import order.
- Any test fixture that exercises credential redaction uses an obviously
  synthetic value that is not mistaken for a deliverable secret scan hit.

Example:

```python
with TestClient(app) as client:
    response = client.get("/api/v1/health")

assert response.status_code == 200
assert response.json()["status"] in {"ok", "degraded"}
```

---

## Code Review Checklist

- [ ] `uv.lock` matches `pyproject.toml`.
- [ ] Ruff lint and format checks pass.
- [ ] pytest passes with warnings treated as errors.
- [ ] New functions are covered directly or through an integration boundary.
- [ ] API routes, schemas, and services agree on field names and types.
- [ ] Environment keys are documented in both `.env.example` and README.
- [ ] Local/generated paths are ignored while `uv.lock` and `.env.example`
      remain trackable.
- [ ] No circular imports or route-to-storage coupling were introduced.
- [ ] Alembic can upgrade a fresh SQLite file to `head` and downgrade it to
      `base`.
- [ ] A real Uvicorn smoke test covers registration, login, authenticated
      access, logout, and rejected token reuse.
