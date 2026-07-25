# Asynchronous Speech-to-Text Worker

> Executable contracts for the Replicate Whisper provider, Celery worker,
> storage, process isolation, and deployment.

## Scenario: Replicate Whisper Transcription

### 1. Scope / Trigger

- Trigger: changing transcription endpoints, audio validation, Celery task
  behavior, provider configuration, readiness, or `transcription_jobs`.
- FastAPI, Redis, the Celery parent/child, SQLite, local spool, Hack Club proxy,
  and Replicate must preserve one bounded and user-scoped job contract.

### 2. Signatures

```text
POST /api/v1/transcriptions      -> 202 TranscriptionJobPublic
GET  /api/v1/transcriptions/{id} -> 200 TranscriptionJobPublic
```

Submission fields remain `file`, `language` (`auto|zh|yue|en|ja|ko`), and
`use_itn`. Celery tasks remain `stt.transcribe(job_id)` and `stt.warmup()`.

### 3. Contracts

- Redis contains only `job_id`; never audio, transcript, credentials, remote
  IDs, filenames, or paths.
- The API stages bounded audio under `APP_STT_SPOOL_DIR`. The worker validates
  decoded duration before provider I/O and removes the file on every terminal
  path.
- SQLite is the source of truth. Transcript and version-1 analysis JSON are
  encrypted with `ContextCipher`.
- The provider client is process-global and lazily constructed in the prefork
  child. FastAPI and the Celery parent perform no provider request.
- Audio is uploaded through `{base_url}/files`; prediction creation uses
  `{base_url}/predictions` with the exact configured version. Polling builds a
  relative `{base_url}/predictions/{id}` path and never follows an upstream
  absolute URL that bypasses Hack Club.
- Model input is `task=transcribe`, mapped full language name, `batch_size=24`,
  `timestamp=chunk`, and `diarise_audio=false`. Do not send `use_itn`, an HF
  token, translation, webhook, or invented parameter.
- `auto` maps to `None`; `zh/yue/en/ja/ko` map to
  `chinese/cantonese/english/japanese/korean`.
- Successful new jobs store empty `emotions` and `audio_events` arrays because
  Whisper does not provide SenseVoice classifications. Pre-success fields and
  legacy successful rows with no analysis remain nullable.
- Provider chunks, timestamps, diarization, confidence, prediction IDs, file
  IDs, logs, and error bodies are not persisted or exposed.
- Defaults are 64 MiB, 300 decoded seconds, 70-second request timeout,
  540-second prediction timeout, one-second poll interval, 600/660-second
  Celery soft/hard limits, three attempts, and 30-second readiness TTL.
- Prediction timeout must be lower than the Celery soft limit.
- Readiness begins only after the child constructs a configured client. It
  proves local configuration, not remote provider availability.

Environment:

| Key | Default |
| --- | --- |
| `APP_STT_ENABLED` | `false` |
| `APP_STT_BROKER_URL` | `redis://127.0.0.1:6379/0` |
| `APP_STT_QUEUE` | `stt` |
| `APP_STT_SPOOL_DIR` | `.inspireflow-stt-spool` |
| `APP_STT_API_KEY` | blank secret |
| `APP_STT_BASE_URL` | `https://ai.hackclub.com/proxy/v1/replicate` |
| `APP_STT_MODEL` | pinned `vaibhavs10/incredibly-fast-whisper:3ab86df6...` |
| `APP_STT_REQUEST_TIMEOUT_SECONDS` | `70` |
| `APP_STT_PREDICTION_TIMEOUT_SECONDS` | `540` |
| `APP_STT_POLL_INTERVAL_SECONDS` | `1` |
| `APP_STT_MAX_UPLOAD_MIB` | `64` |
| `APP_STT_MAX_DURATION_SECONDS` | `300` |
| `APP_STT_SOFT_TIME_LIMIT_SECONDS` | `600` |
| `APP_STT_HARD_TIME_LIMIT_SECONDS` | `660` |
| `APP_STT_MAX_ATTEMPTS` | `3` |
| `APP_STT_READY_TTL_SECONDS` | `30` |

### 4. Validation And Error Matrix

| Condition | Required behavior |
| --- | --- |
| STT disabled or publish unavailable | `503 stt_unavailable`; compensate staged file/job |
| Upload exceeds configured bytes | `413 audio_too_large`; remove partial file |
| Unsupported declared media | `415 unsupported_audio_type` |
| Unknown or foreign job | `404 transcription_not_found` |
| Decode failure | terminal `invalid_audio` before provider I/O |
| Duration over limit | terminal `audio_too_long` before provider I/O |
| Missing key, HTTP/auth/rate-limit/timeout/provider/payload failure | terminal `stt_model_unavailable` |
| Prediction deadline | best-effort cancel, stable failure, local cleanup |
| Existing successful row without analysis | return nullable metadata |
| Pool child exits | parent replaces child; API remains available |
| Hard task timeout | idempotent retry up to attempt bound |

Public failures never contain native exceptions, response bodies, broker URLs,
credentials, transcript text, filenames, remote IDs, or paths.

### 5. Tests Required

- Settings: provider defaults, blank-secret normalization, and timeout order.
- Engine: language mapping, local validation before network, multipart upload,
  exact fixed-version input, immediate and polled success, proxy-only polling,
  deadline cancellation, remote cleanup, malformed output, and safe errors.
- Worker: lazy child construction, readiness TTL, idempotency, encrypted empty
  analysis arrays, retry bounds, and local spool cleanup.
- API/persistence: unchanged authentication, ownership, status, compensation,
  encryption, nullable legacy rows, and error contracts.
- Stable tests use `httpx.MockTransport` or fake engines; no real key, network,
  Redis process, or paid prediction.
- Secret scan must reject long real bearer values in tracked files and task
  artifacts.

### 6. Good / Base / Bad Cases

- Good: FastAPI commits a bounded queued job, publishes only its UUID, and
  returns `202` without waiting for upload or inference at the provider.
- Base: one prefork child validates duration, uploads the staged file through
  Hack Club, waits or polls the pinned prediction, encrypts text plus empty
  compatibility arrays, and removes local and remote temporary files.
- Bad: send base64 audio through Redis or prediction JSON, follow an absolute
  `api.replicate.com` polling URL with the Hack Club key, expose an upstream
  error body, or start the prediction deadline only after `Prefer: wait`
  returns.

### 7. Wrong vs Correct

#### Wrong

```python
prediction_url = prediction["urls"]["get"]
response = client.get(prediction_url)
```

The provider URL can bypass the configured Hack Club proxy and send its bearer
key to the wrong origin.

#### Correct

```python
prediction_id = prediction["id"]
response = client.get(f"predictions/{prediction_id}")
```

The configured base URL remains the only provider origin.

#### Wrong

```python
prediction = create_prediction()
deadline = monotonic() + timeout
```

This grants a second full timeout after the synchronous wait.

#### Correct

```python
deadline = monotonic() + timeout
prediction = create_prediction()
prediction = wait_for_prediction(prediction, deadline=deadline)
```

The configured prediction timeout covers initial creation plus later polling.

### Forbidden Patterns

- Put audio or transcript data in Redis.
- Base64-embed large audio in prediction JSON.
- Follow provider-returned absolute polling URLs.
- Persist or log provider response bodies, prediction IDs, file IDs, or keys.
- Hold a database transaction during upload, prediction, or polling.
- Reintroduce FunASR, Torch, device selection, or local model-cache settings.
- Expose timestamps, confidence, diarization, emotions, or events not produced
  by the selected integration.
