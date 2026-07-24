# RESTful User Authentication Technical Design

## Overview

The feature adds two resources beneath the existing API prefix:

- `users` owns public profile state and password-derived authentication state.
- `sessions` owns opaque bearer credentials and their expiry/revocation state.

The implementation remains synchronous because the existing FastAPI routes are
synchronous and SQLite is local, file-backed storage. SQLAlchemy 2.0 supplies
the ORM and session boundary, Alembic owns schema evolution, and `pwdlib`
supplies Argon2id password hashing. The standard library supplies UUIDs,
cryptographic token generation, SHA-256 token digests, Unicode normalization,
and timezone-aware UTC datetimes.

## Dependency Decisions

Runtime additions:

- `sqlalchemy` for declarative models, typed queries, and unit-of-work sessions.
- `alembic` for reproducible schema upgrades and downgrades.
- `pwdlib[argon2]` for Argon2id password hashing and verification.

No async database driver is added. Async SQLAlchemy would add an event-loop
boundary and `aiosqlite` without improving the behavior required by this local
SQLite service.

## Package Boundaries

```text
HTTP request
  -> api/routes/{users,sessions}.py
  -> api/dependencies.py
  -> services/{users,sessions}.py
  -> data/repositories/{users,sessions}.py
  -> data/models/{user,auth_session}.py
  -> SQLite
```

| Area | Owner |
| --- | --- |
| `api/routes/` | HTTP methods, status codes, response headers, dependency wiring |
| `api/dependencies.py` | Database-session lifetime and bearer authentication dependency |
| `schemas/` | Pydantic request, public response, and error contracts |
| `services/` | Use cases, transactions, normalization coordination, domain errors |
| `data/repositories/` | SQLAlchemy queries and mutations without commits |
| `data/models/` | Internal persistence entities and relationships |
| `core/security.py` | Password hashing, token generation, and token digesting |
| `core/errors.py` | Domain error types and FastAPI exception handlers |
| `core/time.py` | Testable timezone-aware UTC clock |
| `data/database.py` | Engine, session factory, dependency, foreign-key pragma |
| `data/types.py` | SQLite UTC datetime conversion |

Routes never import a concrete model or repository. Repositories never format
HTTP errors. Services own `commit()` and `rollback()` so each use case is a
single transaction.

## Data Model

### `users`

| Column | SQLAlchemy/Python type | Constraint |
| --- | --- | --- |
| `id` | `Uuid(as_uuid=True, native_uuid=False)` / `UUID` | Primary key, UUID v4 default |
| `nickname` | `String(50)` / `str` | Required public display value |
| `nickname_key` | `String(255)` / `str` | Required unique normalized lookup key |
| `avatar_url` | `String(2048)` / `Optional[str]` | Nullable |
| `password_hash` | `String(255)` / `str` | Required, internal only |
| `created_at` | `UTCDateTime` / aware `datetime` | Required |
| `updated_at` | `UTCDateTime` / aware `datetime` | Required |

The migration creates a named unique constraint on `nickname_key`. The public
nickname is preserved after trimming, while the lookup key is:

```python
unicodedata.normalize("NFKC", nickname.strip()).casefold()
```

Validation rejects a normalized length outside 2 through 50 or any Unicode
control character. The database constraint remains the final authority during
concurrent registrations or profile updates.

### `auth_sessions`

| Column | SQLAlchemy/Python type | Constraint |
| --- | --- | --- |
| `id` | `Uuid(as_uuid=True, native_uuid=False)` / `UUID` | Primary key, UUID v4 default |
| `user_id` | `Uuid(as_uuid=True, native_uuid=False)` / `UUID` | Foreign key to users, cascade delete |
| `token_hash` | `String(64)` / `str` | Required unique SHA-256 hex digest |
| `expires_at` | `UTCDateTime` / aware `datetime` | Required |
| `created_at` | `UTCDateTime` / aware `datetime` | Required |

An index on `user_id` supports later cleanup and relationship access. The raw
token is never assigned to the ORM entity.

### UTC storage

SQLite does not preserve timezone information consistently. `UTCDateTime`
normalizes an aware input to naive UTC while binding and reattaches
`timezone.utc` when reading. Passing a naive datetime is a programming error.
API schemas therefore always serialize UTC with an offset, and tests parse the
value rather than comparing an implementation-specific string spelling.

## Configuration

`Settings` adds:

```python
database_url: str = "sqlite:///./inspire_flow.db"
session_ttl_hours: int = Field(default=24, gt=0)
```

These use the existing `APP_` prefix:

```dotenv
APP_DATABASE_URL=sqlite:///./inspire_flow.db
APP_SESSION_TTL_HOURS=24
```

`data/database.py` builds a module-level engine and session factory from the
cached settings. Its engine factory sets `check_same_thread=False` for SQLite
so FastAPI's synchronous worker-thread boundary can safely use request-owned
connections. SQLite connections also receive `PRAGMA foreign_keys=ON` through
a SQLAlchemy connection event. `get_db_session()` yields one session and always
closes it; services decide whether to commit or roll back.

Tests override `get_db_session` with a temporary SQLite engine. File-backed
temporary databases avoid the connection-pooling caveats of independent
in-memory SQLite connections.

## Validation Contracts

`schemas/users.py` owns shared field rules and these models:

- `UserCreate(nickname, password: SecretStr, avatar_url)`
- `UserUpdate(nickname | omitted, avatar_url | omitted)`
- `UserPublic(id, nickname, avatar_url, created_at, updated_at)`

`UserUpdate` rejects a body with no supplied fields. Pydantic's model-fields-set
distinguishes an omitted avatar from explicit `null`.

`schemas/sessions.py` owns:

- `SessionCreate(nickname, password: SecretStr)`
- `SessionCreated(access_token, token_type, expires_at, user)`

Every input schema uses `extra="forbid"`. `avatar_url` uses Pydantic `HttpUrl`
with a 2,048-character cap at input and is stored/returned as a string so JSON
consumers receive the requested field without ORM-specific types. Registration
enforces the 15 to 128 character password policy. Login accepts any non-empty
password through 128 characters so a short wrong password is still an
authentication failure, not a registration-policy response.

FastAPI request-validation errors are converted to the application envelope.
The handler includes only safe locations, messages, and error types. It removes
Pydantic's `input` and context values so a rejected password cannot be reflected
into logs or responses.

## Security Design

### Passwords

`core/security.py` configures `PasswordHash.recommended()` and exposes:

```python
hash_password(password: str) -> str
verify_password(password: str, password_hash: str) -> bool
```

At module load it generates one valid dummy hash. Login verifies against the
dummy hash when the nickname lookup misses, then returns the same
`InvalidCredentialsError` as a real hash mismatch. This does not guarantee
perfect constant-time behavior, but it avoids the large and obvious timing
difference between performing Argon2 verification and returning immediately.

### Bearer sessions

`generate_session_token()` uses `secrets.token_urlsafe(32)`. The returned value
has 32 random bytes before URL-safe encoding. `digest_session_token()` stores
only `hashlib.sha256(token.encode("utf-8")).hexdigest()`.

Authentication flow:

1. `HTTPBearer(auto_error=False)` parses the Authorization header.
2. The dependency requires a case-insensitive `Bearer` scheme and a non-empty
   credential.
3. The digest identifies the server-side session.
4. Unknown, expired, or malformed input raises `InvalidSessionError`.
5. An expired row is deleted and committed as opportunistic cleanup; the
   request still returns `401`.
6. A valid dependency returns an `AuthenticatedSession` value containing both
   the user and session entity so logout can revoke exactly the presented row.

Session tokens are bearer credentials. Anyone holding one has the session's
authority, so the handoff tells integrators to keep tokens out of source code,
URLs, logs, and persistent browser storage. Production transport security and
rate limiting are deployment responsibilities outside this SQLite MVP.

## Use Cases and Transactions

### Register

1. Validate and normalize fields at the schema/service boundary.
2. Hash the password before constructing the user model.
3. Add the user and commit.
4. Catch `IntegrityError`, roll back, and raise `NicknameConflictError`.
5. Refresh and return the persisted user.

The service relies on the unique constraint and maps `IntegrityError` for race
safety instead of treating a pre-check as authoritative.

### Login

1. Normalize the nickname lookup key.
2. Query the user.
3. Verify the submitted password against the real or dummy hash.
4. On failure, raise one generic `InvalidCredentialsError`.
5. Generate a token, digest it, calculate `expires_at = now + ttl`, persist the
   session, commit, and return the raw token plus public user.

The route adds the no-store headers. Registration does not implicitly log the
user in.

### Read or update current user

The authentication dependency resolves the session and user. `GET` returns the
user. `PATCH` applies only fields that were supplied, recalculates
`nickname_key` if the nickname changes, and advances `updated_at` only when a
persisted value differs. A nickname uniqueness race maps to the same
`NicknameConflictError` as registration.

### Logout

The authentication dependency identifies the exact session row. The service
deletes it and commits. The route returns `Response(status_code=204)` without a
body. Other sessions for the same user remain valid.

## Error Boundary

Domain errors carry a stable code, safe message, HTTP status, and optional
headers. `register_error_handlers()` installs:

- a handler for application errors;
- a handler for `RequestValidationError`;
- a handler for Starlette `HTTPException` so application routes use the same
  envelope for framework-generated failures.

The required responses are:

```json
{"error":{"code":"nickname_conflict","message":"Nickname is already in use"}}
```

```json
{"error":{"code":"invalid_credentials","message":"Invalid nickname or password"}}
```

```json
{"error":{"code":"invalid_session","message":"A valid bearer session is required"}}
```

The invalid-session response includes `WWW-Authenticate: Bearer`.

## API Composition

`api/router.py` includes:

```python
api_router.include_router(users_router, prefix="/users", tags=["users"])
api_router.include_router(sessions_router, prefix="/sessions", tags=["sessions"])
```

Feature route modules use relative resource paths:

- users: `POST ""`, `GET "/me"`, `PATCH "/me"`
- sessions: `POST ""`, `DELETE "/current"`

This preserves the configured version prefix and keeps the existing health
router unchanged.

## Migration and Startup

Alembic files live at the repository root:

```text
alembic.ini
migrations/
├── env.py
├── script.py.mako
└── versions/
    └── 20260723_0001_create_users_and_auth_sessions.py
```

`migrations/env.py` imports the model metadata, reads
`get_settings().database_url`, and supports offline and online migrations.
The initial revision creates `users` first and `auth_sessions` second; downgrade
drops them in reverse order.

Normal startup never calls `Base.metadata.create_all()`. A developer runs:

```bash
uv run alembic upgrade head
uv run uvicorn inspire_flow_backend.main:app --reload
```

## Testing Strategy

Tests follow red, green, refactor by boundary:

1. Unit tests lock down nickname normalization, password verification, token
   digests, and aware UTC conversion.
2. Migration tests point Alembic at a temporary database, upgrade to `head`,
   inspect both tables and constraints, then downgrade to `base`.
3. API fixtures create an app whose database dependency uses a temporary
   SQLAlchemy session factory.
4. Registration tests cover public shape, normalization collision, validation,
   and password non-disclosure.
5. Session tests cover successful login, generic failures, digest-only
   persistence, no-store headers, every invalid bearer class, two concurrent
   sessions, and logout isolation.
6. Profile tests cover retrieval, nickname changes, avatar changes/clearing,
   empty patches, conflicts, and `updated_at`.
7. Existing health/config tests stay green.

Tests use deterministic assertions around time windows rather than freezing the
production clock globally. Unit tests inject or monkeypatch `utc_now` where an
exact transition must be asserted.

## Compatibility, Operations, and Rollback

- The health endpoint and application factory remain available at their
  existing import paths.
- Adding settings has safe local defaults, so current startup commands remain
  valid after applying migrations.
- Existing SQLite files are ignored but never deleted by application code.
- Schema rollback is `uv run alembic downgrade base`. It intentionally drops
  session and user tables, so it is destructive and must only be used against a
  disposable or backed-up database.
- Code rollback is safe only while the corresponding schema is also rolled
  back or unused; the old application does not access the new tables.
- Before merging, a fresh temporary database must pass upgrade, API tests, and
  downgrade. A real local Uvicorn process must still answer the health route.

## Deferred Work

- Rate limiting and brute-force throttling.
- Password change, password reset, recovery, and email ownership.
- MFA, roles, and authorization policy.
- Refresh tokens, session listing, all-session logout, and device metadata.
- Account administration and deletion.
- Production database selection, distributed session storage, and deployment
  hardening.

## Research Record

Primary-source notes and the reasoning behind the password, token, UUID, and
migration choices are preserved in
`research/security-and-persistence-decisions.md`.
