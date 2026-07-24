# SenseVoice STT worker implementation plan

## 1. Dependency and configuration foundation

- [x] Add lightweight API-side Celery/Redis and multipart dependencies.
- [x] Add `[dependency-groups].stt` with FunASR/SenseVoice, audio decoding, and
      an exact binary-compatible Torch/Torchaudio pair.
- [x] Lock with uv and verify the normal environment omits native STT packages.
- [x] Add validated `APP_STT_*` settings and safe `.env.example` entries.
- [x] Ignore `.venv-stt`, model cache, and spool artifacts.
- [x] Add unit tests for device/limit/settings validation.

Review gate:

```bash
uv lock --check
uv sync --locked --dev
uv run python -c "import inspire_flow_backend.main"
uv run python -c "import importlib.util; assert importlib.util.find_spec('funasr') is None"
```

The last assertion may use an isolated normal uv environment if the developer's
existing `.venv` already contains exploratory packages.

## 2. Persistence and SQLite concurrency

- [x] Add the `TranscriptionJob` model, model registry import, repository, and
      UTC/status constraints.
- [x] Add service-owned create/read/transition/compensation operations.
- [x] Store transcript text only as authenticated ciphertext and decrypt only
      after a user-scoped lookup.
- [x] Add a reversible Alembic revision.
- [x] Enable SQLite WAL and bounded busy timeout without changing non-SQLite
      behavior or foreign-key enforcement.
- [x] Add migration, repository, transaction, cascade, and concurrent
      connection tests.

Review gate:

```bash
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
uv run pytest tests/data
```

Rollback point: revert the migration/model before adding the public route.

## 3. Public asynchronous API

- [x] Add transcription schemas and stable domain errors.
- [x] Implement authenticated multipart streaming to owner-only `.part` files,
      byte counting, atomic rename, and safe cleanup.
- [x] Add the Celery publisher boundary so tests can inject a fake.
- [x] Implement `POST /api/v1/transcriptions` returning `202` and `Location`.
- [x] Implement user-scoped `GET /api/v1/transcriptions/{id}`.
- [x] Register the router without moving the existing `/api/v1` prefix.
- [x] Test authentication, user isolation, validation, size limit, broker
      outage compensation, result polling, OpenAPI, and absence of path/error
      leakage or plaintext transcript persistence.

Review gate:

```bash
uv run pytest tests/api tests/services
```

Rollback point: disable `APP_STT_ENABLED`; unrelated routes remain available.

## 4. Celery and SenseVoice worker

- [x] Add a lightweight Celery app with a dedicated `stt` route, Redis
      visibility timeout, late acknowledgement, worker-loss rejection,
      prefetch one, and configured soft/hard limits.
- [x] Implement an injected engine protocol and fake engine.
- [x] Implement the concrete SenseVoice engine with imports inside the pool
      child, bounded duration validation, output normalization, and safe error
      mapping.
- [x] Implement `auto/cpu/cuda/mps` discovery and one-time CPU fallback only
      for `auto`.
- [x] Add idempotent transcribe/warmup tasks, attempt bounds, process-global
      lazy model reuse, readiness TTL heartbeat, and terminal file cleanup.
- [x] Ensure neither Celery parent import nor FastAPI import initializes Torch
      or the model.
- [x] Unit-test tasks without native dependencies or Redis.

Review gate:

```bash
uv run pytest tests/workers
uv run ruff check .
uv run ruff format --check .
```

## 5. Operational verification and documentation

- [x] Document installing Redis without requiring Docker/systemd.
- [x] Document the separate normal and `.venv-stt` uv environments.
- [x] Document migrations, environment variables, worker startup, upload/poll
      examples, model cache, health/readiness, and cleanup.
- [x] Add a cheap STT doctor/import command.
- [x] Run an opt-in CPU import and short-audio model smoke test.
- [x] On this Apple Silicon host, run MPS availability and real inference;
      record CPU fallback if upstream support fails.
- [x] Document the locked PyTorch Linux wheel behavior. CUDA capability is
      covered by unit tests; real CUDA inference remains a deployment-host
      check because this Apple Silicon host has no CUDA device.
- [x] Start Redis, API, and a real worker; kill the pool child and
      verify Celery replaces it while `/api/v1/health` remains responsive.
- [x] Run the full quality suite.

Final quality gate:

```bash
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run alembic upgrade head
```

## Out-of-scope follow-ups

- Streaming partial transcripts or WebSocket transcription.
- Audio longer than the configured five-minute default.
- Multiple STT workers per device or distributed object storage.
- Automatic restart of the Celery worker parent without an external process
  manager.
- Long-term raw-audio retention.
