# Structured SenseVoice metadata implementation plan

## 1. Contract-first parser

- [x] Add typed emotion and audio-event literals to transcription schemas.
- [x] Add a pure raw-token parser and typed parsed-output/result structures.
- [x] Parse language, emotions, events, and clean text before FunASR rich
      postprocessing.
- [x] Preserve first-seen unique labels and safely ignore unknown tokens.
- [x] Test all known labels, repeated/multi-segment tags, missing tags, unknown
      tags, malformed text, and absence of emoji/control tokens in text.

Review gate:

```bash
uv run pytest tests/workers/test_stt_engine.py -q
```

## 2. Encrypted persistence

- [x] Add nullable `analysis_ciphertext` to `TranscriptionJob`.
- [x] Add a reversible `20260724_0004` Alembic migration.
- [x] Serialize a versioned analysis object and encrypt it with
      `ContextCipher` when completing a successful job.
- [x] Decrypt and validate analysis only after a user-scoped lookup.
- [x] Keep existing rows compatible with nullable analysis.
- [x] Test migration upgrade/downgrade, absence of plaintext metadata in raw
      SQLite, encryption authentication, and existing-row compatibility.

Review gate:

```bash
uv run pytest tests/data tests/workers/test_stt_tasks.py -q
```

Rollback point: downgrade `20260724_0004`; transcript ciphertext is retained.

## 3. Authenticated public JSON

- [x] Add nullable `emotions` and `audio_events` to
      `TranscriptionJobPublic`.
- [x] Return `null` until success and typed arrays after successful analysis.
- [x] Keep current POST/GET routes, bearer authentication, `202`, `Location`,
      error envelope, and cross-user not-found behavior.
- [x] Update OpenAPI/API tests with exact JSON assertions for queued,
      succeeded, failed, unauthenticated, and cross-user requests.
- [x] Assert existing fields and clients remain compatible.

Review gate:

```bash
uv run pytest tests/api/test_transcriptions.py -q
```

## 4. Documentation and operational smoke

- [x] Update README and STT handoff with the additive result fields and an
      authenticated submit/poll example.
- [x] Document that values are aggregate labels without confidence or
      timestamps.
- [x] Run an opt-in real cached-model smoke to confirm the parser produces
      clean text, `zh`, `happy`, and `speech` from tagged output.
- [x] Run Alembic against a fresh database and an upgraded
      `20260724_0003` database.
- [x] Run the full warning-strict quality suite.

Final quality gate:

```bash
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run pytest -W error
```

## Risk checks

- Do not expose raw tags or emojis inside transcript `text`.
- Do not infer confidence or segment timing.
- Do not import native model packages in the API or Celery parent.
- Do not store emotion/event plaintext in SQLite, Redis, logs, or task results.
- Do not change the existing `/api/v1` route layout or authentication model.
