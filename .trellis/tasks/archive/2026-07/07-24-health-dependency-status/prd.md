# Expand Backend Health Checks

## Goal

Expand the existing health endpoint so the iOS app and demo operator can see
whether the backend and its important dependencies are ready, without changing
the existing `/api/v1` API prefix.

## Background

- `GET /api/v1/health` currently returns static service and environment
  metadata with `status="ok"`.
- SQLite/SQLAlchemy is already configured and can be checked with a lightweight
  query.
- The Chat Completions runtime is configured through `MODEL_API_KEY`,
  `MODEL_NAME`, and `MODEL_BASE_URL`.
- Injective has not been integrated or configured yet.
- The frontend handoff expects top-level status, per-service database/model/
  Injective status, and a deployable version identifier.

## Requirements

1. Keep the endpoint at `GET /api/v1/health`.
2. Return a typed JSON response containing:
   - top-level `status`
   - `services.database`
   - `services.model`
   - `services.injective`
   - `version`
3. Do not expose provider URLs, credentials, exception messages, or other
   sensitive configuration.
4. Check the database through the existing request-owned SQLAlchemy session.
5. Check model readiness locally: report `ok` only when `MODEL_API_KEY`,
   `MODEL_NAME`, and `MODEL_BASE_URL` are all configured; do not make a
   provider request.
6. Report Injective as `not_configured` until its client and configuration
   exist; do not add placeholder RPC behavior.
7. Use bounded, deterministic dependency checks so health requests cannot hang.
8. Add `APP_VERSION`, defaulting to `dev`, so deployments can inject a Git SHA
   or release identifier.
9. Use these statuses:
   - top level: `ok | degraded | unavailable`
   - database: `ok | unavailable`
   - model: `ok | not_configured`
   - Injective: `not_configured`
10. Return HTTP `200` when the database is healthy, including when optional
    model or Injective dependencies make the top-level state `degraded`.
11. Return HTTP `503` with top-level `unavailable` when the database check
    fails.
12. Preserve the standard health response schema for both `200` and `503`;
    dependency failures are health data, not the general API error envelope.
13. Update settings, `.env.example`, README, executable backend spec, and API
    tests for this contract.

## Acceptance Criteria

- [x] `/api/v1/health` remains the only health endpoint.
- [x] A working database produces `services.database="ok"`.
- [x] An unavailable database returns HTTP `503`, top-level
      `status="unavailable"`, and `services.database="unavailable"` without
      leaking its exception.
- [x] Complete `MODEL_*` configuration produces `services.model="ok"`; any
      missing model value produces `services.model="not_configured"`.
- [x] `services.injective` is `not_configured` in this iteration.
- [x] Any optional dependency that is not `ok` produces top-level
      `status="degraded"` while retaining HTTP `200`.
- [x] `version` defaults to `dev` and follows `APP_VERSION` when injected.
- [x] Tests cover healthy, degraded, and core-unavailable cases.
- [x] Ruff, formatting, and the complete pytest suite pass without warnings.

## Key Decisions

- Health checks are lightweight and deterministic. They do not spend model
  tokens or depend on public network availability.
- Database availability is critical because the core authenticated API cannot
  operate without persistence.
- Model and Injective are optional for HTTP availability, so their failure
  degrades the response but does not produce HTTP `503`.
- The endpoint stays at `/api/v1/health`; no API-prefix migration occurs.
- This is a lightweight cross-layer change and needs only this PRD.

## Out of Scope

- Moving APIs from `/api/v1` to `/v1`.
- Implementing Injective transactions, RPC clients, wallets, or an outbox.
- Generating content through the model as part of normal business behavior.
- Adding a general observability stack or metrics exporter.
