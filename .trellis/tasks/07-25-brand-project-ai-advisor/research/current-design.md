# Current design evidence

## Domain findings

- `Project` is user-owned and has no brand link. Repository reads filter by both
  project ID and user ID.
- `CommercialTask` links to a user project but remains user-owned and does not
  model brand ownership.
- `BrandOrganization` access is mediated through `BrandMembership`. The
  `require_brand_member` service intentionally returns the same not-found error
  for a missing brand and a non-member.
- Existing read-only brand engagement capabilities are available to both owner
  and member roles, supporting member-level advisory access.

## Agent and API findings

- Agent-visible tools live one-per-module under `services/agent/func`; the
  registry owns stable order and dependency composition.
- Tool ownership comes from `AgentRunContext`, which is hidden from the model.
- Web search uses DuckDuckGo HTML with Chinese MediaWiki fallback. Web fetch is
  SSRF-, redirect-, media-type-, byte-, and character-bounded.
- The Agents SDK `RunResult.new_items` exposes paired tool call/output items,
  allowing application code to reconstruct the real evidence used in a run.
- Typed Agent output is already established by `ModelProjectDraftGenerator`
  using Pydantic `output_type`.
- Every authenticated POST requires an 8..128 ASCII `Idempotency-Key`. Response
  bodies are encrypted and replayable for 24 hours; this does not provide a
  user-facing history resource.

## Design consequence

The MVP should not change project ownership or add persistence. It should use a
brand-scoped request brief, optional current-user project enrichment, a
structured Advisor Agent, and deterministic post-run citation/sufficiency
validation. Future shared projects and report history remain separate explicit
aggregates.
