# Brand project AI advisor implementation plan

## 1. Typed contracts and deterministic finalizer

- [x] Write failing schema tests for request normalization, list limits,
      evidence/recommendation cross-references, confidence enums, and report
      serialization.
- [x] Add `schemas/advisory.py` with request, draft, evidence, reasoning,
      recommendation, scope, and public report models.
- [x] Write failing unit tests for extracting the evidence ledger from synthetic
      Agent run items including mapping-backed SDK raw items, URL deduplication,
      tool-grounded public excerpts, freshness, domain counts, fabricated
      citations, sufficiency, and confidence downgrade/rejection.
- [x] Implement the deterministic evidence finalizer before model integration.

Review gate:

```bash
uv run pytest tests/services/agent/test_brand_advisor.py -q
```

## 2. Publication metadata and research tools

- [x] Write failing fetch tests for `article:published_time`, JSON-LD
      `datePublished`, `<time datetime>`, timezone normalization, ambiguous
      metadata, and unchanged SSRF/size behavior.
- [x] Add nullable `published_at` to `FetchResponse` and HTML metadata parsing.
- [x] Keep search/fetch tool schemas bounded and update exact shared tool tests.

Review gate:

```bash
uv run pytest tests/services/agent/test_web_fetch.py tests/services/agent/test_tools.py -q
```

## 3. Model-backed Advisor Agent

- [x] Write failing tests with a fake `AgentRunner` for tool availability,
      structured output, bounded turns, tool-output extraction, malformed model
      output, and fabricated citations.
- [x] Implement `BrandAdvisor` and `ModelBrandAdvisor` with search/fetch only.
- [x] Add safe prompt construction from validated brand/project context and map
      expected SDK/provider failures at the service boundary.

Review gate:

```bash
uv run pytest tests/services/agent/test_brand_advisor.py -q
```

## 4. Shared service and HTTP API

- [x] Write failing service tests for member access, owner parity, non-member
      404 behavior, optional owned project enrichment, cross-user project 404,
      explicit-brief precedence, and no database writes.
- [x] Implement `services/advisory.py` with brand/project authorization and
      Agent delegation.
- [x] Write failing API tests for authentication, validation, typed success,
      weak/provider-failure reports, 404 isolation, 502/503 mapping,
      idempotency replay, and OpenAPI.
- [x] Add `api/routes/advisory.py` and compose
      `POST /brands/{brand_id}/advisory-reports`.

Review gate:

```bash
uv run pytest tests/services/test_advisory.py tests/api/test_advisory.py -q
```

## 5. Conversation Agent tools and runtime

- [x] Write failing tests for exact appended tool names/order and schemas,
      hidden `user_id`, brand listing isolation, advisory delegation, safe tool
      errors, and Agent instruction concepts.
- [x] Add `list_brands` and `analyze_brand_project` FunctionTool modules and
      shared safe error formatters.
- [x] Add the Advisor to `AgentRuntime`, share/close outbound dependencies
      exactly once, and register the tools in the conversation Agent.
- [x] Update default instructions without weakening existing creator, project,
      memory, or untrusted-web rules.

Review gate:

```bash
uv run pytest tests/services/agent tests/services/test_conversations.py -q
```

## 6. Documentation and complete validation

- [x] Update `.trellis/spec/backend/agent-tools.md`, directory/error contracts,
      and API handoff documentation with the new route, report semantics,
      evidence threshold, idempotency behavior, and future upgrade boundary.
- [x] Confirm no migration or advisory-history table was introduced.
- [x] Run task validation, secret scan, diff checks, formatting, lint, focused
      tests, and the full warning-strict suite.

Final gate:

```bash
python3 ./.trellis/scripts/task.py validate 07-25-brand-project-ai-advisor
git diff --check
uv lock --check
uv sync --locked --dev
uv run ruff check .
uv run ruff format --check .
uv run pytest -W error -q
```

## Risk and rollback checks

- Never accept `user_id` from HTTP payloads or Agent tool arguments.
- Never expose brand/project data before membership/ownership checks.
- Never accept a citation absent from actual tool output.
- Never allow weak evidence to produce high confidence.
- Never hold a database transaction open during model or web calls.
- Never use a live model, DNS resolver, or public provider in stable tests.
- Rollback removes the route, schemas/service, Advisor runtime field, two
  appended tools, and additive fetch metadata field; no persisted advisory data
  needs migration cleanup.
