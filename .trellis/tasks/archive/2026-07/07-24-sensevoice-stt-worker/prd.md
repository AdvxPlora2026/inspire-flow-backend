# Isolate SenseVoice STT worker

## Goal

Add a uv dependency group named `stt` and deploy SenseVoice-Small as an
independently supervised speech-to-text service. A model load or inference
failure must not terminate or block the main InspireFlow API process.

## Requirements

- Keep the existing backend API prefix at `/api/v1`.
- Declare the optional STT runtime in the root uv project as a dependency
  group named `stt`; the normal backend environment must not install or import
  the heavy model runtime.
- Run SenseVoice-Small only in a Celery prefork child process isolated from the
  main FastAPI process and the Celery worker's parent process.
- Load the model once in the STT service and expose readiness separately from
  process liveness.
- Route STT jobs through a dedicated Celery `stt` queue. Run one prefork child
  by default; the Celery worker parent must replace an unexpectedly exited,
  timed-out, or recycled child.
- Keep blocking model inference off the STT service event loop and limit
  concurrent inference so that overload does not exhaust the host.
- Make model identifier, device, language, ITN, request limits, timeouts, and
  model-cache location configurable through environment variables.
- Do not download or load the real model during the normal unit-test suite.
- Do not persist uploaded audio unless a later product requirement explicitly
  opts into storage.
- Preserve failure isolation: an unavailable STT service may make
  transcription unavailable, but the user, agent, health, and other API
  features must continue serving.

## Acceptance Criteria

- [x] `pyproject.toml` contains a resolvable `[dependency-groups].stt` group and
      `uv.lock` records it.
- [x] Starting the normal backend without the `stt` group does not require
      FunASR, PyTorch, Torchaudio, or a downloaded SenseVoice model.
- [x] STT runs under a dedicated Celery worker parent; killing its prefork
      child causes that child to be replaced without restarting the backend.
- [x] Audio bytes are not embedded in broker messages; tasks contain only a
      job identifier and a controlled temporary-file reference.
- [x] The public API submits STT work asynchronously and returns a job ID
      without waiting for model inference.
- [x] Killing or crashing the STT process leaves `/api/v1/health` and all
      unrelated backend routes available.
- [x] The STT service has liveness and readiness checks; readiness remains
      false until model loading succeeds.
- [x] Inference concurrency, upload size, audio duration, and upstream
      timeouts are bounded and configurable.
- [x] Unit and integration tests cover success, invalid input, model-not-ready,
      timeout, and worker-unavailable behavior using a fake inference engine.
- [x] Deployment and local-development documentation explains how to install
      the `stt` group, start both services, locate the model cache, and verify
      crash recovery.

## Confirmed Decisions

- The deployment must not require Docker, Docker Compose, or systemd.
- Use Celery as the master/worker task layer: FastAPI is a producer, while a
  dedicated Celery worker parent supervises the STT prefork child.
- Default to one STT worker so that one model copy is loaded. More workers may
  be configured only when the host has enough CPU/GPU memory.
- Use asynchronous transcription jobs rather than holding an HTTP request open
  for model inference.
- Expose the job submission and status/result API under the existing
  `/api/v1` prefix.
- Use Redis as the Celery broker. Store durable user-visible transcription job
  state and results in the existing SQLite database rather than treating Redis
  as the source of truth.
- Support `cpu`, `cuda`, and `mps` device modes through configuration, plus an
  `auto` mode that prefers CUDA, then MPS, then CPU.
- Validate the selected accelerator in the STT child during startup. Explicit
  unavailable device selections must fail readiness with a clear diagnostic;
  automatic selection may fall back to CPU.
- Treat MPS support as capability-tested rather than assumed. PyTorch documents
  the backend, but SenseVoice/FunASR only documents CPU and CUDA deployment, so
  a real MPS smoke test and controlled CPU fallback are required.
- Default to a five-minute maximum audio duration and a 64 MiB upload limit.
  Both limits must be configurable, and the worker must reject decoded audio
  beyond the duration limit before inference.

## Confirmed Scope

- Accept authenticated multipart audio submissions under `/api/v1`.
- Return asynchronous job state and results rather than streaming partial
  transcripts.
- Support common creator/browser inputs including WAV, MP3, M4A/MP4 audio,
  FLAC, OGG/Opus, and WebM/Opus when the installed decoder supports them.
- Raw audio is temporary and is removed after a terminal job outcome.
- Transcript text is encrypted at rest with the existing context cipher and is
  never stored in Redis or Celery result metadata.
