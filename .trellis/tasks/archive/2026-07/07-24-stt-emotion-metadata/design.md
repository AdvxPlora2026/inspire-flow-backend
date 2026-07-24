# Structured SenseVoice metadata design

## Summary

Extend the existing authenticated asynchronous transcription resource instead
of adding a second endpoint or synchronous model path. The STT child parses raw
SenseVoice control tokens before text postprocessing, then returns a typed
internal result containing clean text, detected language, aggregate emotions,
audio events, and duration. The task stores transcript text and analysis JSON
as separate authenticated ciphertext values in SQLite. The existing polling
route decrypts both only after its user-scoped lookup.

## API contract

Routes remain unchanged:

```text
POST /api/v1/transcriptions      -> 202 TranscriptionJobPublic
GET  /api/v1/transcriptions/{id} -> 200 TranscriptionJobPublic
```

`TranscriptionJobPublic` gains additive fields:

```python
emotions: list[TranscriptionEmotion] | None
audio_events: list[TranscriptionAudioEvent] | None
```

Queued, running, and failed jobs return `null` for both fields. Successful jobs
return arrays, including `[]` when no recognized metadata exists.

Example success body excerpt:

```json
{
  "status": "succeeded",
  "text": "今天真是太开心了，我们终于完成了这个作品。",
  "detected_language": "zh",
  "emotions": ["happy"],
  "audio_events": ["speech"],
  "duration_seconds": 4.3
}
```

No confidence, raw control-token, emoji-analysis, timestamp, or native model
field is exposed.

## Raw output parsing

Introduce a pure parser in the lightweight STT engine module:

```python
def parse_sensevoice_output(raw_text: str) -> ParsedSenseVoiceOutput: ...
```

It recognizes `<|...|>` tokens and produces:

```python
@dataclass(frozen=True, slots=True)
class ParsedSenseVoiceOutput:
    text: str
    detected_language: str | None
    emotions: tuple[TranscriptionEmotion, ...]
    audio_events: tuple[TranscriptionAudioEvent, ...]
```

Rules:

1. Parse before calling any rich postprocessor.
2. Use lowercase public labels defined in project code, not FunASR emoji maps.
3. Use the first recognized language token as `detected_language`.
4. Preserve first-seen order and de-duplicate emotion/event labels.
5. Ignore unknown tags while removing every well-formed `<|...|>` token from
   public text.
6. Leave malformed, non-token angle-bracket text unchanged.
7. Normalize only boundary/segment whitespace needed after tag removal; do not
   rewrite ordinary transcript punctuation.

The parser is project-owned because the installed FunASR helper emits display
emoji rather than a typed metadata contract. The concrete engine still keeps
all heavy imports lazy, but no longer depends on rich postprocessing for the
public transcript.

## Worker and task flow

`TranscriptionResult` gains `emotions` and `audio_events` tuples. The engine
builds that result from the pure parser. The task forwards these values to
`complete_transcription_job()`. Celery messages and the model lifecycle remain
unchanged.

```text
raw model text
  -> parse tags in prefork child
  -> typed TranscriptionResult
  -> encrypt transcript + analysis JSON
  -> commit SQLite
  -> remove staged audio
```

Failures follow existing safe error codes and never persist partial metadata.

## Persistence and migration

Add nullable `analysis_ciphertext TEXT` to `transcription_jobs` in a new
reversible Alembic revision after `20260724_0003`.

Successful analysis plaintext has a versioned internal shape:

```json
{
  "version": 1,
  "emotions": ["happy"],
  "audio_events": ["speech"]
}
```

Serialize with deterministic JSON separators, encrypt with the existing
`ContextCipher`, and store only ciphertext. Existing rows retain `NULL` and
therefore expose `null` metadata without a data backfill. Transcript storage
remains in `transcript_ciphertext`, avoiding a breaking rewrite of existing
encrypted data.

On public reads:

1. Fetch by `(user_id, job_id)`.
2. Decrypt analysis only after the scoped lookup.
3. Validate the internal version and known labels.
4. If ciphertext authentication or internal validation fails, propagate the
   existing context-storage failure behavior rather than returning untrusted
   metadata.

## Compatibility

- Existing endpoints, authentication, response fields, status codes, queue
  names, and job lifecycle remain unchanged.
- The two new response fields are additive.
- Existing successful rows return `null` metadata.
- New workers can process jobs created before or after migration once the
  schema is upgraded.
- Rolling back the new revision removes only `analysis_ciphertext`; existing
  transcript results remain intact.

## Security and privacy

- Emotions can reveal sensitive characteristics, so they are encrypted at
  rest together with audio-event analysis.
- Raw model text and tags are never logged or stored.
- Redis and Celery contain only `job_id`.
- Unknown model tags do not become arbitrary public enum values.
- Authentication and cross-user not-found behavior remain unchanged.

## Rollback

Disable STT submissions if worker/API versions become incompatible. Downgrade
the new migration to remove `analysis_ciphertext`, then roll back code. This
does not affect existing transcript ciphertext or raw-audio lifecycle.
