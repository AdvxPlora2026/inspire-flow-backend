# Asynchronous Speech-to-Text Worker

> Executable contracts for the SenseVoice-Small API, Celery worker, storage,
> process isolation, and local deployment.

---

## Scenario: Isolated SenseVoice Transcription

### 1. Scope / Trigger

- Trigger: adding or changing transcription endpoints, audio validation,
  Celery task behavior, model/device configuration, readiness, or the
  `transcription_jobs` schema.
- This is an infrastructure and cross-layer flow. FastAPI, Redis, the Celery
  parent, its prefork child, SQLite, and the temporary spool must keep the same
  job and failure contracts.

### 2. Signatures

HTTP:

```text
POST /api/v1/transcriptions      -> 202 TranscriptionJobPublic
GET  /api/v1/transcriptions/{id} -> 200 TranscriptionJobPublic
```

Submission is authenticated multipart form data:

```text
file: required audio upload
language: auto | zh | yue | en | ja | ko, default auto
use_itn: boolean, default true
```

Worker and diagnostics:

```bash
UV_PROJECT_ENVIRONMENT=.venv-stt uv run --locked --group stt --no-dev \
  celery -A inspire_flow_backend.workers.celery_app:celery_app worker \
  --queues stt --pool prefork --concurrency 1

uv run python -m inspire_flow_backend.workers.stt_doctor
```

Celery tasks:

```python
stt.transcribe(job_id: str) -> None
stt.warmup() -> dict[str, str]
```

Durable table:

```text
transcription_jobs(
  id, user_id, status, language, use_itn, transcript_ciphertext,
  analysis_ciphertext, detected_language, duration_seconds, error_code,
  attempt_count, created_at, updated_at, started_at, completed_at
)
```

### 3. Contracts

- The API runs without the `stt` uv group. API and Celery-parent imports must
  not import FunASR, Torch, Torchaudio, or load a model.
- The `stt` dependency group owns native inference packages. Use a separate
  `.venv-stt` environment so installing the normal backend remains lightweight.
- Redis messages contain only the UUID job identifier. They never contain
  audio bytes, transcript text, a client filename, credentials, or an absolute
  spool path.
- The job UUID maps to a server-owned file beneath `APP_STT_SPOOL_DIR`.
  Uploads stream to an owner-only `.part` file and are atomically renamed only
  after validation.
- SQLite is the source of truth. Transcript text is encrypted with
  `ContextCipher`; aggregate emotion/audio-event analysis is a versioned JSON
  object encrypted into `analysis_ciphertext`. Redis has no result backend and
  never stores user-visible results.
- Job states are `queued`, `running`, `succeeded`, or `failed`. Reads are
  scoped by authenticated `user_id`; a foreign UUID is indistinguishable from
  an unknown UUID.
- Celery uses queue `stt`, prefork, late acknowledgement, worker-loss
  rejection, prefetch one, and one child by default. A child crash must not
  terminate FastAPI or the Celery parent.
- The model is process-global and lazily loaded inside the prefork child.
  Readiness is a short-lived Redis heartbeat written only after model load.
- Raw audio is removed after success, terminal failure, or publish
  compensation. The original filename and local path are never persisted.
- Default bounds are 64 MiB upload size, 300 seconds decoded duration, a
  600-second soft task limit, a 660-second hard limit, and three attempts.
- `APP_STT_DEVICE=auto` chooses CUDA, then MPS, then CPU and may fall back to
  CPU once. Explicit `cuda` or `mps` must fail clearly if unavailable.
- Successful public jobs add `emotions` and `audio_events`. Both are `null`
  before success and typed arrays after success, including empty arrays when
  no known tag is present. Existing successful rows with no analysis remain
  readable and return `null`.
- Parse raw SenseVoice tokens before rich postprocessing. Public `text` is
  plain transcript text without control tokens or display emoji. Emotion and
  event arrays preserve unique known labels in first-seen order.
- SenseVoice does not provide reliable confidence or segment timestamps
  through this integration. Do not invent either field.

Environment:

| Key | Default |
| --- | --- |
| `APP_STT_ENABLED` | `false` |
| `APP_STT_BROKER_URL` | `redis://127.0.0.1:6379/0` |
| `APP_STT_QUEUE` | `stt` |
| `APP_STT_SPOOL_DIR` | `.inspireflow-stt-spool` |
| `APP_STT_MODEL_CACHE_DIR` | `.inspireflow-models` |
| `APP_STT_MODEL` | `FunAudioLLM/SenseVoiceSmall` |
| `APP_STT_MODEL_HUB` | `hf` |
| `APP_STT_HF_DISABLE_XET` | `true` |
| `APP_STT_DEVICE` | `auto` |
| `APP_STT_MAX_UPLOAD_MIB` | `64` |
| `APP_STT_MAX_DURATION_SECONDS` | `300` |
| `APP_STT_SOFT_TIME_LIMIT_SECONDS` | `600` |
| `APP_STT_HARD_TIME_LIMIT_SECONDS` | `660` |
| `APP_STT_MAX_ATTEMPTS` | `3` |
| `APP_STT_READY_TTL_SECONDS` | `30` |

> **Hugging Face download gotcha**: with common local proxies, Xet-backed
> downloads can establish connections while leaving the weight file at zero
> bytes. Standard HTTP is therefore the default. Set
> `APP_STT_HF_DISABLE_XET=false` only when Xet is known to work.

### 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| STT disabled or publish unavailable | `503 stt_unavailable`; compensate the staged file and job |
| Upload exceeds configured bytes | `413 audio_too_large`; remove the partial file |
| Unsupported declared media type/extension | `415 unsupported_audio_type` |
| Unknown or foreign job | `404 transcription_not_found` |
| Decode failure | terminal `failed` with `invalid_audio` |
| Decoded duration exceeds the configured limit | terminal `failed` with `audio_too_long` before inference |
| Model/device initialization failure | terminal `failed` with `stt_model_unavailable` |
| Known emotion/event tags | normalize to stable lowercase labels |
| Unknown well-formed SenseVoice tag | remove it from text and omit it from metadata |
| Existing successful row without analysis | return `emotions=null`, `audio_events=null` |
| Invalid encrypted analysis shape | `503 context_storage_unavailable`; do not return untrusted fields |
| Pool child exits | Celery parent replaces it; API health remains available |
| Worker parent exits | API remains available; an operator must restart the worker |
| Hard task timeout | child is replaced and the idempotent job is retried up to the attempt bound |

Public errors never contain native exceptions, broker URLs, credentials,
client filenames, transcript text, or local paths.

### 5. Good / Base / Bad Cases

- Good: FastAPI streams a bounded upload, commits a queued UUID, publishes
  only that UUID, and returns `202` without waiting for inference.
- Base: a single prefork child loads one cached model, records encrypted text
  and analysis in SQLite, removes the audio, and polling returns clean text,
  detected language, aggregate emotions, and audio events only to its owner.
- Bad: import Torch in the API or Celery parent, put audio in Redis, hold a
  database transaction during inference, run multiple model children by
  default, trust the upload filename as a path, expose raw SenseVoice tags, or
  synthesize confidence values.

### 6. Tests Required

- Settings: parse every `APP_STT_*` setting and reject hard limits not greater
  than soft limits.
- Import boundary: normal `uv sync --locked --dev` imports the FastAPI app
  while `funasr` and `torch` remain absent.
- API: assert authentication, `202` plus `Location`, exact error codes,
  user isolation, upload bounds, publish compensation, and no path leakage.
- Persistence: migrate a fresh file to head, downgrade and upgrade the STT
  revision, assert the user cascade, WAL mode, foreign keys, and busy timeout.
- Worker: use fake engines to assert lazy imports, device selection, CPU
  fallback, duration-before-inference, idempotency, retry bounds, encryption,
  cleanup, readiness expiry, payload containing only `job_id`, every known
  emotion/event mapping, first-seen de-duplication, and unknown-tag removal.
- Persistence/API: assert analysis is absent as plaintext, old rows return
  null metadata, new rows decrypt to typed arrays, and cross-user reads remain
  not-found.
- Worker process: in an isolated Python subprocess, import `stt_tasks` and run
  `configure_mappers()` so unit-test import order cannot mask a missing ORM
  model registration.
- Real opt-in smoke: import the locked `stt` group and transcribe short audio
  on the selected host device. This test is not part of stable unit tests.
- Process smoke: start Redis, Uvicorn, and one prefork worker; terminate the
  resolved pool-child PID; assert a different child PID appears while
  `/api/v1/health` remains HTTP 200, then warm the replacement and assert
  doctor reports its PID as ready.

### 7. Wrong vs Correct

#### Wrong

```python
celery_app.send_task(
    "stt.transcribe",
    kwargs={"audio": upload_bytes, "filename": upload.filename},
)
```

This expands Redis into audio storage, trusts user metadata, and makes retries
carry sensitive bulk data.

#### Correct

```python
celery_app.send_task(
    "stt.transcribe",
    args=[str(job_id)],
    task_id=str(job_id),
    queue=settings.stt_queue,
)
```

The child resolves the server-owned spool file from the validated UUID and
stores only encrypted results through the service layer.

#### Wrong

```python
text = rich_transcription_postprocess(raw_text)
return {"text": text, "confidence": 0.9}
```

This mixes emotion emoji into transcript text and fabricates a score the model
did not return.

#### Correct

```python
parsed = parse_sensevoice_output(raw_text)
return TranscriptionResult(
    text=parsed.text,
    detected_language=parsed.detected_language,
    emotions=parsed.emotions,
    audio_events=parsed.audio_events,
    duration_seconds=duration,
)
```

The worker owns raw-token parsing and passes a typed result to encrypted
persistence.
