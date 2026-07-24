# SenseVoice STT handoff

InspireFlow accepts authenticated audio uploads, stores an asynchronous job in
SQLite, and sends only the job UUID through Redis. SenseVoice-Small runs in a
Celery prefork child. The ordinary FastAPI process never imports FunASR,
PyTorch, or Torchaudio.

## Runtime shape

```text
FastAPI -> Redis -> Celery worker parent -> SenseVoice pool child
              \-> SQLite job status and encrypted transcript
```

- A pool-child crash or hard timeout causes Celery to replace that child.
- FastAPI keeps serving user, Agent, memory, and health endpoints.
- Celery does not restart its own parent process. Without Docker, systemd, or
  another supervisor, an operator must restart the worker command if that
  parent exits.
- Raw audio is temporary. Terminal success or failure removes it.
- Transcript text is encrypted in SQLite with the existing context cipher.
  Redis never receives audio bytes or transcript text.

## Prerequisites

- Python 3.13 and uv
- A local or remotely reachable Redis server
- `ffmpeg` when formats such as WebM/Opus or M4A cannot be decoded by the local
  SoundFile stack

Redis can run directly in the foreground; Docker and systemd are not required.
For example, after installing Redis with the operating-system package manager:

```bash
redis-server --port 6379
```

## Install

Install the ordinary development environment:

```bash
uv sync --locked --dev
```

Install the STT runtime into its own uv environment:

```bash
UV_PROJECT_ENVIRONMENT=.venv-stt \
  uv sync --locked --group stt --no-dev
```

The `stt` group pins Torch and Torchaudio to the same 2.11 release line. Its
locked Linux packages include CUDA dependencies; macOS uses the Apple Silicon
wheel with CPU and MPS capability where supported.

## Configure

Copy `.env.example` to the ignored `.env` file, then set:

```dotenv
APP_STT_ENABLED=true
APP_STT_BROKER_URL=redis://127.0.0.1:6379/0
APP_STT_MODEL_HUB=hf
APP_STT_HF_DISABLE_XET=true
APP_STT_DEVICE=auto
```

`APP_STT_DEVICE=auto` prefers CUDA, then MPS, then CPU. Explicit `cuda` or
`mps` selection fails visibly when unavailable. Auto mode may fall back to CPU
if model initialization or the first accelerator inference is unsupported.
Standard HTTP model downloads are used by default because they work more
reliably through common local proxies; set `APP_STT_HF_DISABLE_XET=false` to
opt back into Hugging Face Xet downloads.

The default limits are 64 MiB and five minutes. Change
`APP_STT_MAX_UPLOAD_MIB` or `APP_STT_MAX_DURATION_SECONDS` only after checking
host memory and expected queue latency.

The API and worker must use the same:

- `APP_DATABASE_URL`
- `APP_CONTEXT_ENCRYPTION_KEY` or key file
- `APP_STT_BROKER_URL`
- `APP_STT_SPOOL_DIR`

When they run from the repository root, the default relative SQLite, key,
spool, and model-cache paths resolve to the same files.

## Start

Apply the migration:

```bash
uv run alembic upgrade head
```

Start FastAPI in one terminal:

```bash
uv run uvicorn inspire_flow_backend.main:app --reload
```

Start the isolated STT worker in another terminal:

```bash
UV_PROJECT_ENVIRONMENT=.venv-stt \
  uv run --locked --group stt --no-dev \
  celery -A inspire_flow_backend.workers.celery_app:celery_app worker \
  --queues stt \
  --pool prefork \
  --concurrency 1 \
  --loglevel INFO
```

Concurrency defaults to one intentionally: every pool child loads a complete
model copy. The worker queues a warmup task when it connects. First startup may
download model files into `APP_STT_MODEL_CACHE_DIR`.

## Check liveness and readiness

The existing API remains independently checkable:

```bash
curl http://127.0.0.1:8000/api/v1/health
```

Run the STT doctor from the model environment:

```bash
UV_PROJECT_ENVIRONMENT=.venv-stt \
  uv run --locked --group stt --no-dev \
  python -m inspire_flow_backend.workers.stt_doctor
```

The doctor reports:

- `broker`: Redis is reachable.
- `worker`: a Celery worker responds to remote ping.
- `model`: a pool child loaded the model and is refreshing its readiness TTL.
- `status`: `disabled`, `unavailable`, `warming`, or `ready`.

Model readiness is false until loading succeeds. If a pool child dies, its
readiness key expires and the Celery parent starts a replacement child.

## REST usage

Register and log in using the user-system handoff, then keep the returned
bearer token in a shell variable:

```bash
ACCESS_TOKEN='replace-with-login-token'
```

Submit WAV, MP3, M4A/MP4 audio, FLAC, OGG/Opus, or WebM/Opus:

```bash
curl -i \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -F "file=@./voice.wav;type=audio/wav" \
  -F "language=auto" \
  -F "use_itn=true" \
  http://127.0.0.1:8000/api/v1/transcriptions
```

The response is `202 Accepted`, contains a job document, and includes:

```text
Location: /api/v1/transcriptions/<job-id>
```

Poll the user-scoped result:

```bash
curl \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  http://127.0.0.1:8000/api/v1/transcriptions/<job-id>
```

Statuses are `queued`, `running`, `succeeded`, and `failed`. Failed jobs expose
only a stable error code and safe message. They never return native model
exceptions, local paths, broker credentials, or another user's resource.

## Device notes

- CPU is the compatibility baseline.
- CUDA is selected only when `torch.cuda.is_available()` succeeds.
- MPS requires `torch.backends.mps.is_available()` and a real SenseVoice
  inference. PyTorch supports MPS, but FunASR does not currently publish an
  explicit SenseVoice MPS compatibility guarantee.
- Torch/device discovery and model imports occur only in the Celery pool child,
  after prefork. The FastAPI and Celery parent processes do not initialize an
  accelerator.

## Failure recovery

Celery uses late acknowledgement, worker-loss rejection, a prefetch multiplier
of one, and bounded attempts. A killed pool child causes the same idempotent
job to be delivered again. Completed jobs do not run twice.

To verify isolation in a non-production environment:

1. Keep polling `/api/v1/health`.
2. Identify and terminate only the Celery pool child, not the worker parent.
3. Confirm the API health response remains available.
4. Confirm Celery logs a replacement child.
5. Run the STT doctor until it returns `ready` again.
