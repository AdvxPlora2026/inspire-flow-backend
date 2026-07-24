# Bootstrap FastAPI Application

## Goal

Create a clean, runnable FastAPI backend whose Python interpreter,
dependencies, lockfile, and virtual environment are managed by `uv`. Establish
clear boundaries for API delivery, configuration, schemas, services, and future
data persistence so later features have an obvious home.

## Background

- The repository currently contains only `LICENSE`, Trellis metadata, and an
  untracked `.gitignore`; there is no application code or existing Python
  compatibility requirement.
- The installed tooling is `uv 0.11.28`.
- Existing backend Trellis specs are still template placeholders, so this task
  establishes the first concrete backend convention without rewriting the
  bootstrap-spec task.
- The existing `.gitignore` intentionally excludes local agent/Trellis files
  and must retain those entries.

## Requirements

### R1: uv-managed Python project

- Initialize project metadata with `uv`.
- Pin the development interpreter to Python 3.13 in `.python-version`.
- Declare runtime and development dependencies in `pyproject.toml`.
- Commit `uv.lock`; do not ignore it.
- A fresh `uv sync --dev` must create the local `.venv` and install the project.

### R2: Layered FastAPI application

- Use a `src/inspire_flow_backend/` package layout.
- Keep HTTP routing under `api/`, runtime settings under `core/`, transport
  models under `schemas/`, business behavior under `services/`, and future
  persistence concerns under `data/`.
- Expose both an application factory and the conventional module-level
  `app` object from `inspire_flow_backend.main`.
- Mount application endpoints beneath a configurable `/api/v1` prefix.

### R3: Observable starter endpoint

- Provide `GET /api/v1/health`.
- Return HTTP 200 and the JSON contract:
  `{"status": "ok", "service": "Inspire Flow Backend", "environment": "development"}`.
- Describe the response with a Pydantic schema and generate it through the
  service layer rather than assembling the payload in the route.

### R4: Environment-based configuration

- Load settings with `pydantic-settings`.
- Support `APP_NAME`, `APP_ENVIRONMENT`, `APP_DEBUG`, and
  `APP_API_V1_PREFIX` environment variables.
- Ignore local `.env` variants while tracking a safe `.env.example`.

### R5: Development quality and documentation

- Add pytest integration coverage for settings and the health endpoint.
- Configure Ruff for linting, import sorting, modernization, and formatting.
- Document setup, local development, endpoint usage, checks, and the directory
  responsibilities in `README.md`.

### R6: Repository hygiene

- Expand `.gitignore` for Python bytecode, build products, local virtual
  environments, caches, coverage output, secrets, logs, and common editor/OS
  files.
- Preserve the existing `.agents/`, `.codex/`, `.code/`, `.trellis/`,
  `AGENTS.md`, and `.DS_Store` ignore behavior.

## Acceptance Criteria

- [x] `uv sync --dev` succeeds and creates a Python 3.13 `.venv`.
- [x] `uv run pytest` passes tests for environment overrides and the health
      endpoint response contract.
- [x] `uv run ruff check .` passes.
- [x] `uv run ruff format --check .` passes.
- [x] Importing `inspire_flow_backend.main:app` succeeds.
- [x] An in-process request to `/api/v1/health` returns the exact R3 contract.
- [x] FastAPI OpenAPI output contains `/api/v1/health`.
- [x] `uv.lock` and `.env.example` are trackable, while `.venv`, `.env`, Python
      caches, and test/lint caches are ignored.
- [x] The README explains every top-level application layer and the commands
      needed to install, run, and verify the project.

## Out of Scope

- Database engine selection, ORM models, migrations, and repository
  implementations.
- Product/business endpoints beyond health checking.
- Authentication, authorization, CORS policy, background jobs, and external
  integrations.
- Containers, deployment manifests, and CI/CD configuration.
- Rewriting the separate `00-bootstrap-guidelines` Trellis task.

## Technical Notes

- Python 3.13 is chosen as a mature runtime baseline while keeping
  `requires-python = ">=3.13"` forward-compatible.
- The application package is named `inspire_flow_backend` to avoid a generic
  import name such as `app`.
- The persistence packages are intentionally structural only until a database
  is selected; no fake repository behavior will be introduced.
