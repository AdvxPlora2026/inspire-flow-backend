# SenseVoice STT worker design

## Summary

Add authenticated, asynchronous speech-to-text jobs to the existing `/api/v1`
API. FastAPI stages bounded audio uploads and publishes small Celery messages
through Redis. A dedicated Celery prefork child lazily loads SenseVoice-Small
and performs inference. SQLite remains the durable source of truth for
user-visible job state and results.

The main API, Celery worker parent, and STT pool child are separate operating
system processes:

```text
client
  |
  | POST /api/v1/transcriptions (multipart)
  v
FastAPI process ---- SQLite transcription_jobs
  |
  | Celery message: {job_id}; no audio bytes
  v
Redis broker
  |
  v
Celery worker parent (queue=stt, prefork, concurrency=1)
  |
  v
STT pool child ---- staged audio file ---- SenseVoice-Small
```

A native model crash or Celery hard timeout may terminate the pool child. The
Celery worker parent replaces that child while the FastAPI process continues
serving unrelated requests. If the Celery worker parent itself exits, the API
continues serving and queued jobs remain pending, but restarting that parent
still requires an operator because Docker, systemd, and other external process
supervision are explicitly out of scope.

## Process and dependency boundaries

### Main API environment

Core project dependencies gain:

- `celery[redis]` for publishing jobs and shared task contracts.
- `python-multipart` for streaming multipart uploads.

The main API must not import `funasr`, `torch`, `torchaudio`, ModelScope, or the
concrete SenseVoice engine. Merely importing the FastAPI application must work
after a normal `uv sync` that omits the `stt` group.

### STT environment

`[dependency-groups].stt` owns FunASR, SenseVoice model-download support,
PyTorch, Torchaudio, and required audio decoding packages. Torch and Torchaudio
must be pinned to a binary-compatible release pair with Python 3.13 wheels.
Resolution alone is insufficient; implementation must verify imports and
perform a short real inference smoke test.

Use a second uv environment in documentation to keep native model packages out
of the ordinary backend environment:

```bash
UV_PROJECT_ENVIRONMENT=.venv-stt uv sync --locked --group stt --no-dev
UV_PROJECT_ENVIRONMENT=.venv-stt uv run --group stt --no-dev \
  celery -A inspire_flow_backend.workers.celery_app:celery_app worker \
  --queues stt --pool prefork --concurrency 1
```

`.venv-stt/`, the model cache, and the audio spool directory are ignored by
Git.

## Package layout

```text
src/inspire_flow_backend/
├── api/routes/transcriptions.py
├── core/config.py
├── core/errors.py
├── data/models/transcription_job.py
├── data/repositories/transcriptions.py
├── schemas/transcriptions.py
├── services/transcriptions.py
└── workers/
    ├── celery_app.py
    ├── stt_engine.py
    └── stt_tasks.py
```

- Route: HTTP/authentication wiring, multipart streaming, status and headers.
- Schema: request options, job state, public result, safe error contract.
- Service: transaction ownership, user scoping, file lifecycle, enqueue
  compensation, state transitions.
- Repository: SQLAlchemy reads/mutations without commits.
- `celery_app.py`: lightweight Celery configuration; never imports model code.
- `stt_tasks.py`: idempotent task orchestration and lazy engine acquisition.
- `stt_engine.py`: the only module allowed to import FunASR/PyTorch.

## Configuration

Add `APP_STT_*` settings with safe local defaults:

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_STT_ENABLED` | `false` | Register/enable task submission behavior |
| `APP_STT_BROKER_URL` | `redis://127.0.0.1:6379/0` | Celery broker |
| `APP_STT_QUEUE` | `stt` | Dedicated queue name |
| `APP_STT_SPOOL_DIR` | `.inspireflow-stt-spool` | Temporary audio directory |
| `APP_STT_MODEL_CACHE_DIR` | `.inspireflow-models` | Shared model cache |
| `APP_STT_MODEL` | `FunAudioLLM/SenseVoiceSmall` | Model identifier |
| `APP_STT_DEVICE` | `auto` | `auto`, `cpu`, `cuda`, or `mps` |
| `APP_STT_MAX_UPLOAD_MIB` | `64` | Streaming upload bound |
| `APP_STT_MAX_DURATION_SECONDS` | `300` | Decoded audio bound |
| `APP_STT_SOFT_TIME_LIMIT_SECONDS` | `600` | Cleanup-capable task limit |
| `APP_STT_HARD_TIME_LIMIT_SECONDS` | `660` | Child replacement limit |
| `APP_STT_MAX_ATTEMPTS` | `3` | Worker-loss redelivery bound |
| `APP_STT_READY_TTL_SECONDS` | `30` | Model-ready heartbeat TTL |

The context encryption key and model-provider settings are unrelated and must
not be reused for STT.

## HTTP contract

All transcription resources require the existing bearer authentication.
Resources are user-scoped and cross-user lookups return the same not-found
response as unknown IDs.

### Submit

```text
POST /api/v1/transcriptions
Content-Type: multipart/form-data

file: required
language: auto | zh | yue | en | ja | ko
use_itn: boolean, default true
```

Success:

```text
202 Accepted
Location: /api/v1/transcriptions/{id}
```

The response is a public job document with status `queued`. The route streams
the upload to a server-generated spool path with owner-only permissions and
stops after 64 MiB by default. It never trusts the client filename as a path.

### Read result

```text
GET /api/v1/transcriptions/{id}
```

The response status is one of:

- `queued`
- `running`
- `succeeded`
- `failed`

`text`, `detected_language`, `duration_seconds`, and `completed_at` are present
when available. Failed jobs expose only a stable error code and safe message,
never model traces, local paths, broker URLs, or native exception text.

### Error behavior

| Condition | Behavior |
| --- | --- |
| STT disabled | `503 stt_unavailable` |
| Redis publish unavailable | remove staged file/job and return `503 stt_unavailable` |
| Upload exceeds byte limit | remove partial file and return `413 audio_too_large` |
| Unsupported declared type/extension | `415 unsupported_audio_type` |
| Decoding fails | asynchronous job becomes `failed: invalid_audio` |
| Decoded duration exceeds five minutes | asynchronous job becomes `failed: audio_too_long` |
| Unknown/cross-user job | `404 transcription_not_found` |
| Model unavailable/device incompatible | job becomes `failed: stt_model_unavailable` |

## Persistence

Add `transcription_jobs`:

| Column | Notes |
| --- | --- |
| `id` | UUID primary key |
| `user_id` | users FK, `ON DELETE CASCADE`, indexed |
| `status` | constrained string enum |
| `language` | requested language |
| `use_itn` | requested ITN flag |
| `transcript_ciphertext` | nullable encrypted transcript |
| `detected_language` | nullable |
| `duration_seconds` | nullable numeric |
| `error_code` | nullable stable code |
| `attempt_count` | non-negative integer |
| `created_at`, `updated_at` | aware UTC application types |
| `started_at`, `completed_at` | nullable aware UTC |

Do not persist the original filename, absolute spool path, raw audio, plaintext
transcript, native exception, or model cache path. Encrypt completed transcript
text with the existing `ContextCipher`; decrypt it only after a user-scoped
lookup when building the public response. A job ID deterministically maps to a
validated spool filename inside `APP_STT_SPOOL_DIR`.

The migration is reversible and follows the existing Alembic chain. Because
FastAPI and Celery write the same SQLite file, application SQLite connections
enable WAL mode and a bounded busy timeout while retaining foreign-key
enforcement. Services keep transactions short and never hold a database
transaction during upload, broker I/O, model loading, or inference.

## Task lifecycle and crash recovery

1. FastAPI validates metadata and streams to a temporary `.part` file.
2. It atomically renames the completed file to the job-owned spool name.
3. The service inserts and commits a `queued` job.
4. It publishes task `stt.transcribe` with only `job_id`, using that UUID as
   the Celery task ID.
5. Publish failure compensates by removing the file and job.
6. The task opens its own SQLAlchemy session and atomically moves a nonterminal
   job to `running`, incrementing `attempt_count`.
7. The pool child lazily imports model packages and obtains a process-global
   engine. Model loading is deliberately not performed in
   `worker_process_init`, whose Celery handlers must finish within four
   seconds.
8. The worker decodes and validates duration, runs SenseVoice, stores a safe
   terminal result, commits, and deletes the staged file.
9. With `task_acks_late=true`, `task_reject_on_worker_lost=true`, and
   `worker_prefetch_multiplier=1`, a killed child causes an idempotent
   redelivery. At `APP_STT_MAX_ATTEMPTS`, the task records a terminal failure
   and acknowledges without another inference attempt.
10. Startup cleanup marks stale nonterminal jobs failed when their spool file
    is missing and removes orphaned/expired spool files.

The Celery visibility timeout must exceed the hard task limit so a healthy
five-minute transcription is not delivered twice.

## Model readiness and devices

A small `stt.warmup` task is published when the worker becomes ready. It calls
the same lazy engine accessor used by transcription tasks. After a successful
model load and sample inference, the child writes a short-lived Redis readiness
key and refreshes it from a daemon heartbeat owned by that child. If the child
dies, the key expires.

Device rules:

- `cpu`: require CPU inference.
- `cuda`: require `torch.cuda.is_available()` and fail clearly otherwise.
- `mps`: require `torch.backends.mps.is_available()` plus real model smoke
  inference; fail clearly otherwise.
- `auto`: choose CUDA, then MPS, then CPU. Only `auto` may retry initialization
  once on CPU when an accelerator is unavailable or unsupported.

Torch/device discovery happens only in the pool child. The parent must not call
even CUDA discovery APIs before forking. MPS remains best-effort because
SenseVoice/FunASR does not currently document a compatibility guarantee and
recent PyTorch/macOS combinations have reported availability issues.

## Security and privacy

- Authentication and user-scoped reads are mandatory.
- Generate file paths server-side and reject path traversal.
- Create spool/cache directories with restrictive permissions.
- Do not log audio, transcript text, authorization headers, Redis credentials,
  filenames, or local paths.
- Keep transcript text out of Redis task payloads/results and encrypt it in
  SQLite with the existing context key.
- Validate size while streaming and duration after trusted decoding.
- Remove raw audio on success, failure, publish compensation, and stale cleanup.
- Model downloads should be pinned by model identifier/revision where upstream
  supports it; do not enable arbitrary remote code from request input.

## Testing strategy

Normal tests must not install/import STT native dependencies, download weights,
start Redis, or invoke the network.

- Unit-test state transitions and task idempotency with an injected fake
  engine and fake publisher.
- API-test authentication, user isolation, upload streaming limits,
  `202/Location`, job polling, broker failure compensation, and safe errors.
- Migration-test fresh upgrade/downgrade plus constraints and cascade.
- SQLite-test WAL/busy-timeout behavior without weakening foreign keys.
- Worker contract-test Celery routing, late acknowledgement, prefetch, timeout,
  and concurrency configuration without starting the model.
- Subprocess integration-test killing a fake STT pool child and confirm its
  replacement while `/api/v1/health` stays available.
- Opt-in `stt` smoke commands test imports, device discovery, model warmup, and
  a bundled short fixture. Network/model-cache availability may be required and
  these tests are not part of ordinary `pytest`.

## Rollout and rollback

The migration and API may be deployed before Redis/STT is started, with
`APP_STT_ENABLED=false`; unrelated API behavior is unchanged. Enabling STT
requires Redis, a migrated shared SQLite database, a writable shared spool
directory, and the separate worker command.

Rollback disables STT, drains/stops the worker, removes staged audio, and then
downgrades the migration if job history may be discarded. Removing the uv
group does not affect normal backend installation.
