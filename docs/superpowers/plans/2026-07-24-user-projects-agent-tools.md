# User Projects and Agent Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `test-driven-development` and execute this plan task-by-task. Trellis inline
> mode owns implementation, review, and the final batched commit in Phase 3.4.

**Goal:** Add authenticated user projects, non-persisted Agent-generated
drafts, and user-bound Agent tools for project CRUD.

**Architecture:** A shared Project schema/service layer serves both FastAPI
routes and Agent FunctionTools. The model receives no owner identifier;
request-owned `AgentRunContext` carries the SQLAlchemy session and authenticated
UUID through the Agents SDK. A dedicated structured-output Agent creates
drafts without mutation tools or database access.

**Tech Stack:** Python 3.13, FastAPI, Pydantic 2, SQLAlchemy 2, SQLite,
Alembic, OpenAI Agents SDK, pytest, Ruff, uv.

---

### Task 1: Project schemas and service lifecycle

**Files:**

- Create: `src/inspire_flow_backend/schemas/projects.py`
- Create: `src/inspire_flow_backend/data/models/project.py`
- Create: `src/inspire_flow_backend/data/repositories/projects.py`
- Create: `src/inspire_flow_backend/services/projects.py`
- Modify: `src/inspire_flow_backend/data/models/user.py`
- Modify: `src/inspire_flow_backend/core/errors.py`
- Create: `tests/services/test_projects.py`

- [ ] **Step 1: Write the failing lifecycle and isolation tests**

```python
def test_project_lifecycle_and_user_isolation(db: Session) -> None:
    owner = add_user(db, "owner")
    other = add_user(db, "other")
    created = create_project(
        db,
        owner.id,
        ProjectCreate(
            title="  MPS 实测  ",
            type=" 科技数码 ",
            audience=" Mac 用户 ",
            summary=" 在本地运行语音识别 ",
        ),
    )

    assert created.title == "MPS 实测"
    assert list_projects(db, owner.id, limit=20, offset=0).total == 1
    with pytest.raises(ProjectNotFoundError):
        get_project(db, other.id, created.id)

    updated = update_project(
        db,
        owner.id,
        created.id,
        ProjectUpdate(summary="补充性能对比"),
    )
    assert updated.summary == "补充性能对比"
    delete_project(db, owner.id, created.id)
    with pytest.raises(ProjectNotFoundError):
        get_project(db, owner.id, created.id)
```

Add a second test that captures `updated_at`, performs a patch with the same
value, and asserts the timestamp is unchanged. Add schema parameterized tests
for blank and over-limit values and for an empty/null patch.

- [ ] **Step 2: Run the focused test and verify RED**

```bash
uv run pytest tests/services/test_projects.py -q
```

Expected: collection fails because `schemas.projects` and
`services.projects` do not exist.

- [ ] **Step 3: Add the shared schemas**

Implement a single normalization helper and reuse it through annotated field
validators:

```python
def _normalize_required(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Project field cannot be blank")
    return normalized


class ProjectFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    type: str = Field(min_length=1, max_length=50)
    audience: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1, max_length=2_000)

    _normalize_fields = field_validator(
        "title", "type", "audience", "summary", mode="before"
    )(_normalize_required)
```

`ProjectUpdate` declares the four fields as nullable defaults, rejects an empty
`model_fields_set`, rejects every supplied `None`, and normalizes every
supplied string. `ProjectPublic` uses `ConfigDict(from_attributes=True)`.

- [ ] **Step 4: Add model, repository, service, and domain error**

Use this model shape:

```python
class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_user_id_updated_at", "user_id", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    audience: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now
    )
    user: Mapped["User"] = relationship(back_populates="projects")
```

The repository's single-row query must be:

```python
select(Project).where(Project.id == project_id, Project.user_id == user_id)
```

The list query orders by `Project.updated_at.desc(), Project.id.desc()`.
Services add/commit/refresh on create, compare supplied patch values before
changing `updated_at`, and commit once per mutation.

Add:

```python
class ProjectNotFoundError(ApplicationError):
    status_code = 404
    code = "project_not_found"
    message = "Project was not found"
```

- [ ] **Step 5: Run and verify GREEN**

```bash
uv run pytest tests/services/test_projects.py -q
uv run ruff check src/inspire_flow_backend/{schemas/projects.py,data/models/project.py,data/repositories/projects.py,services/projects.py} tests/services/test_projects.py
```

Expected: all focused tests and lint checks pass.

### Task 2: Reversible project migration

**Files:**

- Create: `migrations/versions/20260724_0005_add_projects.py`
- Modify: `src/inspire_flow_backend/data/model_registry.py`
- Modify: `tests/data/test_migrations.py`
- Modify: `tests/api/conftest.py`

- [ ] **Step 1: Extend migration tests first**

Add `"projects"` to a `PROJECT_TABLES` set and assert these columns:

```python
{
    "id", "user_id", "title", "type", "audience", "summary",
    "created_at", "updated_at",
}
```

Assert index `ix_projects_user_id_updated_at`, foreign key
`projects.user_id -> users.id ON DELETE CASCADE`, and that downgrade to
`20260724_0004` removes only `projects`.

- [ ] **Step 2: Run migration tests and verify RED**

```bash
uv run pytest tests/data/test_migrations.py -q
```

Expected: `projects` is absent at Alembic head.

- [ ] **Step 3: Add revision `20260724_0005`**

The upgrade creates the complete table and index:

```python
op.create_table(
    "projects",
    sa.Column("id", sa.Uuid(native_uuid=False), nullable=False),
    sa.Column("user_id", sa.Uuid(native_uuid=False), nullable=False),
    sa.Column("title", sa.String(length=120), nullable=False),
    sa.Column("type", sa.String(length=50), nullable=False),
    sa.Column("audience", sa.String(length=500), nullable=False),
    sa.Column("summary", sa.Text(), nullable=False),
    sa.Column("created_at", sa.DateTime(), nullable=False),
    sa.Column("updated_at", sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(
        ["user_id"], ["users.id"],
        name=op.f("fk_projects_user_id_users"), ondelete="CASCADE",
    ),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
)
op.create_index(
    "ix_projects_user_id_updated_at",
    "projects",
    ["user_id", "updated_at"],
)
```

Downgrade drops the index and table. Import and assert `Project` in
`register_models()`. Import `Project` in the API test fixture and include its
table in the metadata assertion.

- [ ] **Step 4: Run migration and mapper tests**

```bash
uv run pytest tests/data/test_migrations.py tests/workers/test_stt_tasks.py -q
```

Expected: migration and isolated mapper registration tests pass.

### Task 3: Authenticated Project REST API

**Files:**

- Create: `src/inspire_flow_backend/api/routes/projects.py`
- Modify: `src/inspire_flow_backend/api/router.py`
- Create: `tests/api/test_projects.py`

- [ ] **Step 1: Write failing endpoint tests**

Cover:

```python
response = client.post(
    "/api/v1/projects",
    headers=authorization(token),
    json={
        "title": "MPS 实测",
        "type": "科技数码",
        "audience": "Mac 用户",
        "summary": "在本地运行语音识别",
    },
)
assert response.status_code == 201
project_id = UUID(response.json()["id"])
```

Also assert missing bearer `401`, owner list includes the project, another
user's list excludes it, cross-user GET/PATCH/DELETE each return the exact same
`404 project_not_found` body as an unknown UUID, empty patch returns `422`,
delete returns an empty `204`, and OpenAPI exposes all operations.

- [ ] **Step 2: Run and verify RED**

```bash
uv run pytest tests/api/test_projects.py -q
```

Expected: `/api/v1/projects` returns `404`.

- [ ] **Step 3: Add route functions and composition**

Each CRUD route injects `AuthenticatedSession` and `Session`, delegates once to
`services.projects`, and returns `ProjectPublic.model_validate(...)`. The list
route uses:

```python
limit: Annotated[int, Query(ge=1, le=100)] = 50
offset: Annotated[int, Query(ge=0)] = 0
```

Compose with:

```python
api_router.include_router(projects_router, prefix="/projects", tags=["projects"])
```

- [ ] **Step 4: Run and verify GREEN**

```bash
uv run pytest tests/api/test_projects.py -q
```

Expected: all Project CRUD and authorization tests pass.

### Task 4: Structured description drafting

**Files:**

- Create: `src/inspire_flow_backend/services/agent/project_drafting.py`
- Modify: `src/inspire_flow_backend/services/agent/runtime.py`
- Modify: `src/inspire_flow_backend/services/projects.py`
- Modify: `src/inspire_flow_backend/api/routes/projects.py`
- Create: `tests/services/agent/test_project_drafting.py`
- Modify: `tests/api/conftest.py`
- Modify: `tests/api/test_projects.py`

- [ ] **Step 1: Write fake-generator tests first**

```python
class FakeProjectDraftGenerator:
    async def generate(self, description: str) -> ProjectDraft:
        assert description == "做一期本地语音识别视频"
        return ProjectDraft(
            title="本地语音识别实测",
            type="科技数码",
            audience="希望保护隐私的创作者",
            summary="对比本地部署的速度和效果",
        )
```

Call `POST /api/v1/projects/drafts`, assert exact four-field response, then
query/count projects and assert zero. Add provider failure and missing model
configuration contract tests.

- [ ] **Step 2: Run and verify RED**

```bash
uv run pytest tests/services/agent/test_project_drafting.py tests/api/test_projects.py -q
```

Expected: the generator and draft route are missing.

- [ ] **Step 3: Implement the dedicated structured-output Agent**

```python
class ProjectDraftGenerator(Protocol):
    async def generate(self, description: str) -> ProjectDraft: ...


class ModelProjectDraftGenerator:
    def __init__(self, *, model: Model) -> None:
        self._agent = Agent(
            name="InspireFlowProjectDrafter",
            instructions=PROJECT_DRAFT_INSTRUCTIONS,
            model=model,
            tools=[],
            output_type=ProjectDraft,
        )
        self._runner = OpenAIAgentRunner()

    async def generate(self, description: str) -> ProjectDraft:
        result = await self._runner.run(self._agent, description, max_turns=2)
        output = result.final_output
        if not isinstance(output, ProjectDraft):
            raise ModelBehaviorError("Project drafter returned an invalid output")
        return output
```

Add the generator to `AgentRuntime`; construct it from the shared model in
`create_agent_runtime()`. `draft_project()` catches `AgentsException`,
`openai.APIError`, and `httpx.HTTPError`, then raises `AgentRunFailedError`.

- [ ] **Step 4: Add `POST /projects/drafts`**

The route must inject authentication, runtime, and no database session:

```python
@router.post("/drafts", response_model=ProjectDraft)
async def create_project_draft(
    payload: ProjectDraftRequest,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    runtime: Annotated[AgentRuntime, Depends(get_agent_runtime)],
) -> ProjectDraft:
    del authenticated
    return await draft_project(payload.description, runtime.project_draft_generator)
```

- [ ] **Step 5: Run and verify GREEN**

```bash
uv run pytest tests/services/agent/test_project_drafting.py tests/api/test_projects.py -q
```

Expected: draft output is typed, provider-free in tests, and never persisted.

### Task 5: Trusted Agent context and Project tools

**Files:**

- Modify: `src/inspire_flow_backend/services/agent/contracts.py`
- Modify: `src/inspire_flow_backend/services/agent/agent.py`
- Modify: `src/inspire_flow_backend/services/agent/runtime.py`
- Modify: `src/inspire_flow_backend/services/agent/conversation.py`
- Create: `src/inspire_flow_backend/services/agent/func/create_project.py`
- Create: `src/inspire_flow_backend/services/agent/func/list_projects.py`
- Create: `src/inspire_flow_backend/services/agent/func/get_project.py`
- Create: `src/inspire_flow_backend/services/agent/func/update_project.py`
- Create: `src/inspire_flow_backend/services/agent/func/delete_project.py`
- Modify: `src/inspire_flow_backend/services/agent/func/registry.py`
- Modify: `tests/services/agent/test_agent.py`
- Modify: `tests/services/agent/test_tools.py`
- Modify: `tests/services/agent/test_conversation.py`

- [ ] **Step 1: Write context-forwarding and schema tests**

Assert exact tool order:

```python
[
    "current_datetime", "search_website", "fetch_webpage",
    "create_project", "list_projects", "get_project",
    "update_project", "delete_project",
]
```

Assert `"user_id"` is absent from every project tool schema. Assert the fake
runner receives `AgentRunContext(db=db, user_id=user.id)` from
`run_conversation_turn()`.

- [ ] **Step 2: Write mutation-confirmation tests**

Invoke `create_project` with `confirmed=false`, assert
`status=="confirmation_required"` and no row. Invoke with `true`, assert one
owned row. For delete, invoke false, assert returned UUID/title and the row
still exists; invoke true, assert `status=="deleted"` and the row is gone.
Invoke owner tools with another user's UUID and assert `project_not_found`.

- [ ] **Step 3: Run and verify RED**

```bash
uv run pytest tests/services/agent/test_agent.py tests/services/agent/test_tools.py tests/services/agent/test_conversation.py -q
```

Expected: project tools and Agent run context are missing.

- [ ] **Step 4: Forward trusted context**

Add:

```python
@dataclass(frozen=True, slots=True)
class AgentRunContext:
    db: Session
    user_id: UUID
```

Add `context: AgentRunContext | None = None` to `AgentService.run()`,
`AgentRunner.run()`, `OpenAIAgentRunner.run()`, and the runtime protocol.
Forward it to `Runner.run(context=context)`. In durable turns call:

```python
await runtime.conversation_agent.run(
    [],
    context=AgentRunContext(db=db, user_id=user.id),
    session=session,
    run_config=run_config,
)
```

- [ ] **Step 5: Implement tools with stable JSON**

Each tool's first parameter is:

```python
ctx: RunContextWrapper[AgentRunContext | None]
```

The model-visible parameters never include context. `create_project` validates
with `ProjectCreate`; false confirmation returns `ProjectDraft`, true calls the
service. `delete_project` fetches the owned project first; false returns only
its ID/title, true calls the service. Catch only `ProjectNotFoundError` and
Pydantic `ValidationError` for stable model-facing errors. Let unexpected
database/programming defects propagate.

- [ ] **Step 6: Update prompt and registration**

Append the five factories in the specified order. Update
`DEFAULT_AGENT_INSTRUCTIONS` to require draft-first creation, explicit save
confirmation, no cross-user assumptions, and a separate explicit confirmation
turn before deletion. Extend concept tests without copying the complete
prompt.

- [ ] **Step 7: Run and verify GREEN**

```bash
uv run pytest tests/services/agent tests/services/test_conversations.py -q
```

Expected: all Agent, context, confirmation, and existing tool tests pass.

### Task 6: Documentation, migrations, and full quality gate

**Files:**

- Modify: `README.md`
- Create: `docs/HANDOFF_PROJECTS.md`
- Modify: `.trellis/spec/backend/directory-structure.md`
- Modify: `.trellis/spec/backend/database-guidelines.md`
- Modify: `.trellis/spec/backend/error-handling.md`
- Modify: `.trellis/spec/backend/agent-tools.md`

- [ ] **Step 1: Add handoff examples**

Document login-variable setup, description draft, draft editing, manual save,
list/get/patch/delete, response/error shapes, Agent tool names, the two-turn
create/delete rules, and the fact that drafts are not persisted. Use
`$ACCESS_TOKEN` placeholders only.

- [ ] **Step 2: Run reversible migration smoke**

```bash
DB_FILE=$(mktemp /tmp/inspire-flow-projects-XXXXXX.db)
APP_DATABASE_URL="sqlite:///$DB_FILE" uv run alembic upgrade head
APP_DATABASE_URL="sqlite:///$DB_FILE" uv run alembic downgrade 20260724_0004
APP_DATABASE_URL="sqlite:///$DB_FILE" uv run alembic upgrade head
```

Expected: each command exits zero. Remove the explicit temporary file after
the smoke.

- [ ] **Step 3: Run final checks**

```bash
python3 ./.trellis/scripts/task.py validate 07-24-user-projects-agent-tools
git diff --check
uv lock --check
uv sync --locked --dev
uv run ruff check .
uv run ruff format --check .
uv run pytest -W error -q
```

Expected: task manifests validate, no whitespace errors, lockfile resolves,
Ruff passes, formatting is unchanged, and the complete warning-strict test
suite passes.

- [ ] **Step 4: Prepare Trellis Phase 3.4 commits**

Inspect all dirty paths, separate unexpected work, and propose coherent
Git-style messages to the user. Do not commit or push until the Phase 3.4
confirmation.
