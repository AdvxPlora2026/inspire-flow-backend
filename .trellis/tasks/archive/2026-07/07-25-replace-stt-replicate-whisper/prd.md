# Replace STT with Replicate incredibly-fast-whisper

## Goal

Replace the local SenseVoice/FunASR inference runtime with the fixed Replicate
model version
`vaibhavs10/incredibly-fast-whisper:3ab86df6c8f54c11309d4d1f930ac292bad43ace52d10c80d87eb258b3c9f79c`
through the Hack Club AI Replicate proxy, while preserving the authenticated
asynchronous transcription API and encrypted persistence behavior.

## Background

- The current HTTP contract is `POST /api/v1/transcriptions` followed by
  polling `GET /api/v1/transcriptions/{id}`.
- FastAPI stages bounded audio in a server-owned spool, persists a queued job,
  and publishes only the job UUID to the dedicated Celery queue.
- The Celery child currently loads SenseVoice locally, checks decoded duration,
  encrypts the transcript and analysis in SQLite, and removes staged audio on
  terminal outcomes.
- Hack Club documents the Replicate-compatible base URL as
  `https://ai.hackclub.com/proxy/v1/replicate` with bearer authentication.
- The requested model accepts an audio file, `transcribe` task, language,
  batch size, timestamp mode, and optional diarization. This task does not add
  timestamps or diarization to the public API.

## Requirements

- Keep the existing transcription endpoints, authentication, job states,
  polling flow, queue isolation, encrypted transcript storage, retry bounds,
  upload bounds, duration bounds, and spool cleanup.
- Replace local FunASR/Torch inference with remote Replicate calls through a
  configurable Hack Club proxy base URL and secret API key.
- Pin the requested owner/model/version as the default model reference.
- Upload staged audio through the Replicate files API instead of embedding
  large audio as a base64 data URI, then submit a synchronous-wait prediction
  and poll it to a terminal state when the initial wait expires.
- Map API languages to Whisper model values: `auto` to `None`, `zh` to
  `chinese`, `yue` to `cantonese`, `en` to `english`, `ja` to `japanese`, and
  `ko` to `korean`.
- Continue accepting `use_itn` for API compatibility. The Whisper integration
  has no equivalent option and must not send an invented model parameter.
- Preserve the successful-response schema for SenseVoice-only metadata:
  `emotions` and `audio_events` are empty arrays after successful Whisper
  transcription because the selected model does not produce those labels.
- Never persist or log the Hack Club key, provider error body, remote upload
  URL, transcript, or local spool path.
- Remove obsolete local-model/device/cache configuration and the heavy `stt`
  dependency group when no longer used.
- Update `.env.example`, README, STT handoff documentation, tests, and the STT
  executable spec to describe the remote provider architecture.
- Stable automated tests must use fake clients/transports and require no API
  key, external network, Redis process, or paid prediction.

## Acceptance Criteria

- [x] Default settings point to the Hack Club Replicate proxy and the exact
      requested model version; the API key is optional while STT is disabled
      and required to construct an enabled worker engine.
- [x] A worker uploads the local audio file, submits the expected prediction
      input, handles both immediate and polled completion, and stores the
      normalized transcript and language through the existing encrypted job
      service.
- [x] Successful Whisper jobs return `emotions: []` and `audio_events: []`;
      queued/running jobs and legacy successful rows retain their existing
      nullable behavior.
- [x] Provider authentication, transport, timeout, malformed response,
      canceled prediction, and failed prediction outcomes become the stable
      public job error `stt_model_unavailable` without secret leakage.
- [x] Invalid local audio and excessive duration are rejected before any
      provider upload or prediction request.
- [x] Existing retry, idempotency, spool cleanup, worker readiness, and API
      ownership tests remain valid after adapting provider-specific details.
- [x] FastAPI and Celery parent imports do not initialize a client or perform
      network I/O.
- [x] The normal project environment contains no FunASR, Torch, Torchaudio,
      ModelScope, Hugging Face model-cache, or device-selection requirement.
- [x] Documentation contains placeholders/environment names only and a secret
      scan finds no real Hack Club API key.
- [x] Focused STT tests and the full lint/test quality gate pass.

## Out Of Scope

- Changing the public transcription endpoints or database schema.
- Adding word/chunk timestamps, speaker diarization, webhooks, translation, or
  direct browser-to-Replicate uploads.
- Persisting Replicate prediction IDs or remote file IDs.
- Adding another STT provider or runtime provider-selection abstraction.
