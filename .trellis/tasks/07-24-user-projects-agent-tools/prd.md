# User projects and Agent project tools

## Goal

Add a user-owned Project resource so an authenticated Bilibili creator can
turn a natural-language description into an editable draft, explicitly save
that draft as a project, and manage saved projects through REST or InspireFlow.

## Background

- The backend uses `/api/v1`, bearer authentication, UUID identifiers,
  SQLAlchemy, SQLite, Alembic, Pydantic response models, and service-owned
  transactions.
- Existing user-scoped resources return not-found for missing and cross-user
  identifiers.
- The conversation Agent currently has date, web-search, and webpage-fetch
  tools. Its run API can carry trusted SDK context that is not shown to the
  model.
- Project ownership must come only from the authenticated run context; model
  input must never choose or override `user_id`.

## Requirements

### Project data

- Persist projects with UUID `id`, owner `user_id`, `title`, video-like
  `type`, target `audience`, `summary`, and UTC `created_at` / `updated_at`.
- Require all four content fields and normalize surrounding whitespace.
- Apply these bounds after normalization:
  - `title`: 1 through 120 characters
  - `type`: 1 through 50 characters
  - `audience`: 1 through 500 characters
  - `summary`: 1 through 2,000 characters
- Store `type` as normalized free-form text rather than a closed enum. Clients
  and the Agent may suggest common Bilibili-like categories without changing
  the database contract.
- Cascade project deletion when its owning user is deleted.

### Authenticated REST API

- Add these bearer-authenticated operations under `/api/v1/projects`:
  - `POST /drafts` generates but does not persist a project draft from a
    description of 1 through 4,000 normalized characters.
  - `POST /` saves a manually supplied or user-edited draft and returns `201`.
  - `GET /` returns the current user's projects ordered by most recently
    updated, with `limit` and `offset` pagination.
  - `GET /{project_id}` returns one owned project.
  - `PATCH /{project_id}` edits one or more supplied content fields.
  - `DELETE /{project_id}` permanently deletes an owned project and returns
    `204`.
- The draft response contains `title`, `type`, `audience`, and `summary`, but
  no UUID or timestamps because it is not a stored resource.
- Saved-project reads and mutations scope by both authenticated `user_id` and
  project UUID. Missing and cross-user UUIDs use one safe
  `project_not_found` response.
- Unknown fields, blank content, overlong content, empty patches, and explicit
  `null` values return the existing safe validation envelope.
- Model configuration and provider failures use the existing
  `agent_unavailable` and `agent_run_failed` contracts.

### InspireFlow tools

- Register stable Agent tools in this order after the existing tools:
  `create_project`, `list_projects`, `get_project`, `update_project`,
  `delete_project`.
- Pass a trusted request-owned database session and authenticated user UUID
  through Agents SDK run context. Do not expose `user_id` in tool schemas.
- Return stable JSON success/error payloads and never expose ORM or database
  exception text.
- `create_project` follows a two-turn flow:
  - `confirmed=false` validates and returns a project draft without saving.
  - only a later explicit user confirmation allows `confirmed=true` to save.
- `delete_project` follows a mandatory two-turn flow:
  - `confirmed=false` returns the matched project's UUID/title and asks for
    confirmation without deleting.
  - only a later explicit user confirmation allows `confirmed=true` to delete.
- `update_project` may edit a saved project when the user explicitly requests
  the change; it does not require an additional confirmation turn.
- Direct stateless Agent runs without authenticated project context keep
  existing non-project tools usable; project tools return a safe unavailable
  result if invoked.
- Update the default InspireFlow instructions to state the draft/save rule,
  user isolation, truthful tool-result reporting, and mandatory two-turn
  deletion confirmation.

### Persistence and quality

- Add a reversible Alembic migration after revision `20260724_0004`.
- Register the Project model in the explicit ORM model registry.
- Add migration, service, API, Agent tool, runtime-context, authorization, and
  user-isolation tests.
- Automated tests use fake draft generators and runners; they do not call a
  live model provider or public network.

## Acceptance Criteria

- [x] An authenticated user can generate a normalized draft from a description
      and no project row is created.
- [x] The user can edit that draft client-side, save it through `POST
      /api/v1/projects`, and later edit the saved project through `PATCH`.
- [x] Manual create, list, inspect, edit, and delete return the documented
      typed responses and pagination.
- [x] All project endpoints reject unauthenticated callers with `401`.
- [x] Missing and cross-user project UUIDs return identical `404
      project_not_found` responses.
- [x] InspireFlow exposes all five project tools after its existing tools.
- [x] Project tool schemas contain no `user_id`, and tool operations affect
      only the authenticated run-context owner.
- [x] Agent create and delete calls with `confirmed=false` do not mutate the
      database; their confirmed follow-up calls do.
- [x] Existing Agent date/web tools, conversations, memory, and direct
      stateless runs remain compatible.
- [x] Alembic upgrades an existing `20260724_0004` database without altering
      existing rows, enforces user cascade, and cleanly downgrades.
- [x] uv lock, Ruff, formatting, warning-strict pytest, and migration checks
      pass.

## Out of Scope

- Project collaborators, permissions, budgets, revenue sharing, assets,
  scripts, storyboards, and publishing workflows.
- Persisted draft rows, draft UUIDs, draft history, or draft expiration.
- Soft deletion, project restoration, project version history, and audit logs.
- Public projects, cross-user sharing, filtering, full-text search, and custom
  sort options.
- Resumable Agents SDK approval interruptions or a general approval UI.
- Live provider calls in the automated test suite.
