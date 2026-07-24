# Build RESTful user authentication system

## Goal

Add a REST-style user and authentication system to the FastAPI application so
an API client can create an account, log in with a nickname and password, use a
short-lived bearer credential, manage its own public profile, and invalidate
the current credential on logout. Persist user and session state in SQLite and
provide a Chinese handoff guide that another engineer can follow without
reading the source.

## Background

- The application already mounts routes beneath `/api/v1` and separates API,
  core, schema, service, and data concerns.
- The current repository has no database, migration framework, authentication
  contract, or compatibility constraint beyond preserving the health endpoint.
- The requested public user data is a UUID, nickname, optional avatar URL,
  creation time, and update time.
- The approved login identifier is `nickname`; passwords are authentication
  inputs and are never public user fields.
- The approved client credential is an opaque bearer token backed by a
  server-side SQLite session. A session lasts 24 hours and logout invalidates
  only the presented session.
- The application ships with no seeded or default account. Every caller
  registers and then logs in to obtain a credential.

## Requirements

### User resource

- Identify every user with a server-generated UUID version 4.
- Persist `nickname`, optional `avatar_url`, `created_at`, and `updated_at`.
- When supplied, require `avatar_url` to be an HTTP or HTTPS URL no longer
  than 2,048 characters.
- Accept nicknames whose NFKC-normalized form contains 2 through 50 Unicode
  characters after surrounding whitespace is removed.
- Compare nickname uniqueness using Unicode NFKC normalization followed by
  case folding. For example, case-only variants must conflict.
- Reject control characters in nicknames.
- Require registration passwords from 15 through 128 characters without
  imposing character class rules; allow Unicode, spaces, and
  password-manager-generated values.
- Accept a non-empty login password up to 128 characters, then use the
  authentication result rather than the registration policy to decide whether
  credentials are valid.
- Hash passwords with Argon2id through a maintained library. Never persist or
  return plaintext passwords.
- Never include the password hash or normalized nickname key in an API
  response.
- Let an authenticated user read and update its own `nickname` and
  `avatar_url`.
- Interpret `avatar_url: null` in a profile patch as clearing the avatar.
  Reject `nickname: null`, an empty patch, or a patch containing unknown
  fields.
- Advance `updated_at` when a persisted profile value changes.

### Session resource

- Log in with `nickname` and `password`.
- Generate a cryptographically random opaque bearer token and return its raw
  value only in the successful login response.
- Store only a SHA-256 digest of the bearer token.
- Expire sessions 24 hours after creation.
- Treat missing, malformed, unknown, expired, and revoked credentials as
  invalid sessions.
- Return the same generic login failure for an unknown nickname and an
  incorrect password.
- Delete or otherwise invalidate the current server-side session on logout.
  Reusing the logged-out token must fail immediately.
- Add `Cache-Control: no-store` and `Pragma: no-cache` to successful login
  responses so intermediaries are instructed not to retain credentials.

### HTTP contract

All endpoints are below the configured `/api/v1` prefix.

| Method | Path | Authentication | Success |
| --- | --- | --- | --- |
| `POST` | `/users` | None | `201` with the public user |
| `POST` | `/sessions` | None | `201` with bearer token, expiry, and public user |
| `GET` | `/users/me` | Bearer | `200` with the public user |
| `PATCH` | `/users/me` | Bearer | `200` with the updated public user |
| `DELETE` | `/sessions/current` | Bearer | `204` with no response body |

Registration input:

```json
{
  "nickname": "aria",
  "password": "correct horse battery staple",
  "avatar_url": "https://cdn.example.com/avatars/aria.png"
}
```

Public user representation:

```json
{
  "id": "9f979b61-77cc-4294-945d-dd0dc96bb2d3",
  "nickname": "aria",
  "avatar_url": "https://cdn.example.com/avatars/aria.png",
  "created_at": "2026-07-23T10:00:00Z",
  "updated_at": "2026-07-23T10:00:00Z"
}
```

Login input:

```json
{
  "nickname": "aria",
  "password": "correct horse battery staple"
}
```

Successful login representation:

```json
{
  "access_token": "<returned-once-by-the-login-endpoint>",
  "token_type": "bearer",
  "expires_at": "2026-07-24T10:00:00Z",
  "user": {
    "id": "9f979b61-77cc-4294-945d-dd0dc96bb2d3",
    "nickname": "aria",
    "avatar_url": "https://cdn.example.com/avatars/aria.png",
    "created_at": "2026-07-23T10:00:00Z",
    "updated_at": "2026-07-23T10:00:00Z"
  }
}
```

Authenticated requests send:

```text
Authorization: Bearer <access-token>
```

Every application and request-validation failure uses:

```json
{
  "error": {
    "code": "machine_readable_code",
    "message": "Safe human-readable message"
  }
}
```

Validation failures may add a `details` array, but must not echo the submitted
password. Required stable errors are:

| Condition | Status | Code | Additional header |
| --- | --- | --- | --- |
| Normalized nickname already exists | `409` | `nickname_conflict` | None |
| Unknown nickname or wrong password | `401` | `invalid_credentials` | None |
| Missing, malformed, expired, revoked, or unknown bearer token | `401` | `invalid_session` | `WWW-Authenticate: Bearer` |
| Invalid request body | `422` | `validation_error` | None |

### Persistence and configuration

- Use SQLite as the application database.
- Make the database URL configurable with `APP_DATABASE_URL`, defaulting to
  `sqlite:///./inspire_flow.db`.
- Make the lifetime configurable with `APP_SESSION_TTL_HOURS`, defaulting to
  `24` and requiring a positive integer.
- Reproduce the schema through Alembic migrations. Do not call implicit ORM
  table creation during application startup.
- Enforce SQLite foreign keys for application connections.
- Treat service functions as transaction owners; repositories query and mutate
  but do not commit.
- Serialize every API timestamp as a timezone-aware UTC datetime.
- Exclude SQLite files, `.env`, virtual environments, caches, and generated
  artifacts from Git while keeping `.env.example` and `uv.lock` trackable.

### Architecture and compatibility

- Preserve the existing route to service to repository/model boundaries.
- Keep request and response contracts in Pydantic schema modules.
- Keep password and token operations in shared security infrastructure rather
  than route functions.
- Map domain/application errors to the stable error envelope in one FastAPI
  error-handling boundary.
- Preserve `GET /api/v1/health` and its current response contract.

### Handoff document

- Create `HANDOFF_USERSYS.MD` at the repository root after the API contract is
  stable.
- Write the handoff in Chinese for engineers integrating with the service.
- Document dependency setup, database migration, server startup, base URL,
  endpoint methods and paths, request and response bodies, status codes,
  registration, login, bearer credential use, profile retrieval and update,
  and logout.
- Include copyable curl commands that use shell variables such as
  `$BASE_URL`, `$PASSWORD`, and `$ACCESS_TOKEN`. Do not publish a real password,
  token, database contents, or production secret.
- State explicitly that there is no default account and that registration
  followed by login is the only included credential-acquisition flow.
- Include the stable error reference, credential-handling cautions, and a
  short integration checklist.
- Review the final text with both `humanizer:humanizer` and `humanizer-zh`.
  Keep it direct and technical, remove formulaic AI phrasing, and ensure the
  final document contains no em dash or en dash characters.

## Acceptance Criteria

- [ ] `POST /api/v1/users` creates a user with a UUID and returns exactly the
      public fields; no password-derived or normalization field is exposed.
- [ ] A case-insensitive or NFKC-equivalent nickname duplicate returns `409`
      with `error.code == "nickname_conflict"`.
- [ ] Registration rejects invalid nickname, password, and avatar URL inputs
      with a safe `422 validation_error` response that does not echo a
      password.
- [ ] `POST /api/v1/sessions` accepts the registered nickname and password,
      returns `201`, a 24-hour opaque bearer credential, its expiry, and the
      public user, with no-store response headers.
- [ ] Unknown-nickname and wrong-password login attempts return the same
      `401 invalid_credentials` response body.
- [ ] Only a token digest is persisted; the raw bearer token returned by login
      is absent from the database.
- [ ] `GET /api/v1/users/me` returns the authenticated public user.
- [ ] `PATCH /api/v1/users/me` updates a nickname or avatar URL, supports
      clearing the avatar, rejects an empty patch, and advances `updated_at`
      when a persisted value changes.
- [ ] Missing, malformed, unknown, expired, and revoked bearer tokens return
      `401 invalid_session` with `WWW-Authenticate: Bearer`.
- [ ] `DELETE /api/v1/sessions/current` returns an empty `204` response,
      invalidates only that session, and rejects subsequent reuse.
- [ ] A user with two sessions can log out one session without invalidating the
      other.
- [ ] Alembic can upgrade an empty temporary SQLite database to `head` and
      downgrade it to `base`.
- [ ] API timestamps are emitted as timezone-aware UTC values and SQLite
      foreign-key enforcement is active for application connections.
- [ ] The existing health endpoint remains compatible.
- [ ] `uv lock --check`, locked dependency sync, Ruff lint, Ruff format, the
      warning-free pytest suite, and a real Uvicorn health smoke test pass.
- [ ] `HANDOFF_USERSYS.MD` lets a new integrator register, log in, attach the
      credential, retrieve and update a profile, and log out without reading
      source code.
- [ ] The handoff contains no real credentials, no formulaic AI filler, and no
      em dash or en dash characters.

## Out of Scope

- Email identity, email verification, password change or reset, account
  recovery, social login, MFA, roles, and authorization policies.
- Session listing, logout of all sessions, refresh tokens, and device/session
  metadata.
- User search, user listing, user deletion, and administrative endpoints.
- Avatar upload or binary storage; `avatar_url` is metadata only.
- Built-in brute-force throttling or distributed rate limiting.
- Production database deployment, horizontal session storage, or switching
  away from the requested SQLite backend.
