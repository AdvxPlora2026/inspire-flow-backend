# User projects and Agent tools implementation plan

## 1. Persistence and shared contracts

- [x] Write failing schema/model/service tests for normalized required fields,
      pagination order, no-op updates, user isolation, and delete behavior.
- [x] Add `Project` model, `User.projects`, repository, schemas, service, and
      `ProjectNotFoundError`.
- [x] Run the focused service/schema tests and refactor only after green.

Review gate:

```bash
uv run pytest tests/services/test_projects.py tests/schemas/test_projects.py -q
```

## 2. Migration

- [x] Extend migration tests first for the `projects` table, columns, index,
      foreign key cascade, upgrade from revision `20260724_0004`, and
      downgrade.
- [x] Add revision `20260724_0005`, update the ORM model registry, and make the
      migration tests green.

Review gate:

```bash
uv run pytest tests/data/test_migrations.py -q
```

Rollback point: downgrade `20260724_0005`; saved projects are removed.

## 3. Authenticated REST CRUD

- [x] Write failing API tests for unauthenticated requests, manual creation,
      list pagination/order, inspect, patch, delete, validation, OpenAPI, and
      identical missing/cross-user not-found responses.
- [x] Add the `/projects` router and compose it under `/api/v1`.
- [x] Make API tests green without introducing model runtime dependencies into
      CRUD routes.

Review gate:

```bash
uv run pytest tests/api/test_projects.py -q
```

## 4. Structured description drafts

- [x] Write failing unit/API tests using a fake `ProjectDraftGenerator`;
      assert the draft is normalized, has no resource fields, creates no row,
      and maps expected provider errors.
- [x] Add the generator protocol and model-backed structured-output Agent.
- [x] Add it to `AgentRuntime` and implement `POST /projects/drafts`.
- [x] Keep the stable suite provider-free.

Review gate:

```bash
uv run pytest tests/services/agent/test_project_drafting.py tests/api/test_projects.py -q
```

## 5. Trusted Agent context and tools

- [x] Write failing tests for context forwarding, exact tool names/order and
      schemas, absence of `user_id`, CRUD isolation, safe errors, create
      confirmation, and mandatory delete confirmation.
- [x] Add `AgentRunContext`, forward it through runner/service boundaries, and
      supply it from durable conversation turns.
- [x] Add one FunctionTool module per project operation and register them.
- [x] Update the default prompt and stable concept tests for draft/save and
      two-turn deletion.
- [x] Re-run existing Agent, conversation, memory, and tool suites.

Review gate:

```bash
uv run pytest tests/services/agent tests/services/test_conversations.py -q
```

## 6. Documentation and complete validation

- [x] Update README and add a project API/Agent handoff with placeholder
      credentials and request/response examples.
- [x] Run a fresh migration upgrade, downgrade one revision, and upgrade to
      head against a temporary SQLite file.
- [x] Run Trellis task validation, secret scan, diff check, and the complete
      quality suite.

Final gate:

```bash
python3 ./.trellis/scripts/task.py validate 07-24-user-projects-agent-tools
git diff --check
uv lock --check
uv sync --locked --dev
uv run ruff check .
uv run ruff format --check .
uv run pytest -W error -q
```

## Risk checks

- Never accept `user_id` in a project tool schema.
- Never persist `/projects/drafts` output.
- Never mutate on `confirmed=false`.
- Never let a cross-user UUID reveal that a project exists.
- Never make CRUD depend on model credentials.
- Never use a live provider or public network in automated tests.

## 7. Optional project icon

- [x] Write failing schema, service, API, migration, and Agent tool tests for
      unset, set, invalid, no-op, and cleared `icon_url`.
- [x] Add nullable `icon_url` through the shared project contract and revision
      `20260724_0006`; preserve existing rows on upgrade and downgrade.
- [x] Extend create/update Agent tools without exposing ownership or weakening
      confirmation behavior.
- [x] Update handoff/spec documentation and run the complete quality gate.
