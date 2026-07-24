# 灵感数据关联项目：实施计划

## Phase 1 — Tests and persistence contract

- [x] Add failing migration tests for revision `20260724_0007`: tables, columns, checks, indexes, foreign keys, user cascade, source `SET NULL`, join cascade, upgrade from `0006`, and downgrade.
- [x] Add failing model/repository tests for UUID ownership, many-to-many uniqueness, eager project summaries, count, filters, keyword search, stable sorting and pagination.
- [x] Implement `Inspiration` and the association table, update user/project relationships and explicit model registration.
- [x] Add the reversible Alembic revision.

## Phase 2 — Schemas, services and errors

- [x] Add failing schema tests for trimmed content/title, lengths, enum values, empty patch rejection, project summaries, pages and deletion-impact response.
- [x] Add `schemas/inspirations.py` and the project-detail extension.
- [x] Add stable inspiration and orphan-confirmation domain errors with safe dynamic details.
- [x] Add failing service tests for create/get/list/update/delete, no-op timestamps, full association replacement, idempotent incremental links, foreign ownership and atomic validation.
- [x] Implement `repositories/inspirations.py` and `services/inspirations.py`; repositories never commit and services commit once per mutation.

## Phase 3 — REST API

- [x] Add failing authenticated API tests for every inspiration route, missing/revoked credentials, cross-user 404 behavior, validation and combined query parameters.
- [x] Add `api/routes/inspirations.py` and register it under `/api/v1/inspirations`.
- [x] Add project-scoped inspiration listing and `ProjectDetail.inspiration_count`.
- [x] Assert OpenAPI success/error models and that no alternate `/v1` routes appear.

## Phase 4 — Safe project and conversation deletion

- [x] Add failing service/API tests for deletion with no affected inspiration, surviving alternate project/source links, blocked orphan creation, bounded impact details and confirmed atomic cascade.
- [x] Extend project deletion with `delete_orphan_inspirations`.
- [x] Extend conversation deletion without regressing existing automatic/protected memory cleanup.
- [x] Cover transaction rollback so a failed cascade leaves the project/conversation, inspirations and links unchanged.

## Phase 5 — Agent context and FunctionTools

- [x] Add failing tests that durable turns pass current conversation and user-message provenance while direct runs remain compatible.
- [x] Extend `AgentRunContext` and durable turn composition.
- [x] Add one module per inspiration tool and register them in a stable tested order.
- [x] Test exact tool schemas, user isolation, invalid UUID behavior, filters, full/incremental linking, immediate clear-idea creation and preview-first deletion.
- [x] Extend `create_project` to preview and atomically link optional `inspiration_ids` after confirmation.
- [x] Extend `delete_project` preview to list orphan impact and require explicit confirmed cascade.
- [x] Update prompt tests, then update `DEFAULT_AGENT_INSTRUCTIONS` for automatic clear-idea capture, ambiguous-content confirmation, provenance, link management and deletion boundaries.

## Phase 6 — Documentation and project specs

- [x] Add `HANDOFF_INSPIRATIONS.md` with authentication, CRUD, query, association and deletion-confirmation examples.
- [x] Document Agent tool names and behavior, project detail changes, nullable source fields and plaintext SQLite storage.
- [x] Update `.trellis/spec/backend/database-guidelines.md`, `directory-structure.md`, `error-handling.md` and `agent-tools.md` with the implemented contracts.

## Validation

Run focused tests during each red-green-refactor cycle, then:

```bash
uv lock --check
uv sync --locked --dev
uv run ruff check .
uv run ruff format --check .
uv run pytest -W error
```

Also run a local authenticated smoke flow:

1. Register and log in.
2. Create an unassociated inbox inspiration.
3. Create two projects and associate both.
4. Search and filter the inspiration list.
5. Verify both project counts and project-scoped lists.
6. Remove one link.
7. Attempt to delete the final linked project, observe the confirmation conflict, then confirm cascade.
8. Run a fake-model durable Agent turn and verify source provenance without a public network call.

## Risky Files and Rollback Points

- `services/conversations.py`: preserve memory deletion/tombstone behavior while adding inspiration impact handling.
- `services/projects.py`: keep current project API and Agent confirmation behavior compatible.
- `services/agent/conversation.py`: resolve provenance without changing message sequence, encryption or run-lock semantics.
- `core/errors.py`: add dynamic safe details without exposing validation inputs or arbitrary exceptions.
- Migration `0007`: verify upgrade/downgrade against fresh and `0006` databases before any real data migration.

## Pre-start Check

- [x] Latest planning summary has been presented.
- [x] User has explicitly approved that summary in a subsequent message.
- [x] Run `trellis-before-dev` and load the backend database, directory, error, quality and Agent tool specs before editing product code.
- [x] Start the task with `task.py start` only after approval.
