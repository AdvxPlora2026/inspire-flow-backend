# Brand project AI advisor design

## Summary

Add one read-only advisory use case shared by an HTTP route and an Agent
FunctionTool. A dedicated structured-output Advisor Agent may call only bounded
search and webpage-fetch tools. Application code then reconstructs an evidence
ledger from the run's real tool outputs, validates citations, computes evidence
status, and enforces confidence rules before returning the public report.

No advisory or brand-project table is added in the MVP.

## HTTP contract

```text
POST /api/v1/brands/{brand_id}/advisory-reports
Authorization: Bearer <token>
Idempotency-Key: <8..128 ASCII characters>
```

Request shape:

```python
class BrandAdvisoryRequest(BaseModel):
    project_brief: str                 # normalized, 1..6000
    project_id: UUID | None = None     # owned by current user
    market: str = "China mainland"     # normalized, 1..120
    focus_topics: list[str] = []       # <= 5 unique items, each 1..100
    lookback_days: int = 7             # 1..30
```

The public API documentation describes `market` as free-form context. The model
response remains Simplified Chinese regardless of the market value.

Response outline:

```text
BrandAdvisoryReport
  generated_at
  evidence_status: sufficient | limited | insufficient
  brand: id, name
  project_context: brief, optional linked project projection
  research_scope: market, focus topics, lookback window, executed queries
  evidence[]
  recommendations[]
  caveats[]
  next_research_steps[]
```

The route returns `200`. It declares `401`, `404`, `422`, `502`, and `503`
error models. Existing middleware requires and scopes idempotency by user,
brand path parameter, method, route template, and request fingerprint.

## Authorization and context assembly

`services/advisory.py` owns the use case:

1. Call `require_brand_member(db, brand_id, user_id)` before exposing brand
   fields.
2. If `project_id` is supplied, call the existing user-scoped project service.
3. Build an immutable `BrandAdvisoryContext` from the safe brand projection,
   explicit brief, optional project projection, market, focus topics, and time
   window.
4. Invoke the injected `BrandAdvisor` protocol.
5. Map expected SDK/provider/transport/model-behavior failures to the existing
   `AgentRunFailedError`; unexpected programming defects propagate.

No database transaction remains open while model or outbound network work is
running. Membership/project reads complete before the Advisor run.

## Advisor Agent

Add `services/agent/brand_advisor.py`:

```python
class BrandAdvisor(Protocol):
    async def analyze(self, context: BrandAdvisoryContext) -> BrandAdvisoryReport: ...


class ModelBrandAdvisor:
    # Agent(name="InspireFlowBrandAdvisor", output_type=BrandAdvisoryDraft,
    #       tools=[search_website, fetch_webpage], model=model)
```

The prompt contains only validated application context. Instructions require:

- two or more research angles when the brief supports them;
- preference for multiple independent sources;
- webpage fetching before relying on a search snippet when possible;
- explicit separation of observation, inference, and advice;
- no unsupported source, brand fact, metric, or causal claim;
- no financial-trading advice and no write actions.

The maximum turns and search/fetch limits remain bounded through
`AgentToolSettings`. Search/fetch errors are model-visible safe tool results and
may lead to an insufficient report rather than an exception.

## Evidence ledger and finalization

The structured model output is a draft, not the authority for citations or
confidence. After the run:

1. Walk `RunResult.new_items` and pair `ToolCallItem` names with
   `ToolCallOutputItem` values by call ID.
2. Parse only successful `search_website` and `fetch_webpage` outputs through
   their Pydantic contracts.
3. Canonicalize and deduplicate public HTTP(S) URLs. Record the actual title,
   URL, normalized host/domain, bounded snippet or fetched-text excerpt,
   verification level, retrieval time, and optional verified publication time.
   Support both typed and mapping-backed Agents SDK `raw_item` values. If the
   draft repeats one canonical URL under multiple evidence IDs, accept only the
   first so duplicates cannot satisfy the three-evidence threshold. Empty tool
   content cannot form evidence; an empty fetch may retain a prior search
   excerpt for the same URL.
4. Reject a draft evidence URL that is absent from this ledger.
5. Require unique evidence IDs and require every recommendation citation to
   resolve to accepted evidence.
6. Compute freshness from `generated_at`, `lookback_days`, and verified
   publication time. Undated evidence is labeled honestly; known out-of-window
   evidence does not support current-topic sufficiency.
7. Compute `evidence_status` in application code. `sufficient` requires at
   least three accepted relevant items, at least two normalized source domains,
   and at least one source with verified in-window freshness. Any weaker set is
   `limited` or `insufficient`.
8. Reject or downgrade `high` confidence unless status is `sufficient`.
   `insufficient` may return no strategic recommendations and must provide next
   research steps.

This finalizer is deterministic and unit-tested without a model. It prevents a
well-formed but fabricated model report from becoming public output.

## Web metadata

Extend the fetch success contract additively with nullable `published_at`.
For HTML, extract only machine-readable publication metadata such as
`article:published_time`, JSON-LD `datePublished`, or a valid `<time datetime>`
candidate. Normalize accepted values to aware UTC. Ambiguous or invalid values
remain null; page prose is never date-parsed heuristically.

Existing SSRF, redirect, media-type, byte, and character limits remain
unchanged. The additive field is covered in the shared Agent tool contract and
tests.

## Agent tools

Append these stable tools to `services/agent/func/registry.py`:

```text
list_brands(limit=50, offset=0)
analyze_brand_project(brand_id, project_brief, project_id=None,
                      market="China mainland", focus_topics=None,
                      lookback_days=7)
```

Both receive trusted ownership through `AgentRunContext`; neither accepts
`user_id`. `list_brands` exposes only brands where the caller is a member.
`analyze_brand_project` delegates to the same application service as the HTTP
route and returns the same report in the standard `{ok:true,...}` tool shape.

Safe expected tool errors include `brand_context_unavailable`,
`brand_not_found`, `project_not_found`, `invalid_advisory_request`, and
`advisory_unavailable`. Unknown/foreign identifiers remain indistinguishable.

Update the default Agent instructions to gather a concrete brief, use brand
discovery when needed, call the advisory tool only for advice requests, and
summarize the returned evidence and reasoning without changing its confidence.

## Runtime composition

`AgentRuntime` gains a `brand_advisor` field and owns one bounded outbound
HTTPX client shared by the conversation Agent tools and Advisor Agent tools.
The model client remains shared as today. Runtime shutdown closes the
conversation Agent, outbound client, and model client exactly once.

Tests inject a fake `BrandAdvisor`; no test requires model settings or network
access.

## Compatibility and rollout

- No migration or existing row rewrite is required.
- The fetch tool response receives one nullable additive field; update exact
  schema/output tests and the Agent tool spec.
- New Agent tools are appended so existing relative ordering is preserved.
- If rollout causes poor results, remove the route and two appended tools; no
  stored advisory data requires cleanup.

## Deferred upgrades

The durable upgrade path is recorded in `prd.md`: a separate brand-owned
`BrandProject`, followed later by versioned `AdvisoryReport` snapshots and
licensed/scheduled trend providers. Existing user projects are not silently
re-parented.
