# 灵感数据关联项目：技术设计

## 1. Architecture

沿用现有 FastAPI 分层，不在路由中直接查询或提交数据库：

```text
HTTP / Agent FunctionTool
        ↓
Pydantic schemas
        ↓
inspirations / projects / conversations services
        ↓
repositories
        ↓
SQLAlchemy models + SQLite
```

新增 `inspirations` 功能模块，并对项目、对话删除服务和 Agent 运行上下文做小范围扩展。所有写操作由服务层拥有事务；关联替换、删除影响确认和级联清理必须原子完成。

## 2. Data Model

### 2.1 `inspirations`

| Column | Type | Rules |
| --- | --- | --- |
| `id` | UUID | UUID v4 primary key |
| `user_id` | UUID | `users.id`, `ON DELETE CASCADE`, not null |
| `title` | `VARCHAR(120)` | nullable |
| `content` | `TEXT` | not null; API max 20,000 characters |
| `status` | `VARCHAR(32)` | `inbox/developing/converted/archived` check |
| `source_type` | `VARCHAR(16)` | `manual/agent/voice` check |
| `source_conversation_id` | UUID | nullable, `ON DELETE SET NULL` |
| `source_message_id` | UUID | nullable, `ON DELETE SET NULL` |
| `created_at` | `UTCDateTime` | not null |
| `updated_at` | `UTCDateTime` | not null |

Indexes:

- `ix_inspirations_user_id_updated_at(user_id, updated_at)`
- `ix_inspirations_user_id_status_updated_at(user_id, status, updated_at)`
- source conversation and source message indexes for deletion-impact queries

Title and content remain plaintext by product decision. Ownership checks still scope every query by `user_id`.

### 2.2 `inspiration_projects`

| Column | Type | Rules |
| --- | --- | --- |
| `inspiration_id` | UUID | `inspirations.id`, `ON DELETE CASCADE` |
| `project_id` | UUID | `projects.id`, `ON DELETE CASCADE` |

The two columns form the composite primary key. Add
`ix_inspiration_projects_project_id_inspiration_id` for project-first listing and deletion-impact queries. Services verify both resources belong to the authenticated user before inserting a link.

### 2.3 ORM relationships

- `User.inspirations`
- `Inspiration.user`
- `Inspiration.projects`
- `Project.inspirations`

Use `selectinload` for inspiration project summaries. Register the new model explicitly in `data/model_registry.py` and Alembic metadata.

## 3. Invariants

- Unknown and foreign inspiration/project IDs are indistinguishable to callers.
- Source message, when present, must belong to the source conversation and current user.
- Public manual/voice creation cannot forge an Agent conversation/message origin. Agent provenance comes from trusted `AgentRunContext`.
- An unassociated inspiration is allowed when it is created or explicitly returned to `inbox`.
- A project or conversation deletion may not silently turn a previously associated inspiration into an unassociated record.
- Replacing a complete project set validates all target projects before mutating any link.
- No-op patches preserve `updated_at`.

## 4. REST Contracts

### 4.1 Inspiration resources

| Method | Path | Result |
| --- | --- | --- |
| `POST` | `/api/v1/inspirations` | `201 InspirationPublic` |
| `GET` | `/api/v1/inspirations` | `200 InspirationPage` |
| `GET` | `/api/v1/inspirations/{id}` | `200 InspirationPublic` |
| `PATCH` | `/api/v1/inspirations/{id}` | `200 InspirationPublic` |
| `DELETE` | `/api/v1/inspirations/{id}` | `204` |
| `PUT` | `/api/v1/inspirations/{id}/projects/{project_id}` | idempotent add, `204` |
| `DELETE` | `/api/v1/inspirations/{id}/projects/{project_id}` | idempotent remove, `204` |
| `GET` | `/api/v1/projects/{project_id}/inspirations` | `200 InspirationPage` |

List query parameters:

- `project_id`
- `status`
- `source_type`
- `query`
- `sort_by=created_at|updated_at`
- `sort_order=asc|desc`
- `limit` from 1 through 100
- `offset` at least 0

`InspirationCreate` accepts title, content, optional status, public source type (`manual` or `voice`), and `project_ids`. `InspirationUpdate` accepts only supplied mutable fields and rejects an empty body. Provenance IDs are response-only at the public HTTP boundary.

`InspirationPublic.projects[]` contains `id`, `title`, and `icon_url`. The response also contains source IDs, status, source type, owner UUID, and timestamps.

### 4.2 Project response

Use a dedicated `ProjectDetail` schema extending the existing public project fields with `inspiration_count`. The list/create/update contracts remain compatible. `GET /projects/{id}` returns `ProjectDetail`.

### 4.3 Deletion confirmation

`DELETE /projects/{id}` and `DELETE /conversations/{id}` accept
`delete_orphan_inspirations=false` by default.

1. Service computes which linked inspirations would have neither another project nor a surviving source.
2. If the candidate list is non-empty and the flag is false, raise
   `409 orphaned_inspirations_confirmation_required`.
3. The response includes bounded safe details: inspiration UUID and nullable title.
4. After UI or Agent confirmation, retry with `delete_orphan_inspirations=true`.
5. Delete candidates and the target resource in one transaction.

The shared application error boundary will support safe instance-specific `details`; a dedicated response schema documents this conflict without weakening validation-error schemas.

## 5. Services and Repositories

### Inspirations

- create with validated owned project set
- get/list with user scope and eager project summaries
- patch scalar fields and optionally replace complete project set
- idempotent add/remove project link
- hard delete
- project-scoped list
- count by project
- compute deletion-orphan candidates

Search uses escaped SQL `LIKE`/`contains` predicates over title and content. Ordering always adds UUID as a deterministic tie-breaker.

### Projects

- Add an optional internal `inspiration_ids` argument to confirmed project creation so the new project and links commit atomically.
- Add project detail count.
- Extend delete to calculate and enforce orphan confirmation.
- Preserve existing behavior when no inspiration is affected.

### Conversations

- Extend conversation deletion to calculate source-linked orphan candidates before the existing memory cleanup.
- On confirmed deletion, retain inspirations with surviving project links and let source foreign keys become null; delete candidates without surviving links.
- Preserve existing protected/automatic memory deletion semantics in the same transaction.

## 6. Agent Design

Extend `AgentRunContext` with optional trusted `conversation_id` and
`source_message_id`. `run_conversation_turn` resolves the just-persisted user message before running the Agent and supplies these values. Direct Agent calls remain compatible with null provenance.

Add one FunctionTool module per tool:

- `create_inspiration`
- `list_inspirations`
- `get_inspiration`
- `update_inspiration`
- `delete_inspiration`
- `add_inspiration_project`
- `remove_inspiration_project`

Extend `create_project` with optional owned `inspiration_ids`; they appear in the confirmation preview and are linked only after confirmed creation. Extend `delete_project` preview with orphan impact and require its existing second-turn confirmation before setting the cascade flag.

`create_inspiration` saves immediately when called because the prompt itself controls the agreed automatic-capture threshold. `delete_inspiration` remains preview-first with `confirmed=false`. All expected failures use the existing safe tool envelope.

Update `DEFAULT_AGENT_INSTRUCTIONS` so the model:

- saves clear creative ideas and reports the result;
- asks before saving ambiguous discussion;
- uses current provenance automatically;
- manages project links without claiming success before tool output;
- lists cascade impact and waits for explicit deletion confirmation.

## 7. Errors

Add stable domain errors:

- `inspiration_not_found` — 404
- `inspiration_association_required` — 409 for a non-inbox unassociated state
- `orphaned_inspirations_confirmation_required` — 409 with safe impact details

Validation remains `422 validation_error`. Foreign project references use the existing `project_not_found`; foreign inspiration references use `inspiration_not_found`.

## 8. Migration and Compatibility

- Add revision `20260724_0007` after the project icon revision.
- Create `inspirations` before `inspiration_projects`; downgrade drops the join table first.
- Existing users, projects, conversations, messages and tools remain valid.
- Existing project create/list/update responses do not gain required request fields.
- Project detail adds one response field intentionally; OpenAPI and handoff docs record it.
- No environment variables or dependencies are required.

## 9. Operational and Security Notes

- SQLite foreign keys, WAL and bounded busy timeout remain unchanged.
- Do not keep a transaction open across a model call. Agent tool writes are short synchronous service operations executed only during the tool call.
- Keyword search is local and does not send inspiration content to an external search provider.
- SQLite backups contain readable inspiration titles and content; document this explicitly.
- Deletion confirmation limits accidental loss but is not a soft-delete or recovery mechanism.

## 10. Rollback

- Before deployment, downgrade `0007` removes only inspiration data and relations.
- After production data exists, back up SQLite before downgrade because the downgrade is destructive for this new feature.
- Code rollback is compatible only after downgrading or while old code ignores the additional tables and project detail response field.
