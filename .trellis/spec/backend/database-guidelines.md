# Database Guidelines

> Database patterns and conventions for this project.

---

## Overview

The backend uses synchronous SQLAlchemy 2.0 with SQLite. Alembic is the only
schema-creation mechanism; application startup never calls
`Base.metadata.create_all()`. Services own transaction boundaries,
repositories only query or mutate, and API routes never import concrete models
or repositories.

---

## Scenario: SQLite Persistence and Schema Changes

### 1. Scope / Trigger

- Trigger: adding a persisted entity, changing a column or constraint, writing
  a new query, or changing a transaction.
- Every schema change requires a reversible Alembic revision and migration
  tests against a fresh temporary SQLite file.

### 2. Signatures

Database infrastructure:

```python
def create_database_engine(database_url: str) -> Engine: ...
def enable_sqlite_foreign_keys(engine: Engine) -> None: ...
def get_db_session() -> Generator[Session]: ...
```

Repository examples:

```python
def get_user_by_nickname_key(db: Session, key: str) -> User | None: ...
def add_user(db: Session, user: User) -> None: ...
def get_session_by_token_hash(
    db: Session,
    token_hash: str,
) -> AuthSession | None: ...
def get_project(
    db: Session,
    user_id: UUID,
    project_id: UUID,
) -> Project | None: ...
```

The current tables are:

```text
users(id, nickname, nickname_key, avatar_url, profile_text, password_hash,
      created_at, updated_at)
auth_sessions(id, user_id, token_hash, expires_at, created_at)
user_profiles(user_id, bio, timezone, preferred_language, creator_identity,
              content_focus, collaboration_preferences, created_at, updated_at)
agent_conversations(id, user_id, title, archived_at, summary_ciphertext,
                    summary_through_sequence, summary_updated_at, next_sequence,
                    active_run_id, active_run_started_at, created_at, updated_at)
agent_messages(id, conversation_id, turn_id, sequence, item_type, role,
               payload_ciphertext, created_at)
user_memories(id, user_id, category, content_ciphertext, content_fingerprint,
              status, origin, is_sensitive, is_pinned, user_edited,
              source_conversation_id, source_message_id, source_deleted_at,
              created_at, updated_at)
transcription_jobs(id, user_id, status, language, use_itn,
                   transcript_ciphertext, analysis_ciphertext,
                   detected_language, duration_seconds, error_code,
                   attempt_count, created_at, updated_at, started_at,
                   completed_at)
projects(id, user_id, title, type, audience, summary, icon_url,
         created_at, updated_at)
inspirations(id, user_id, title, content, status, source_type,
             source_conversation_id, source_message_id, created_at, updated_at)
inspiration_projects(inspiration_id, project_id)
brand_organizations(...)
brand_memberships(...)
brand_invitations(...)
creator_workshops(...)
workshop_social_accounts(...)
workshop_contacts(...)
workshop_project_selections(...)
workshop_publications(...)
workshop_publication_social_accounts(...)
workshop_publication_contacts(...)
workshop_publication_project_cards(...)
workshop_brand_authorizations(...)
brand_follows(...)
brand_interests(...)
creator_inbox_items(...)
idempotency_records(...)
agent_turn_runs(...)
```

### 3. Contracts

- `APP_DATABASE_URL` defaults to `sqlite:///./inspire_flow.db`.
- UUID identifiers use `Uuid(as_uuid=True, native_uuid=False)` and UUID v4
  defaults.
- `users.nickname_key` and `auth_sessions.token_hash` are unique.
- `users.profile_text` is a nullable, Agent-managed plaintext summary limited
  to 8,000 characters at the service boundary. It supplements rather than
  replaces the structured `user_profiles` row and is not part of `UserPublic`.
- `auth_sessions.user_id` references `users.id` with `ON DELETE CASCADE`.
- SQLite application connections enable `PRAGMA foreign_keys=ON` and use
  `check_same_thread=False`.
- `UTCDateTime` accepts only aware datetimes, stores naive UTC in SQLite, and
  restores aware UTC values.
- A session row stores only the SHA-256 digest of the bearer token.
- Agent message payloads, summaries, and memory content use authenticated
  application-level encryption. Plaintext fallback is forbidden.
- Memory deduplication uses a keyed HMAC fingerprint scoped by user and
  category, not a plaintext content hash.
- `agent_messages.sequence` is unique within its conversation.
- Conversation deletion cascades messages. Memory source foreign keys use
  `ON DELETE SET NULL`, while the service first removes unprotected automatic
  memories and tombstones protected provenance in one transaction.
- Repositories never decrypt context and never commit. Services decrypt only
  after a user-scoped lookup.
- SQLite application connections enable WAL mode and a bounded busy timeout
  because FastAPI and Celery write the same file. Never keep a transaction
  open during upload streaming, broker I/O, model loading, or inference.
- Transcription results use the context cipher. Raw audio, plaintext
  transcripts, spool paths, and native exceptions are not database fields.
- Transcription emotion/event metadata is a versioned JSON document encrypted
  into `analysis_ciphertext`; existing rows may keep this column null.
- Projects belong to one user through `ON DELETE CASCADE`. Every single-project
  query includes both `project_id` and `user_id`; lists order by
  `updated_at DESC, id DESC` through `ix_projects_user_id_updated_at`.
- Project services commit once per mutation. A patch that does not change a
  value must preserve `updated_at`.
- `projects.icon_url` is nullable `VARCHAR(2048)`. Existing and unset icons
  read as `null`; clearing an icon writes `NULL`.
- Inspirations belong to one user through `ON DELETE CASCADE`. Status is one
  of `inbox`, `developing`, `converted`, or `archived`; source type is one of
  `manual`, `agent`, or `voice`.
- Inspiration titles and content are intentionally plaintext so SQLite can
  perform keyword filtering and pagination. Database files and backups are
  therefore readable creative assets and must be access-controlled.
- `inspiration_projects` is a composite-primary-key many-to-many table. Both
  foreign keys use `ON DELETE CASCADE`; services validate that both resources
  share the authenticated owner before linking.
- Inspiration source foreign keys use `ON DELETE SET NULL`. Project and
  conversation services preflight deletion so a previously associated
  inspiration is never silently left without every project and source.
- An unassociated inspiration is valid only in the `inbox` workflow. Project
  set replacement validates every UUID before mutating and commits once.
- Workshop publishing appends an immutable parent snapshot and copied child
  rows. Draft and source-project updates must not cascade into publications.
- `(workshop_user_id, version)` is unique for publication snapshots.
  `workshop_publications.updated_at` is copied from the draft at publication
  time and is the only column used for discovery `sort_by=updated_at`.
- Contact values are encrypted in both draft and publication tables. The
  application decrypts only after current brand membership and creator
  authorization have been established.
- Partial unique indexes enforce one pending invitation, one pending interest,
  and user-scoped idempotency when nullable `brand_id` would make a normal
  SQLite unique constraint insufficient.
- Idempotency records persist only key digests, request fingerprints, safe
  response headers, and encrypted response bodies. They expire after 24 hours.
- Agent SSE work owns a separate SQLAlchemy session and stores one
  `agent_turn_runs` row tied one-to-one to its idempotency record.

### 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| Duplicate normalized nickname | Database raises `IntegrityError`; service rolls back and raises `NicknameConflictError` |
| Naive datetime passed to `UTCDateTime` | Raise `ValueError` before persistence |
| Expired session is resolved | Delete row, commit cleanup, then raise `InvalidSessionError` |
| Migration runs against an empty SQLite file | Create `users`, then `auth_sessions`, and record the head revision |
| Migration downgrades to `base` | Drop `auth_sessions`, then `users` |
| Upgrade from `20260723_0001` | Backfill exactly one empty `user_profiles` row per existing user |
| Downgrade `20260724_0002` | Destructively remove memories, messages, conversations, and profiles only |
| Repository mutation succeeds | Do not commit; the calling service decides the transaction |
| User is deleted | Cascade that user's transcription jobs |
| Foreign or unknown inspiration UUID | Return the same `inspiration_not_found` behavior |
| Foreign project is linked to an inspiration | Reject before mutation with `project_not_found` |
| Project or conversation deletion would orphan inspirations | Roll back/no-op and require explicit cascade confirmation |
| FastAPI and Celery connect concurrently | Both connections use foreign keys, WAL, and the configured busy timeout |
| Published Workshop source changes | Existing publication snapshot remains unchanged |
| Unauthorized brand reads a contact | Contact row and value are absent from the projection |
| Concurrent pending interest inserts | Partial unique index permits only one pending row |
| Nullable brand id in idempotency scope | Partial unique index enforces the user-only scope |

### 5. Good / Base / Bad Cases

- Good: a service calls a repository, commits once for the use case, catches
  the expected integrity error, rolls back, and maps it to a domain error.
- Base: a request-owned `Session` is yielded by `get_db_session()` and closed
  after the request.
- Bad: a repository commits, a route constructs a SQLAlchemy query, startup
  implicitly creates tables, or a naive local datetime is written to SQLite.

### 6. Tests Required

- Upgrade a fresh SQLite file to `head`; assert table names, columns, unique
  constraints, foreign key behavior, and index names.
- Downgrade the same file to `base`; assert application tables are gone.
- Open an application engine and assert `PRAGMA foreign_keys == 1`.
- Unit-test both directions of `UTCDateTime` and rejection of naive input.
- For credential storage, assert the returned raw token is not present in the
  database and its SHA-256 digest is.
- Read SQLite directly and assert conversation text, summaries, and memory
  content are absent from ciphertext columns.
- Test conversation sequence uniqueness, run-lock reclaim, memory provenance
  behavior, profile backfill, and downgrade from the context revision.
- Test encrypted transcription storage, user cascade, and the reversible STT
  migration.
- Test project columns, owner cascade, composite index, upgrade from the
  preceding revision, and downgrade that removes only the project table.
- Test the project-icon revision from `20260724_0005` in both directions and
  prove existing project rows survive with a null icon.
- Test inspiration checks, indexes, user/source/project foreign keys, source
  `SET NULL`, link cascades, upgrade from `20260724_0006`, and downgrade.
- Test the nullable user-profile-text revision from `20260724_0007` in both
  directions and prove existing user rows survive.
- Test user-scoped inspiration CRUD, atomic full-set replacement, idempotent
  link mutations, filters/search/sort/page order, and deletion impact.
- Test Workshop, brand, engagement, idempotency, and Agent-turn tables by
  upgrading from `20260724_0008` to `20260724_0009` and downgrading again.
- Read SQLite directly and assert contact values and cached idempotent response
  bodies are not present in plaintext.
- Use file-backed temporary SQLite databases for API tests so independent
  connections do not split in-memory state.

### 7. Wrong vs Correct

#### Wrong

```python
def add_user(db: Session, user: User) -> None:
    db.add(user)
    db.commit()
```

This hides the transaction boundary and prevents one service use case from
coordinating multiple mutations.

#### Correct

```python
def add_user(db: Session, user: User) -> None:
    db.add(user)


def register_user(db: Session, payload: UserCreate) -> User:
    user = build_user(payload)
    add_user(db, user)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise NicknameConflictError from error
    return user
```

---

## Query Patterns

- Use SQLAlchemy 2.0 `select()` and typed `Session.scalar()`.
- Keep query functions in `data/repositories/`.
- Eager-load the user when resolving an authentication session so the request
  does not depend on an extra lazy query after the session closes.
- Keep package `__init__.py` files free of import side effects. Alembic imports
  concrete model modules in `migrations/env.py` to register metadata.

## Migrations

Apply the current schema:

```bash
uv run alembic upgrade head
```

Inspect the applied revision:

```bash
uv run alembic current
```

Downgrading to `base` drops user data and is only safe for disposable or
backed-up databases:

```bash
uv run alembic downgrade base
```

Do not hand-edit an existing applied revision to change production schema
semantics. Add a new revision instead.

---

## Naming Conventions

- Table and column names use plural `snake_case` tables and `snake_case`
  columns.
- `Base.metadata` supplies deterministic `pk_`, `fk_`, `uq_`, `ck_`, and
  `ix_` names.
- Explicit indexes follow `ix_<table>_<column>`.
- Migrations use stable revision identifiers and create referenced tables
  before referencing tables.

---

## Common Mistakes

- Importing models from `data.models.__init__` would add package import side
  effects. Import concrete model modules where metadata registration is
  required.
- A narrow worker import can load one mapped class while leaving its
  string-named relationship targets unregistered. Tests that previously
  imported every model can mask this. Runtime entry points and Alembic call
  `data.model_registry.register_models()`, and an isolated subprocess test must
  prove `configure_mappers()` succeeds.
- SQLite does not reliably preserve timezone offsets. Always use
  `UTCDateTime`, not a bare `DateTime`, for application timestamps.
- In-memory SQLite can give each connection an independent database. Use a
  temporary file unless the pool is deliberately configured for one shared
  connection.
- Checking nickname availability before insert is not a concurrency guarantee.
  Keep the unique constraint and map the resulting `IntegrityError`.
