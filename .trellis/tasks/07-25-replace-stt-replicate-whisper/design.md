# Technical Design

## Architecture

Preserve the existing API, service, database, spool, Celery, and encryption
layers. Replace only the concrete `SttEngine` implementation and provider-
specific configuration/readiness behavior.

```text
FastAPI -> SQLite queued job -> Redis UUID -> Celery child
                                           -> validate local duration
                                           -> Hack Club files upload
                                           -> Replicate prediction/poll
                                           -> encrypted SQLite result
                                           -> delete local spool audio
```

## Provider Boundary

`ReplicateWhisperEngine` owns:

- API-key validation and an `httpx.Client` scoped to the worker child.
- Local decoded-duration validation before network I/O.
- Uploading the staged file through `{base_url}/files`.
- Creating a fixed-version prediction through `{base_url}/predictions`.
- Polling `{base_url}/predictions/{id}` until terminal or configured timeout.
- Mapping public language codes to model language names.
- Validating dynamic provider output into the existing
  `TranscriptionResult` contract.
- Collapsing all provider and payload failures to `ModelUnavailableError`.

The engine retains the `device` attribute for the existing readiness contract,
but reports a provider label such as `replicate` instead of local hardware.

## Configuration

Replace local-model fields with:

- `APP_STT_API_KEY`: optional `SecretStr`; required when constructing the
  enabled worker engine.
- `APP_STT_BASE_URL`: default Hack Club proxy URL.
- `APP_STT_MODEL`: exact requested owner/model/version reference.
- `APP_STT_REQUEST_TIMEOUT_SECONDS`: per-request network timeout.
- `APP_STT_POLL_INTERVAL_SECONDS`: bounded provider polling interval.

Retain queue, spool, upload/duration, Celery time limits, attempts, and
readiness TTL settings. Remove model-cache, hub, Xet, and device settings.

## Data Contracts

- Redis payload remains only `job_id`.
- SQLite schema remains unchanged.
- Requested non-auto language is used as a fallback detected language when
  the provider omits detection metadata. Auto detection remains `null` when
  the provider does not return a recognizable language.
- `use_itn` remains persisted and accepted but is intentionally not sent to
  Whisper.
- Successful new jobs store an encrypted version-1 analysis payload with
  empty `emotions` and `audio_events` arrays, preserving the public successful
  result shape without inventing classifications.
- Provider chunks/timestamps are ignored in this task.

## Failure Mapping

- Local decode failure -> `invalid_audio`.
- Local duration over limit -> `audio_too_long`.
- Missing key, HTTP/auth/rate-limit/upstream failure, polling timeout,
  canceled/failed prediction, malformed upload/prediction/output payload ->
  `stt_model_unavailable`.

No upstream exception text enters public job fields.

## Readiness

Warmup constructs the provider engine in the prefork child and starts the
existing Redis heartbeat. This proves the worker has valid local configuration
and a provider client, but does not spend a prediction to test the remote
model. The doctor changes its label from local `model` readiness to provider
readiness in documentation while retaining its stable JSON shape unless tests
show a compatibility reason to change it.

## Compatibility And Rollback

- No endpoint or migration changes are required.
- Existing queued jobs can be processed by the new worker because the durable
  job contract is provider-neutral.
- Rollback restores the old engine/config/dependency/docs changes; no stored
  data conversion is needed.
