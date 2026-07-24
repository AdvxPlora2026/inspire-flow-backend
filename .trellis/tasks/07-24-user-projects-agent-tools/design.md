# User projects and Agent tools design

## Summary

Add one user-scoped `projects` resource and reuse its schemas/services from two
entry points: authenticated REST routes and Agent FunctionTools. Description
drafting uses a dedicated structured-output Agent that never receives mutation
tools. Saved-project tools receive ownership only through Agents SDK run
context, which is invisible to the model.

## Data model

Create `Project` in `data/models/project.py`:

```text
projects
  id          UUID primary key
  user_id     UUID foreign key users.id ON DELETE CASCADE
  title       VARCHAR(120) not null
  type        VARCHAR(50) not null
  audience    VARCHAR(500) not null
  summary     TEXT not null
  icon_url    VARCHAR(2048) null
  created_at  UTCDateTime not null
  updated_at  UTCDateTime not null
```

Add `ix_projects_user_id_updated_at` on `(user_id, updated_at)`. Add
`User.projects` with delete-orphan/passive-delete behavior and register
`Project` in `data/model_registry.py`.

Alembic revision `20260724_0005` follows `20260724_0004`, creates the table and
index on upgrade, and drops them on downgrade. Existing rows and tables are not
rewritten.

Revision `20260724_0006` adds nullable `projects.icon_url`. Existing projects
read as `null`; downgrade removes only the icon column and preserves projects.

## Shared schemas

`schemas/projects.py` owns all validation and public projections:

```python
class ProjectFields(BaseModel):
    title: str       # normalized, 1..120
    type: str        # normalized, 1..50
    audience: str    # normalized, 1..500
    summary: str     # normalized, 1..2000
    icon_url: HttpUrl | None  # <= 2048, null when unset


class ProjectDraftRequest(BaseModel):
    description: str  # normalized, 1..4000


class ProjectDraft(ProjectFields):
    pass


class ProjectCreate(ProjectFields):
    pass


class ProjectUpdate(BaseModel):
    title: str | None
    type: str | None
    audience: str | None
    summary: str | None
    icon_url: HttpUrl | None
    # at least one supplied; null is invalid except icon_url=null clears


class ProjectPublic(ProjectFields):
    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime


class ProjectPage(BaseModel):
    items: list[ProjectPublic]
    total: int
    limit: int
    offset: int
```

The same normalization owner is used by REST, model draft output, services,
and Agent tools. Routes and tools do not independently trim or bound strings.

## Repository and service boundary

`data/repositories/projects.py` owns:

```python
add_project(db, project)
get_project(db, user_id, project_id)
list_projects(db, user_id, limit, offset)
delete_project(db, project)
```

Every single-resource query includes both `Project.id` and `Project.user_id`.
The list query filters by owner and orders by `updated_at DESC, id DESC`.
Repositories never commit.

`services/projects.py` owns:

```python
create_project(db, user_id, payload) -> Project
get_project(db, user_id, project_id) -> Project
list_projects(db, user_id, limit, offset) -> ProjectPage
update_project(db, user_id, project_id, payload) -> Project
delete_project(db, user_id, project_id) -> None
draft_project(description, generator) -> ProjectDraft
```

Mutations commit once and refresh when returning an entity. A no-op patch
keeps `updated_at` unchanged; a changed patch sets `updated_at=utc_now()`.
Unknown and foreign UUIDs raise the same `ProjectNotFoundError`.

`draft_project()` performs no database operation. It delegates to a
`ProjectDraftGenerator` and maps expected SDK/provider/transport failures to
the existing `AgentRunFailedError`.

## REST contract

All routes require bearer authentication:

```text
POST   /api/v1/projects/drafts       -> 200 ProjectDraft
POST   /api/v1/projects              -> 201 ProjectPublic
GET    /api/v1/projects              -> 200 ProjectPage
GET    /api/v1/projects/{id}         -> 200 ProjectPublic
PATCH  /api/v1/projects/{id}         -> 200 ProjectPublic
DELETE /api/v1/projects/{id}         -> 204 empty body
```

The draft route injects `AgentRuntime` and uses only its
`project_draft_generator`. CRUD routes do not inject Agent runtime and remain
available when model configuration is absent.

## Structured project drafting

Add `services/agent/project_drafting.py`:

```python
class ProjectDraftGenerator(Protocol):
    async def generate(self, description: str) -> ProjectDraft: ...


class ModelProjectDraftGenerator:
    # Agent(name="InspireFlowProjectDrafter", output_type=ProjectDraft,
    #       tools=[], model=model)
```

Its instructions extract only supported fields, preserve user intent, use a
short normalized category, avoid invented claims, and return a concise draft.
The Agents SDK validates the structured output against `ProjectDraft`; no
free-form JSON parser is added.

`AgentRuntime` owns and closes one model client shared by the conversation
Agent, compactor, memory extractor, and project drafter.

## Trusted Agent run context

Add this non-model context in `services/agent/contracts.py`:

```python
@dataclass(frozen=True, slots=True)
class AgentRunContext:
    db: Session
    user_id: UUID
```

Extend `AgentRunner`, `OpenAIAgentRunner`, `AgentService.run()`, and
`ConversationAgent.run()` with `context: AgentRunContext | None`. The concrete
runner forwards it to `Runner.run(context=context)`.

`run_conversation_turn()` supplies:

```python
AgentRunContext(db=db, user_id=user.id)
```

The SDK does not send run context to the model. Each project tool receives
`RunContextWrapper[AgentRunContext | None]` as its first parameter, which is
removed from its JSON schema. No project tool accepts `user_id`.

## Agent tool contract

Add one module per tool under `services/agent/func/` and append them after the
existing tools in `func/registry.py`:

```text
create_project
list_projects
get_project
update_project
delete_project
```

Success payloads:

```json
{"ok":true,"status":"confirmation_required","draft":{...}}
{"ok":true,"status":"created","project":{...}}
{"ok":true,"projects":[...],"total":1}
{"ok":true,"project":{...}}
{"ok":true,"status":"confirmation_required","project":{"id":"...","title":"..."}}
{"ok":true,"status":"deleted","project_id":"..."}
```

Expected errors retain the existing envelope:

```json
{"ok":false,"error":{"code":"project_not_found","message":"Project not found"}}
{"ok":false,"error":{"code":"project_context_unavailable","message":"Authenticated project context is unavailable"}}
{"ok":false,"error":{"code":"invalid_project","message":"Project fields are invalid"}}
```

`create_project(..., confirmed=false)` returns a validated draft and performs
no insert. `confirmed=true` inserts. `delete_project(..., confirmed=false)`
fetches the owned project and returns its UUID/title without deleting;
`confirmed=true` deletes. The default prompt permits either confirmed call
only after a later user message explicitly confirms the displayed operation.
Project create accepts an optional `icon_url`. Project update accepts
`icon_url` plus `clear_icon`; `clear_icon=true` writes `null`, while omission
leaves the current icon unchanged.

The SDK's native `needs_approval` interruption is intentionally not used in
this MVP because the current HTTP conversation contract has no persisted
suspended-run token or approval-resume endpoint.

## Error and authorization matrix

| Condition | REST | Agent tool |
| --- | --- | --- |
| No bearer session | `401 invalid_session` | No authenticated run context |
| Unknown/foreign UUID | `404 project_not_found` | safe `project_not_found` JSON |
| Invalid fields | `422 validation_error` | safe `invalid_project` JSON |
| Missing model config on draft | `503 agent_unavailable` | not applicable |
| Expected draft model failure | `502 agent_run_failed` | not applicable |
| `confirmed=false` create/delete | no mutation | confirmation payload |
| Unexpected programming/database failure | propagate to server | propagate |

## Compatibility and rollback

- Existing routes, model settings, conversation storage, memory extraction,
  and three existing Agent tools keep their behavior.
- Project CRUD does not require model configuration; only draft generation
  does.
- Direct stateless Agent runs may omit context and retain date/web tools.
- Rollback disables project routes/tools in code, then downgrades revision
  `20260724_0005`. Downgrade permanently removes saved projects only.
