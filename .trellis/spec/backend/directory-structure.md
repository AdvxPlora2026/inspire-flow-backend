# Directory Structure

> How backend code is organized in this project.

---

## Overview

The backend is an installable `src`-layout package named
`inspire_flow_backend`. HTTP transport, configuration, schemas, services, and
persistence concerns have separate owners. Routes may coordinate these layers,
but they must not redefine response contracts or implement storage access.

---

## Directory Layout

```text
.
├── migrations/
│   └── versions/
└── src/inspire_flow_backend/
    ├── api/
    │   ├── dependencies.py
    │   ├── router.py
    │   └── routes/
    ├── core/
    ├── data/
    │   ├── models/
    │   └── repositories/
    ├── schemas/
    ├── services/
    ├── workers/
    └── main.py
```

---

## Module Organization

| Package | Responsibility |
| --- | --- |
| `api/routes/` | FastAPI endpoint definitions and dependency wiring |
| `api/dependencies.py` | Request-owned database and authentication dependencies |
| `api/router.py` | Composition of feature routers |
| `core/` | Process settings, identity rules, security primitives, time, and application errors |
| `schemas/` | Pydantic request and response contracts |
| `services/` | Application behavior and transaction ownership |
| `services/agent/func/` | One module per Agent-visible FunctionTool plus the ordered registry |
| `services/agent/session.py` | User-scoped Agents SDK Session backed by encrypted rows |
| `services/agent/context.py` | Bounded profile, memory, summary, and recent-turn model input |
| `services/agent/compaction.py` | Rolling summary policy and optimistic cursor update |
| `services/agent/memory_extraction.py` | Evidence-backed long-term-memory candidates |
| `services/agent/conversation.py` | Durable Agent turn orchestration |
| `services/agent/streaming.py` | App-scoped background SSE Agent turns and safe event encoding |
| `services/agent/project_drafting.py` | Structured, non-persisted project drafts from descriptions |
| `services/agent/brand_advisor.py` | Search/fetch-only structured Advisor and deterministic evidence finalization |
| `services/agent/runtime.py` | Per-request model, shared outbound client, Agent, compactor, extractor, drafter, and Advisor lifecycle |
| `schemas/advisory.py` | Advisory request, draft, evidence, reasoning, and public report contracts |
| `services/advisory.py` | Brand/project authorization, immutable context assembly, and Advisor failure mapping |
| `services/projects.py` | User-scoped project lifecycle and draft failure mapping |
| `services/inspirations.py` | User-scoped inspiration lifecycle, project links, search, and deletion impact |
| `services/brands.py` | Brand organization, membership, owner, and invitation behavior |
| `services/workshops.py` | Workshop draft, publication snapshot, audience projection, authorization, and discovery |
| `services/engagement.py` | Brand follow, interest, and creator inbox state transitions |
| `services/idempotency.py` | Authenticated-write fingerprint, replay, and encrypted response retention |
| `data/models/` | Internal SQLAlchemy persistence entities |
| `data/model_registry.py` | Explicitly registers all related ORM models for narrow worker and migration entry points |
| `data/repositories/` | SQLAlchemy queries and mutations without commits |
| `workers/celery_app.py` | Lightweight task configuration and API-side publishing without model imports |
| `workers/stt_tasks.py` | Idempotent transcription orchestration inside Celery prefork children |
| `workers/stt_engine.py` | The only module that dynamically imports FunASR and Torch |
| `migrations/` | Alembic environment and reversible schema revisions |
| `main.py` | FastAPI application construction and module-level `app` |

New HTTP features should normally add a matching route, schema, and service
module. Do not add an empty persistence implementation merely to make every
feature touch the data layer.

The brand advisory route is intentionally non-persistent:
`api/routes/advisory.py` owns HTTP wiring, `schemas/advisory.py` owns all typed
contracts, `services/advisory.py` owns membership and optional project checks,
and `services/agent/brand_advisor.py` owns external research plus deterministic
evidence finalization. Do not add an advisory repository or table until the
versioned report-history product contract is approved.

---

## Naming Conventions

- Packages and modules use `snake_case`.
- Pydantic classes use descriptive `PascalCase` names such as
  `HealthResponse`.
- Route functions describe the HTTP operation, while service functions
  describe application behavior.
- Versioned application endpoints are composed under the configured
  `api_v1_prefix`; individual route modules do not repeat `/api/v1`.

---

## Scenario: Versioned FastAPI Endpoint

### 1. Scope / Trigger

- Trigger: adding or changing a FastAPI endpoint, its response contract, or
  environment wiring.
- This is a cross-layer change because route, service, schema, and process
  settings must agree.

### 2. Signatures

Current executable signatures:

```python
def create_app() -> FastAPI: ...

def health_check(
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    model_settings: Annotated[ModelSettings, Depends(get_model_settings)],
    db: Annotated[Session, Depends(get_db_session)],
) -> HealthResponse: ...

def build_health_response(
    settings: Settings,
    model_settings: ModelSettings,
    db: Session,
) -> HealthResponse: ...
```

Current HTTP signature:

```text
GET /api/v1/health -> 200 or 503 HealthResponse
```

### 3. Contracts

`HealthResponse`:

| Field | Type | Constraint |
| --- | --- | --- |
| `status` | `Literal["ok", "degraded", "unavailable"]` | Derived from dependency states |
| `services.database` | `Literal["ok", "unavailable"]` | Real `SELECT 1` probe |
| `services.model` | `Literal["ok", "not_configured"]` | Local `MODEL_*` completeness check |
| `services.injective` | `Literal["not_configured"]` | Placeholder state until integration exists |
| `version` | `str` | `APP_VERSION`, normally a Git SHA in deployment |
| `service` | `str` | Comes from `Settings.name` |
| `environment` | `str` | Comes from `Settings.environment` |

The database is critical. Model and Injective readiness are optional for
serving the core HTTP API. The health endpoint never calls the model provider,
spends tokens, or invents an Injective RPC check before that integration
exists. Health failures use this typed response instead of the general API
error envelope.

Settings use the `APP_` prefix:

| Key | Default |
| --- | --- |
| `APP_NAME` | `Inspire Flow Backend` |
| `APP_VERSION` | `dev` |
| `APP_ENVIRONMENT` | `development` |
| `APP_DEBUG` | `false` |
| `APP_API_V1_PREFIX` | `/api/v1` |
| `APP_DATABASE_URL` | `sqlite:///./inspire_flow.db` |
| `APP_SESSION_TTL_HOURS` | `24` |

Local `.env` values are optional. Unknown `.env` fields are ignored, and
`.env.example` contains only safe defaults.

### 4. Validation & Error Matrix

| Condition | Behavior |
| --- | --- |
| Database ready, optional dependency not ready | HTTP 200 with `status="degraded"` |
| Database unavailable | HTTP 503 with `status="unavailable"` and no exception detail |
| Complete `MODEL_*` configuration | `services.model="ok"` without a provider request |
| Missing `MODEL_*` value | `services.model="not_configured"` |
| Injective not implemented | `services.injective="not_configured"` |
| Unknown route | FastAPI default HTTP 404 |
| Invalid `APP_DEBUG` boolean | Pydantic settings validation fails during application construction |
| Extra `.env` field | Ignored by `Settings` |

### 5. Good / Base / Bad Cases

- Good: the route injects the request-owned session and typed settings,
  delegates the probe to the service, and maps `unavailable` to HTTP 503.
- Base: SQLite responds, model settings are blank, and Injective is not
  configured, so the endpoint returns HTTP 200 with `status="degraded"`.
- Bad: call the LLM on every health request, return exception strings, report
  an unimplemented integration as healthy, or move the endpoint to `/v1`.

### 6. Tests Required

- Settings tests: assert `APP_VERSION` parsing plus the `dev` default.
- Healthy database test: assert the exact `SELECT 1` probe and HTTP 200 typed
  response.
- Model tests: assert complete configuration is `ok` and missing configuration
  is `not_configured`, without public network access.
- Database failure test: raise a synthetic `SQLAlchemyError`; assert HTTP 503,
  the typed unavailable response, and absence of the exception text.
- Composition check: assert `/api/v1/health` exists and `/v1/health` does not.

### 7. Wrong vs Correct

#### Wrong

```python
@router.get("/api/v1/health")
def health_check():
    return {"status": "ok", "service": os.getenv("APP_NAME")}
```

This repeats the version prefix, bypasses the shared settings owner, and
redefines the response shape in the route.

#### Correct

```python
@router.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse}},
)
def health_check(
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    model_settings: Annotated[ModelSettings, Depends(get_model_settings)],
    db: Annotated[Session, Depends(get_db_session)],
) -> HealthResponse:
    health = build_health_response(settings, model_settings, db)
    if health.status == "unavailable":
        response.status_code = 503
    return health
```

---

## Examples

- `src/inspire_flow_backend/api/routes/health.py`
- `src/inspire_flow_backend/services/health.py`
- `src/inspire_flow_backend/schemas/health.py`
- `src/inspire_flow_backend/core/config.py`

---

## Scenario: REST User and Session Resources

### 1. Scope / Trigger

- Trigger: adding or changing registration, login, current-user profile, or
  logout behavior.
- This flow crosses schema, route, dependency, service, repository, model, and
  migration boundaries. Changes must keep every boundary in agreement.

### 2. Signatures

Current HTTP signatures:

```text
POST   /api/v1/users             -> 201 UserPublic
POST   /api/v1/sessions          -> 201 SessionCreated
GET    /api/v1/users/me          -> 200 UserPublic
PATCH  /api/v1/users/me          -> 200 UserPublic
DELETE /api/v1/sessions/current  -> 204 empty body
GET    /api/v1/users/me/profile  -> 200 UserProfilePublic
PATCH  /api/v1/users/me/profile  -> 200 UserProfilePublic
POST   /api/v1/users/me/memories -> 201 UserMemoryPublic
GET    /api/v1/conversations     -> 200 ConversationPage
POST   /api/v1/conversations     -> 201 ConversationPublic
GET    /api/v1/conversations/{conversation_id}/messages
POST   /api/v1/conversations/{conversation_id}/messages
```

Current service signatures:

```python
def register_user(db: Session, payload: UserCreate) -> User: ...
def update_user(db: Session, user: User, payload: UserUpdate) -> User: ...
def create_session(
    db: Session,
    payload: SessionCreate,
    ttl_hours: int,
) -> CreatedSession: ...
def resolve_session(db: Session, token: str) -> AuthenticatedSession: ...
def revoke_session(db: Session, auth_session: AuthSession) -> None: ...
```

### 3. Contracts

`UserCreate` accepts `nickname`, `password`, and optional `avatar_url`.
Registration passwords contain 15 through 128 characters. `SessionCreate`
accepts the same login identity but permits any non-empty password through 128
characters so a wrong password remains an authentication failure.

`UserPublic` contains only:

```text
id: UUID
nickname: str
avatar_url: str | null
created_at: aware UTC datetime
updated_at: aware UTC datetime
```

`users.profile_text` is an internal Agent-managed field. It is injected into
the bounded model context but remains absent from both `UserPublic` and the
public `UserUpdate` request, while the structured `/users/me/profile` resource
continues unchanged.

`SessionCreated` adds `access_token`, literal `token_type: "bearer"`,
`expires_at`, and `user: UserPublic`. The raw access token is returned only by
successful login. Authenticated requests send
`Authorization: Bearer <access-token>`.

`APP_SESSION_TTL_HOURS` controls session lifetime and must be positive.
Registration never creates a session, and the project has no seeded account.

### 4. Validation & Error Matrix

| Condition | HTTP behavior |
| --- | --- |
| Normalized nickname already exists | `409 nickname_conflict` |
| Unknown nickname or wrong password | `401 invalid_credentials` |
| Missing, malformed, expired, unknown, or revoked token | `401 invalid_session` and `WWW-Authenticate: Bearer` |
| Invalid body, unknown field, or empty profile patch | `422 validation_error` |
| Successful login | `201` with `Cache-Control: no-store` and `Pragma: no-cache` |
| Successful logout | `204` with no response body |

### 5. Good / Base / Bad Cases

- Good: a route validates with a Pydantic schema, calls one service use case,
  and maps the returned entity to a public response schema.
- Base: a client registers, logs in, uses one bearer token, and logs out that
  session without affecting another session.
- Bad: a route returns an ORM user directly, exposes `password_hash` or
  `nickname_key`, creates a login session during registration, or accepts a
  token in a URL.

### 6. Tests Required

- Registration: assert exact public fields, UUID parsing, normalized nickname
  collision, safe validation output, and Argon2-only persistence.
- Login: assert a 24-hour expiry window, generic credential failures,
  no-store headers, and that the raw token is absent from SQLite.
- Authentication: cover missing, malformed, unknown, expired, and revoked
  credentials plus case-insensitive `Bearer`.
- Profile: cover read, nickname change, avatar change/clear, conflict, empty
  patch, and no-op `updated_at`.
- Logout: assert an empty `204`, rejected token reuse, and isolation between
  two active sessions.
- OpenAPI: assert all six operations and their success responses are present.
- Durable Agent endpoints: assert all conversation and message operations are
  registered, resources are user-scoped, a new login continues an existing
  conversation, and CRUD-only requests never require model credentials.
- Agent user tools: assert the model cannot supply `user_id`, visible identity
  changes require explicit user intent, and internal profile text is not
  exposed by the REST user resource.

### 7. Wrong vs Correct

#### Wrong

```python
@router.post("/sessions")
def login(payload: dict) -> dict:
    return {"access_token": create_token(payload["password"])}
```

This bypasses schemas and services and derives a credential from a password.

#### Correct

```python
@router.post("", response_model=SessionCreated, status_code=201)
def login(
    payload: SessionCreate,
    response: Response,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionCreated:
    created = create_session(db, payload, settings.session_ttl_hours)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return SessionCreated(
        access_token=created.access_token,
        expires_at=created.expires_at,
        user=UserPublic.model_validate(created.user),
    )
```

The route owns HTTP details, while the service owns authentication and
persistence behavior.

---

## Scenario: Inspiration and Project Associations

Authenticated inspiration endpoints remain under the configured `/api/v1`
prefix:

```text
POST   /api/v1/inspirations
GET    /api/v1/inspirations
GET    /api/v1/inspirations/{inspiration_id}
PATCH  /api/v1/inspirations/{inspiration_id}
DELETE /api/v1/inspirations/{inspiration_id}
PUT    /api/v1/inspirations/{inspiration_id}/projects/{project_id}
DELETE /api/v1/inspirations/{inspiration_id}/projects/{project_id}
GET    /api/v1/projects/{project_id}/inspirations
```

`api/routes/inspirations.py` owns HTTP dependency and query-parameter wiring;
`schemas/inspirations.py` owns enums and payload/response contracts;
`services/inspirations.py` owns validation and transactions; and
`data/repositories/inspirations.py` owns SQLAlchemy queries without commits.

Project detail returns `ProjectDetail` with `inspiration_count`. Complete
inspiration rows are never embedded in project detail; callers use the
project-scoped paginated endpoint. Unknown and foreign UUIDs share the same
resource-specific 404.

Project and conversation DELETE routes accept
`delete_orphan_inspirations=false`. Services return a typed 409 impact response
before mutation when deletion would remove the last project and source. A
confirmed retry performs the target deletion and orphan cleanup in one
transaction.

Tests must cover authentication, user isolation, full and incremental project
links, combined filters/search/sort/pagination, OpenAPI registration, and both
blocked and confirmed deletion paths.
