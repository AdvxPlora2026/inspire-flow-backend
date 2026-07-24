# SenseVoice metadata evidence

## Repository behavior

- `TranscriptionJobPublic` currently returns `text`, `detected_language`, and
  `duration_seconds` but no emotion or event fields.
- `SenseVoiceEngine.transcribe()` passes raw model text through
  `rich_transcription_postprocess()`. This removes control tokens but converts
  known emotion and event tags into emoji, so structured information is lost.
- `transcription_jobs.transcript_ciphertext` encrypts transcript text.
  `detected_language` and duration remain typed scalar columns.
- Celery payloads contain only `job_id`; the worker stores durable results in
  SQLite.

## Installed SenseVoice/FunASR behavior

FunASR 1.3.27 defines:

```text
emotions:
  HAPPY SAD ANGRY NEUTRAL FEARFUL DISGUSTED SURPRISED EMO_UNKNOWN

events:
  BGM Speech Applause Laughter Cry Sneeze Breath Cough
  Sing Speech_Noise Event_UNK

languages:
  zh en yue ja ko nospeech
```

The installed postprocessor replaces control tokens through emoji dictionaries
and does not return a typed analysis object.

A real SenseVoice-Small MPS smoke test returned:

```text
raw=<|zh|><|HAPPY|><|Speech|><|withitn|>
    今天真是太开心了，我们终于完成了这个作品。

postprocessed=今天真是太开心了，我们终于完成了这个作品。😊
result keys=['key', 'text']
```

Therefore metadata must be parsed from raw text before postprocessing. The
model result does not provide emotion confidence or timestamp data, so those
fields cannot be supported honestly in this change.

## Chosen MVP

Return aggregate job-level arrays:

```json
{
  "text": "今天真是太开心了，我们终于完成了这个作品。",
  "detected_language": "zh",
  "emotions": ["happy"],
  "audio_events": ["speech"],
  "duration_seconds": 4.3
}
```

Arrays preserve unique labels in first-seen order. Unknown tags are stripped
and ignored. This provides stable JSON without pretending that SenseVoice
supplies scores or timestamps.
