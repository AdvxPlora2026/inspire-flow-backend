# Return SenseVoice emotion metadata

## Goal

Extend the authenticated speech-to-text API so a caller can poll a completed
job and receive structured SenseVoice analysis including transcript text and
emotion metadata, without weakening the existing asynchronous worker
isolation, user scoping, or encrypted-at-rest result handling.

## Background

- The existing `POST /api/v1/transcriptions` and
  `GET /api/v1/transcriptions/{id}` routes already require bearer
  authentication and enforce user-scoped reads.
- SenseVoice returns control tokens in raw text. A real cached-model smoke
  produced
  `<|zh|><|HAPPY|><|Speech|><|withitn|>...`; FunASR's rich postprocessor
  converts the emotion token to an emoji instead of returning structured
  metadata.
- The current SenseVoice result contains `key` and raw `text`, but no
  confidence score.

## Requirements

- Keep the existing authenticated asynchronous endpoints under `/api/v1`.
- Preserve bearer authentication and return not-found for unknown or
  cross-user job identifiers.
- Parse SenseVoice output into stable JSON fields rather than exposing raw
  model control tokens.
- Return clean transcript `text`, `detected_language`, aggregate `emotions`,
  aggregate `audio_events`, and `duration_seconds` for successful jobs.
- Normalize emotions to lowercase stable labels: `neutral`, `happy`, `sad`,
  `angry`, `fearful`, `disgusted`, and `surprised`.
- Normalize recognized events to lowercase stable labels: `speech`, `bgm`,
  `applause`, `laughter`, `cry`, `sneeze`, `breath`, `cough`, `sing`, and
  `speech_noise`.
- Preserve first-seen order while de-duplicating emotion and event arrays.
- Return `emotions=null` and `audio_events=null` before success; after success,
  return arrays, including empty arrays when the model emits no recognized
  tags.
- Strip recognized and unknown SenseVoice control tokens from public
  transcript text. Do not convert emotion or event tags into emoji inside
  `text`.
- Do not expose or invent confidence scores, segment timestamps, raw tags, or
  model-native payloads.
- Keep raw audio temporary and keep all user-visible transcription metadata
  out of Redis/Celery result payloads.
- Persist emotion and event analysis as encrypted JSON in SQLite and decrypt
  only after a user-scoped lookup, consistent with transcript handling.
- Add API, worker, persistence, and migration tests without loading the real
  model during the normal test suite.
- Retain the five-minute default duration bound and existing CPU/CUDA/MPS
  execution behavior.
- Preserve existing response fields and routes so current clients remain
  source-compatible.

## Acceptance Criteria

- [x] `POST /api/v1/transcriptions` still requires bearer authentication and
      returns `202` with a user-scoped job resource.
- [x] A successful `GET /api/v1/transcriptions/{id}` JSON response includes
      clean transcript `text`, `detected_language`, `emotions`,
      `audio_events`, and `duration_seconds`.
- [x] Raw SenseVoice tags are normalized and are not mixed into transcript
      text or exposed through the API.
- [x] Multiple tags are de-duplicated in first-seen order; missing and unknown
      tags produce safe empty arrays after success.
- [x] Transcript and analysis ciphertext survive process restarts, contain no
      plaintext result values, and remain unavailable to other users.
- [x] Existing clients that consume current transcription fields remain
      compatible.
- [x] Stable tests cover tagged output, output without tags, malformed or
      unknown tags, model failure, authentication, and cross-user isolation.
- [x] A reversible Alembic migration upgrades an existing
      `20260724_0003` database without changing existing transcription rows.
- [x] Full uv, Ruff, pytest, and Alembic quality gates pass.

## Technical Notes

- Use the existing Redis/Celery prefork STT architecture.
- Do not create a second synchronous inference path that could block FastAPI.
- Do not move the existing `/api/v1` prefix.
- Language, emotion, event, and ITN state must be parsed before rich text
  postprocessing. Known emotion labels are neutral, happy, sad, angry,
  fearful, disgusted, and surprised. Known audio events include speech, BGM,
  applause, laughter, crying, sneezing, breathing, coughing, singing, and
  speech noise.

## Out of Scope

- Synchronous transcription requests.
- Per-segment transcripts, timestamps, speakers, or confidence scores.
- Streaming or WebSocket results.
- Changing STT queue topology, duration limits, model selection, or raw-audio
  retention.
