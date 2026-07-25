# Brand project AI advisor

## Goal

Add an authenticated backend advisory capability that an Agent can use to
research current topics and return evidence-backed, actionable advice for a
brand project. A brand operator must be able to trace every recommendation from
public evidence through explicit reasoning to the proposed action.

## Background

- The feature needs both an HTTP API and an Agent FunctionTool entry point.
- `Project` is owned by one user and has no brand association
  (`data/models/project.py:17-57`). Project reads enforce that ownership
  (`data/repositories/projects.py:14-24`).
- `CommercialTask` references a user-owned project but is also user-owned; it
  does not establish a brand-project relationship
  (`data/models/commercial.py:32-65`).
- Brand access is membership-based. Missing brands and brands where the caller
  is not a member use identical not-found behavior
  (`services/brands.py:42-61`).
- The Agent runtime already provides bounded search/fetch tools and typed
  Pydantic model output (`services/agent/func/registry.py:71-112`,
  `services/agent/project_drafting.py:23-47`).

## Requirements

### Advisory target

- The request is scoped to an authenticated `brand_id` and contains a required
  `project_brief`. The explicit brief is the MVP source of truth.
- The request may include a `project_id` owned by the current user. Its title,
  type, audience, and summary enrich the brief; explicit brief content wins on
  conflict.
- The request may include optional focus topics and market context.
- Every active brand member may request advice. Brand ownership is not
  required because the operation is read-only.
- Unknown and inaccessible brands return identical `brand_not_found` behavior.
  Unknown and foreign optional projects return identical `project_not_found`
  behavior.

### Research and evidence

- Research uses only approved, bounded, read-only public web tools. External
  content remains untrusted input.
- `lookback_days` accepts 1 through 30 and defaults to 7.
- Every evidence item includes an identifier, title, URL, normalized source
  domain, summary, project relevance, retrieval time, verification level, and
  freshness state. Publication time is included only when it can be verified;
  otherwise it is null.
- Evidence is `sufficient` only when at least three relevant items cover at
  least two independent source domains and the available freshness metadata
  supports the requested current-topic scope.
- Any weaker evidence set is `limited` or `insufficient`. It must not produce a
  high-confidence recommendation.
- A model-generated claim or URL that did not appear in the actual tool outputs
  is never accepted as evidence.

### Advice and reasoning

- Each recommendation includes priority, action time window, proposed action,
  expected effect, cited evidence identifiers, a causal reasoning chain, risks,
  counterarguments, assumptions, and confidence.
- The reasoning chain explicitly separates observed facts, their implication
  for this brand/project, and why the proposed action follows.
- Missing or conflicting evidence is stated directly. The response must not
  hide weak research behind confident prose.
- An `insufficient` report may omit strategic recommendations and instead
  return concrete next-research steps.
- Output is Simplified Chinese and distinguishes evidence, inference, advice,
  and uncertainty.

### Delivery and lifecycle

- Provide an authenticated brand-scoped POST endpoint and register a matching
  Agent tool. The Agent can discover the caller's brands through a read-only
  brand-list tool when no brand UUID is already available.
- Return expected API and tool failures through the repository's standard safe
  error envelopes.
- Reports are generated on demand and are not stored in a report-history table.
  Existing authenticated POST idempotency may replay the encrypted response for
  24 hours, but this is not a user-visible archive.
- Automated tests do not use real model credentials, public DNS, or live web
  providers.

## Acceptance Criteria

- [ ] `POST /api/v1/brands/{brand_id}/advisory-reports` accepts a valid brief
      from any active brand member and returns a typed advisory report.
- [ ] The request supports optional owned `project_id`, market/focus context,
      and `lookback_days=1..30` with a default of 7.
- [ ] The Agent registry exposes read-only brand discovery and advisory tools
      without exposing `user_id` in their model-visible schemas.
- [ ] Every accepted evidence URL is traceable to an actual search or webpage
      tool output from that run.
- [ ] Every recommendation cites accepted evidence and includes causal steps,
      priority, time window, expected effect, risks, counterarguments,
      assumptions, and confidence.
- [ ] Evidence status is computed by application logic. Fewer than three
      relevant items, fewer than two independent domains, or inadequate
      freshness can never yield `sufficient` or high confidence.
- [ ] Source title, URL, domain, retrieval time, verification level, and
      freshness are always present; verified publication time is included when
      available and otherwise is null.
- [ ] Provider/tool failure can return an honest `limited` or `insufficient`
      report; malformed structured output or fabricated citations return the
      standard expected Agent failure instead of unsafe prose.
- [ ] Missing/non-member brands and missing/foreign projects do not leak
      existence or content.
- [ ] Repeating an identical keyed POST follows existing encrypted idempotency
      replay behavior and no advisory-history table or row is created.
- [ ] Focused unit, tool, service, and API tests cover success, member access,
      cross-tenant denial, optional project enrichment, weak evidence, source
      deduplication, provider failure, malformed model output, fabricated
      citations, confidence downgrading, and idempotent replay without live
      dependencies.

## Out Of Scope

- A shared persisted brand-project domain.
- Long-term advisory report listing, retrieval, refresh, versioning, or deletion.
- Automatically changing projects, commercial tasks, budgets, or campaign state.
- Executing trades or presenting regulated securities advice.
- Treating the model's own statements as independent evidence.

## Deferred Upgrade Direction

- Add a brand-owned `BrandProject` aggregate when brand members need reusable
  shared project state. Link it explicitly to optional creator projects and
  commercial tasks instead of changing current `Project` ownership semantics.
- Define brand-member create/read/update/archive permissions and audit history
  before shared editing. Historical request briefs must be migrated only by an
  explicit backfill or user action.
- Add a durable, versioned advisory-report aggregate only after report quality
  is validated. Preserve request and evidence snapshots, generation version,
  status, refresh lineage, and membership-scoped audit fields with explicit
  retention and deletion rules.
- Future research providers may add licensed trend feeds, social-platform
  metrics, and scheduled monitoring. They must map into the same evidence
  ledger instead of bypassing citation and sufficiency checks.
