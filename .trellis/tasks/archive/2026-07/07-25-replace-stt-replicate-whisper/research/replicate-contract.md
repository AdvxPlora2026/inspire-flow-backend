# Replicate Contract Research

## Sources

- Hack Club guide: <https://docs.ai.hackclub.com/guide/replicate.md>
- Replicate HTTP reference: <https://replicate.com/docs/reference/http.md>
- Requested model API:
  <https://replicate.com/vaibhavs10/incredibly-fast-whisper/versions/3ab86df6c8f54c11309d4d1f930ac292bad43ace52d10c80d87eb258b3c9f79c/api>
- Replicate file inputs:
  <https://replicate.com/docs/topics/predictions/input-files.md>

## Confirmed API Shape

- Base URL: `https://ai.hackclub.com/proxy/v1/replicate`.
- Authentication: `Authorization: Bearer <Hack Club AI key>`.
- Fixed-version prediction: `POST {base_url}/predictions` with JSON fields
  `version` and `input`.
- `Prefer: wait=60` may return a terminal prediction or a non-terminal
  `starting`/`processing` prediction. Non-terminal responses require polling
  `GET {base_url}/predictions/{id}`.
- Non-official models require the exact version ID or
  `owner/model:version-id`; this task uses the exact requested reference.
- Local files should be uploaded rather than embedded as large data URIs.
  Replicate's file API returns a temporary URL suitable for the model input.
- Prediction terminal states are `succeeded`, `failed`, and `canceled`.
- Unauthenticated probes on 2026-07-25 returned HTTP 401 from both
  `{base_url}/files` and `{base_url}/predictions`, confirming those proxy
  routes exist without exposing or using the deployment key.

## Requested Model Input

The pinned version accepts:

- `audio`: required file URL.
- `task`: `transcribe` or `translate`; use `transcribe`.
- `language`: `None` for detection or a full language name.
- `batch_size`: integer, default 24.
- `timestamp`: `chunk` or `word`; use `chunk` internally but do not expose
  timestamps in this task.
- `diarise_audio`: boolean; keep false.
- `hf_token`: only needed for diarization and must not be configured here.

The output schema is dynamically typed. Known deployments return an object
containing transcript text and may include chunks and detected-language data.
The integration must validate fields defensively and ignore unsupported
metadata rather than trusting the provider payload.

## Client Decision

Use the existing `httpx` dependency behind a small typed provider boundary.
The Replicate Python client hardcodes request paths beginning with `/v1`, which
does not compose cleanly with Hack Club's path-prefixed proxy base URL. Raw
HTTP also keeps upload, prediction polling, timeout, and response validation
explicit and straightforward to fake in unit tests.

## Security Notes

- The user-provided key is deployment input only. It must not appear in task
  files, source, tests, examples, command history, or documentation.
- Provider errors can include upstream details and must be collapsed to the
  stable internal `ModelUnavailableError` boundary.
- Remote file and prediction identifiers are ephemeral and are not persisted.
