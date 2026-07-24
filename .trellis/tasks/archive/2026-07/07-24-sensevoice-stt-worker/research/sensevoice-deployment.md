# SenseVoice-Small deployment research

Research date: 2026-07-24

## Primary sources

- SenseVoice repository:
  https://github.com/FunAudioLLM/SenseVoice
- SenseVoiceSmall model card:
  https://huggingface.co/FunAudioLLM/SenseVoiceSmall
- SenseVoice current requirements:
  https://raw.githubusercontent.com/FunAudioLLM/SenseVoice/main/requirements.txt
- SenseVoice reference API:
  https://raw.githubusercontent.com/FunAudioLLM/SenseVoice/main/api.py
- SenseVoice reference Compose deployment:
  https://raw.githubusercontent.com/FunAudioLLM/SenseVoice/main/docker-compose.yaml
- SenseVoice reference Dockerfile:
  https://raw.githubusercontent.com/FunAudioLLM/SenseVoice/main/Dockerfile
- FunASR repository and package:
  https://github.com/modelscope/FunASR
  https://pypi.org/project/funasr/
- uv dependency groups:
  https://docs.astral.sh/uv/concepts/projects/dependencies/
- Torchaudio binary compatibility:
  https://docs.pytorch.org/audio/stable/installation.html

## Findings

SenseVoiceSmall is a 234M-parameter multilingual speech-understanding model.
Its documented FunASR integration supports ASR, language identification,
speech emotion recognition, and audio-event detection. The immediate product
scope is speech-to-text only.

The reference API loads the FunASR model when its service process starts.
Putting that import or model initialization in the main InspireFlow FastAPI
lifecycle would couple backend availability to native libraries, model
downloads, memory pressure, and inference failures.

The upstream deployment already demonstrates a separate FastAPI container,
model-cache volume, and `restart: on-failure:5`. This supports using
process/container supervision rather than attempting to recover the model
inside the main backend process.

uv dependency groups are suitable for a local/deployment-only runtime:
`uv sync --group stt` installs it, while the normal backend can omit it. Groups
are resolved together in one lock file, so incompatible Python or native
dependency constraints will still be detected during locking.

The project currently requires Python 3.13. FunASR advertises `Python >=3.7`
but its published classifiers only explicitly list versions through Python
3.12. A resolver experiment on the current project and Python 3.13 found a
candidate set including FunASR 1.3.27, Torch 2.13.0, and Torchaudio 2.11.0.
That result must not be accepted blindly: Torchaudio's official documentation
states that its binary must match the corresponding Torch release. Exact
compatible pins and a real import/model smoke test are required before the
dependency group is finalized.

The upstream requirements currently include `numpy<=1.26.4`, while the
resolver experiment selected NumPy 2.4.6 without that cap. This is another
reason to validate the actual SenseVoice inference path, not only dependency
resolution.

## Architecture constraints

1. The main backend must never import FunASR, Torch, or Torchaudio.
2. STT must have an independent PID managed by a Celery worker parent outside
   the main application.
3. Model readiness must be distinct from process liveness.
4. Blocking inference should run in a bounded executor inside the STT process.
5. Normal tests must inject a fake inference engine and must not download model
   weights.
6. Requests need bounded size, duration, concurrency, and timeout behavior.
7. Temporary audio must be deleted after inference unless storage is explicitly
   requested later.

## Recommended direction

Use Celery as the task middle layer. The main FastAPI process validates and
stages an upload, creates a transcription job, and sends a small message to a
dedicated `stt` queue. The message contains a job ID and controlled file
reference, never the audio bytes. Redis is designed for rapid transport of
small messages; large audio payloads could congest it.

Run the Celery worker with the prefork pool and concurrency one. Initialize the
SenseVoice model from the child-process initialization hook so neither FastAPI
nor the Celery worker parent loads PyTorch/model state. A hard task time limit
terminates and replaces a stuck child; max-tasks-per-child and
max-memory-per-child provide bounded recycling. Task acknowledgement must be
late and worker-loss rejection enabled so an idempotent transcription job can
be redelivered after a child crash.

The FastAPI request returns `202 Accepted` with a job ID. A separate `/api/v1`
status/result endpoint reads job state, so model inference never occupies the
request lifecycle. The worker cleans up staged audio after a terminal result.

Celery supervises its prefork children, but it does not remove the need to
start the Celery worker parent itself. If that parent process exits, the API
remains available and queued jobs remain pending; without systemd, Docker, or
another external process manager, automatic recovery of the parent process
cannot be guaranteed. The requested isolation still holds because the parent
is not embedded in FastAPI.

References:

- https://docs.celeryq.dev/en/stable/userguide/workers.html
- https://docs.celeryq.dev/en/latest/getting-started/backends-and-brokers/index.html

## Device support

The target modes are `cpu`, `cuda`, `mps`, and `auto`. Auto selection should
prefer CUDA, then MPS, then CPU. Explicit device selection should never silently
change devices; it should produce an actionable startup/readiness error.

PyTorch officially exposes `torch.backends.mps.is_available()` and the `mps`
device on supported Apple Silicon/macOS systems:
https://docs.pytorch.org/docs/stable/notes/mps.html

The official SenseVoice and FunASR examples currently document CPU and CUDA
devices but do not state an MPS compatibility guarantee. MPS must therefore be
validated with an actual model-load and inference smoke test on Apple Silicon.
In `auto` mode only, an unsupported MPS operation may trigger one clean worker
restart configured for CPU; it must not create an endless crash loop.
