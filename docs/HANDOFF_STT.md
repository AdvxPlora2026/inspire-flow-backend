# Replicate Whisper STT handoff

InspireFlow accepts authenticated audio uploads, stores an asynchronous job in
SQLite, and sends only the job UUID through Redis. A Celery prefork child calls
the pinned `vaibhavs10/incredibly-fast-whisper` version through the Hack Club
AI Replicate proxy. FastAPI never sends provider requests.

## Runtime shape

```text
FastAPI -> SQLite queued job -> Redis UUID -> Celery pool child
                                           -> local duration validation
                                           -> Hack Club file upload
                                           -> Replicate prediction and polling
                                           -> encrypted SQLite result
                                           -> local spool cleanup
```

- A pool-child crash or hard timeout causes Celery to replace that child.
- FastAPI keeps serving other endpoints when Redis, the worker, or Replicate is
  unavailable.
- Redis never receives audio bytes, transcript text, credentials, filenames,
  or local paths.
- Raw local audio is removed after terminal success or failure.
- Transcript text and the versioned analysis payload are encrypted in SQLite.

## Prerequisites

- Python 3.13 and uv
- A local or remotely reachable Redis server
- A Hack Club AI key with Replicate access
- `ffprobe` (normally installed with ffmpeg) when SoundFile cannot decode the
  submitted container

Install the normal environment; there is no separate native-model group:

```bash
uv sync --locked --dev
```

## Configure

Set these values in the ignored `.env` file or deployment secret manager:

```dotenv
APP_STT_ENABLED=true
APP_STT_BROKER_URL=redis://127.0.0.1:6379/0
APP_STT_API_KEY=replace-with-hack-club-ai-key
APP_STT_BASE_URL=https://ai.hackclub.com/proxy/v1/replicate
APP_STT_MODEL=vaibhavs10/incredibly-fast-whisper:3ab86df6c8f54c11309d4d1f930ac292bad43ace52d10c80d87eb258b3c9f79c
```

Never commit `APP_STT_API_KEY`. The API and worker must use the same database,
context-encryption key, Redis broker, and spool directory.

Provider timing defaults:

- `APP_STT_REQUEST_TIMEOUT_SECONDS=70`: timeout for one HTTP request.
- `APP_STT_PREDICTION_TIMEOUT_SECONDS=540`: total prediction deadline.
- `APP_STT_POLL_INTERVAL_SECONDS=1`: polling interval after the initial
  synchronous wait.
- Celery soft and hard limits remain 600 and 660 seconds. The prediction
  timeout must be below the soft limit so failure state and cleanup can finish.

The upload and decoded-duration defaults remain 64 MiB and 300 seconds.

## Start

Apply migrations and start FastAPI:

```bash
uv run alembic upgrade head
uv run uvicorn inspire_flow_backend.main:app --reload
```

Start one dedicated STT worker:

```bash
uv run celery -A inspire_flow_backend.workers.celery_app:celery_app worker \
  --queues stt \
  --pool prefork \
  --concurrency 1 \
  --loglevel INFO
```

Concurrency one remains the operational default to bound provider request
volume and preserve predictable queue behavior. The worker queues `stt.warmup`
when it connects. Warmup constructs the configured provider client without
spending a prediction.

## Readiness

Run:

```bash
uv run python -m inspire_flow_backend.workers.stt_doctor
```

The doctor checks Redis, Celery worker liveness, and the short-lived readiness
heartbeat written after the prefork child constructs the Replicate client. A
`ready` report proves local worker configuration, not that the remote provider
will complete the next paid prediction.

## Provider flow

For each claimed job the child:

1. Decodes local duration before any provider request.
2. Uploads the staged audio to `{APP_STT_BASE_URL}/files`.
3. Posts the exact configured version to
   `{APP_STT_BASE_URL}/predictions` with `Prefer: wait=60`.
4. Polls `{APP_STT_BASE_URL}/predictions/{id}` when the initial response is
   still `starting` or `processing`. Provider-supplied absolute polling URLs
   are ignored so the Hack Club proxy is never bypassed.
5. Cancels on the configured prediction deadline and best-effort deletes the
   temporary remote file.
6. Encrypts the normalized result and deletes the local spool file.

Language mapping is `auto -> None`, `zh -> chinese`, `yue -> cantonese`,
`en -> english`, `ja -> japanese`, and `ko -> korean`. `use_itn` remains in the
public API and durable job for compatibility but is not a Whisper input.

## REST result compatibility

Submission and polling endpoints are unchanged:

```text
POST /api/v1/transcriptions
GET  /api/v1/transcriptions/{job_id}
```

Successful new jobs resemble:

```json
{
  "status": "succeeded",
  "text": "今天我们来测试一下自动字幕。",
  "detected_language": "zh",
  "emotions": [],
  "audio_events": [],
  "duration_seconds": 4.82
}
```

Whisper does not provide the old SenseVoice emotion or audio-event labels, so
the retained fields are empty arrays for new successful jobs. They remain
`null` before success and for legacy successful rows that have no encrypted
analysis payload. This integration does not expose provider timestamps,
diarization, confidence, prediction IDs, remote file IDs, or error bodies.

## Failure recovery

Local decode errors become `invalid_audio`; excessive decoded duration becomes
`audio_too_long`. Missing credentials, authentication failures, rate limits,
transport errors, provider timeouts, canceled/failed predictions, and malformed
provider payloads become `stt_model_unavailable` without upstream detail.

Celery still uses late acknowledgement, worker-loss rejection, prefetch one,
and bounded attempts. Completed jobs remain idempotent, and every terminal path
removes the local staged audio.
