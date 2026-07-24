# Error Handling

> How errors are handled in this project.

---

## Overview

Application and request-validation failures use one JSON envelope. Services
raise domain-specific `ApplicationError` subclasses; they do not construct
FastAPI responses. `register_error_handlers()` installs the HTTP boundary once
when the application is created.

---

## Scenario: Stable API Error Responses

### 1. Scope / Trigger

- Trigger: adding an application failure, validation rule, authenticated
  endpoint, or framework-level HTTP failure.
- The caller-visible `error.code`, status, and required headers are API
  contracts. Tests must lock them down.

### 2. Signatures

```python
class ApplicationError(Exception):
    status_code: int
    code: str
    message: str
    headers: dict[str, str] | None


def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, object]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse: ...


def register_error_handlers(application: FastAPI) -> None: ...
```

### 3. Contracts

Every handled error has this outer shape:

```json
{
  "error": {
    "code": "machine_readable_code",
    "message": "Safe human-readable message"
  }
}
```

Validation errors may add `error.details`. Each detail contains only
`location`, `message`, and `type`. Never copy Pydantic's rejected `input` or
`ctx` values because they may contain a password or another secret.

### 4. Validation & Error Matrix

| Condition | Status | Code | Required header |
| --- | --- | --- | --- |
| Nickname uniqueness conflict | `409` | `nickname_conflict` | None |
| Unknown nickname or wrong password | `401` | `invalid_credentials` | None |
| Invalid bearer session | `401` | `invalid_session` | `WWW-Authenticate: Bearer` |
| Foreign or unknown conversation | `404` | `conversation_not_found` | None |
| Foreign or unknown memory | `404` | `memory_not_found` | None |
| Archived conversation turn | `409` | `conversation_archived` | None |
| Concurrent conversation turn | `409` | `conversation_busy` | None |
| Credential-shaped memory | `422` | `credential_memory_forbidden` | None |
| Request validation failure | `422` | `validation_error` | None |
| Expected Agent/model failure | `502` | `agent_run_failed` | None |
| Missing model configuration | `503` | `agent_unavailable` | None |
| Missing/invalid context key | `503` | `context_storage_unavailable` | None |
| STT disabled or broker unavailable | `503` | `stt_unavailable` | None |
| Oversized audio upload | `413` | `audio_too_large` | None |
| Unsupported audio declaration | `415` | `unsupported_audio_type` | None |
| Foreign or unknown transcription | `404` | `transcription_not_found` | None |
| Other Starlette `HTTPException` | Exception status | `http_error` | Preserve exception headers |

Unknown-nickname and wrong-password login attempts must return the same body.
Missing, malformed, expired, unknown, and revoked bearer tokens must share the
same invalid-session response.

### 5. Good / Base / Bad Cases

- Good: a service catches an expected database exception, rolls back, and
  raises a domain error; the central handler serializes it.
- Base: request validation emits safe field locations and error types without
  echoing the submitted value.
- Bad: a route catches `Exception`, returns `str(error)`, reveals whether a
  nickname exists during login, or omits `WWW-Authenticate` on a `401`
  session response.

### 6. Tests Required

- Assert the exact status and `error.code` for every stable domain error.
- Compare unknown-user and wrong-password login response bodies for equality.
- Put a distinctive value in a rejected password and assert it is absent from
  the serialized response.
- Cover missing, wrong-scheme, empty, unknown, expired, and revoked bearer
  credentials; assert `WWW-Authenticate: Bearer`.
- Verify framework-generated `404` responses still use the outer error
  envelope when that contract changes.

### 7. Wrong vs Correct

#### Wrong

```python
except IntegrityError as error:
    return JSONResponse(status_code=409, content={"detail": str(error)})
```

This leaks database detail and invents a second response shape.

#### Correct

```python
except IntegrityError as error:
    db.rollback()
    raise NicknameConflictError from error
```

The service keeps the rollback close to the failed transaction and lets the
shared handler produce the stable envelope.

---

## Error Types

- `NicknameConflictError`: normalized nickname uniqueness failure.
- `InvalidCredentialsError`: generic login failure.
- `InvalidSessionError`: any unusable bearer session; includes the challenge
  header.
- `RequestValidationError`: converted by the FastAPI boundary, not raised by
  services.
- Agent resource errors never reveal whether a foreign identifier exists.
- Known SDK, provider, and transport failures map to `agent_run_failed`
  without exposing the upstream exception. Unexpected programming defects
  remain visible to the internal caller.

---

## Error Handling Patterns

- Raise the error class, not an instance with request-specific unsafe text,
  when the class-level code and message are sufficient.
- Catch only exceptions the service can map meaningfully. Unexpected failures
  should remain failures rather than being mislabeled as validation errors.
- Roll back an interrupted transaction before raising its domain mapping.
- Preserve safe framework headers when converting `HTTPException`.

---

## Common Mistakes

- Returning FastAPI's default `{"detail": ...}` creates an inconsistent
  contract.
- Serializing `exc.errors()` directly can expose rejected passwords through
  `input` or `ctx`.
- Returning early for an unknown nickname skips Argon2 work and creates an
  obvious timing difference. Verify against the shared dummy hash before
  raising the generic credential error.
- Replacing all database integrity errors with `nickname_conflict` is only
  valid while the affected transaction has no other possible integrity
  constraint failure. Revisit the mapping when adding constraints to the same
  use case.
