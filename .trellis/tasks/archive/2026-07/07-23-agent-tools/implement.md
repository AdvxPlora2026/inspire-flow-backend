# Agent Service and Basic Tool Implementation Plan

**Goal:** Replace the current Agent draft with a typed internal service and
add deterministic date/time, no-key DuckDuckGo search with MediaWiki fallback,
and safe webpage fetch tools.

**Method:** Execute inline with strict red-green-refactor. Preserve the user's
existing uncommitted Agent dependency and files; do not revert unrelated work.

## File Map

### Modify

- `pyproject.toml`: keep `openai-agents`; add direct HTTPX dependency through
  uv.
- `uv.lock`: update only through uv.
- `src/inspire_flow_backend/services/agent/agent.py`: replace global draft
  with service, runner adapter, factory, and lifecycle.
- `src/inspire_flow_backend/services/agent/tools.py`: implement function-tool
  wrappers and deterministic registry.
- `src/inspire_flow_backend/services/agent/__init__.py`: keep side-effect free.
- `docs/prompt.md`: write internal Agent/tool handoff.
- `README.md`: link the internal handoff.

### Create

- `src/inspire_flow_backend/services/agent/contracts.py`
- `src/inspire_flow_backend/services/agent/web_search.py`
- `src/inspire_flow_backend/services/agent/web_fetch.py`
- `tests/services/agent/test_agent.py`
- `tests/services/agent/test_tools.py`
- `tests/services/agent/test_web_search.py`
- `tests/services/agent/test_web_fetch.py`

## Task 1: Lock the service and registry contract

- [ ] Write `test_agent.py` before production edits.
- [ ] Require a factory-created service with no module-level Agent.
- [ ] Assert tool names are exactly
      `current_datetime`, `search_website`, `fetch_webpage` in that order.
- [ ] Inject a fake runner; assert prompt, Agent, default turn count, and
      per-call override.
- [ ] Assert blank prompts and non-positive turn counts fail locally.
- [ ] Assert runner exceptions propagate unchanged.
- [ ] Assert `aclose()` closes only factory-owned clients and the async context
      manager delegates to it.
- [ ] Run the focused test and observe failures caused by the missing service.

Implementation:

- [ ] Add `httpx>=0.28,<1` with `uv add`.
- [ ] Add contracts required by the test.
- [ ] Implement `AgentRunner`, SDK adapter, `AgentService`, and factory.
- [ ] Replace wildcard imports, global mutation, `print`, catch-all return
      `None`, and inaccurate coroutine annotation.
- [ ] Keep `__init__.py` side-effect free.
- [ ] Run focused tests to green; refactor without changing behavior.
- [ ] Commit the service foundation separately.

## Task 2: Add the date/time tool

- [ ] Write failing tests for UTC default, `Asia/Shanghai`, fixed-clock
      determinism, and invalid IANA timezone.
- [ ] Write a failing schema test for the Agent-facing function tool.
- [ ] Implement `DateTimeResult`, expected tool-error envelope, and the pure
      date/time operation.
- [ ] Wrap it as `current_datetime` with a typed docstring/schema.
- [ ] Return JSON with `ok`, timezone, ISO datetime, and Unix timestamp.
- [ ] Run focused and registry tests to green.

## Task 3: Add DuckDuckGo search and MediaWiki fallback

- [ ] Write failing provider tests using `httpx.MockTransport`.
- [ ] Cover query trimming/length, result count bounds, fixed endpoint,
      response byte cap, non-success status, timeout mapping, and no-results
      behavior.
- [ ] Add a minimal DuckDuckGo HTML fixture containing multiple results,
      markup in snippets, and `uddg` redirects.
- [ ] Assert mapping to exact title/URL/snippet records and maximum count.
- [ ] Add MediaWiki JSON tests for correct parameters, output mapping, invalid
      structure, and safe URL construction.
- [ ] Add fallback tests proving DuckDuckGo is first and MediaWiki is used only
      for expected provider failure or empty results.
- [ ] Observe failures before adding production search code.

Implementation:

- [ ] Add the provider protocol and typed search contracts.
- [ ] Implement the bounded DuckDuckGo HTML parser with the standard library.
- [ ] Implement streamed HTTP response limits and safe provider errors.
- [ ] Implement the MediaWiki provider and fallback chain.
- [ ] Wrap the chain as `search_website(query, max_results=5)`.
- [ ] Run focused tests to green and refactor parser helpers.

## Task 4: Add safe webpage fetch

- [ ] Write URL-policy tests before implementation.
- [ ] Cover malformed URLs, unsupported schemes, credentials, unsafe ports,
      IP literals, and fake DNS answers for loopback/private/link-local/
      multicast/reserved/unspecified/shared ranges.
- [ ] Assert a hostname is accepted only when every resolved address is
      globally routable.
- [ ] Write redirect tests proving every destination is revalidated before the
      transport is invoked and the redirect limit is enforced.
- [ ] Write body tests for HTML/plain/JSON, unsupported content type,
      non-success status, byte limit, character truncation, and encoding.
- [ ] Assert HTML output omits script/style/noscript/template/SVG content and
      captures the title.
- [ ] Observe the focused failures.

Implementation:

- [ ] Add injectable async hostname resolution and URL policy.
- [ ] Add manual bounded redirect handling with `follow_redirects=False`.
- [ ] Add streamed decoded-byte accounting and media-type checks.
- [ ] Add the standard-library readable-text parser.
- [ ] Wrap the fetcher as `fetch_webpage(url)`.
- [ ] Run focused tests to green and refactor repeated normalization.

## Task 5: Complete Agent behavior and documentation

- [ ] Write/extend failing tests for default instructions, tool error JSON,
      timeout messages, and injected settings.
- [ ] Implement concise default instructions that direct source-aware tool
      use.
- [ ] Ensure expected tool errors are model-visible JSON while unexpected
      errors fail the Agent run.
- [ ] Write `docs/prompt.md` with construction and close examples, credential
      ownership, all tool contracts, limits, provider caveats, and SSRF
      residual risk.
- [ ] Add a README link.
- [ ] Ensure examples contain no real API keys or tokens.
- [ ] Run documentation and diff checks.
- [ ] Commit tools and documentation in coherent slices.

## Task 6: Full verification and review

- [ ] Run:

```bash
uv lock --check
uv sync --locked --dev
uv run ruff check .
uv run ruff format --check .
uv run pytest -W error
```

- [ ] Search for debug output, wildcard imports, warning suppressions, catch-all
      exception swallowing, embedded credentials, and real-network tests.
- [ ] Inspect Agents SDK schemas for all three registered tools.
- [ ] Run one separate live DuckDuckGo smoke search and one public-page fetch;
      do not add live calls to pytest.
- [ ] Run `trellis-check`, fix findings, and repeat the complete gate.
- [ ] Use `trellis-update-spec` to capture Agent service, external-tool, and
      outbound-network conventions.
- [ ] Validate the Trellis task context.
- [ ] Commit all task-owned code before `trellis-finish-work`.

## Rollback Points

- After Task 1, the service refactor is independent of network-tool behavior.
- Search and fetch tools are separate modules and can be removed independently
  from the date tool and service.
- Do not delete or reset the user's initial files during rollback. Revert only
  task-owned hunks or commits.

## Final Review Gate

Before `task.py start`, confirm:

- [x] PRD contains no unresolved product decision.
- [x] Default DuckDuckGo scraping and its operational risk are explicit.
- [x] Internal-only scope is explicit.
- [x] Tests never require an API key, LLM, DNS, or public network.
- [x] The user approves this final plan in a new message.

## Implementation Result

- Implemented the internal `AgentService`, deterministic three-tool registry,
  validated settings, client ownership, and dependency injection.
- Added DuckDuckGo HTML search with Chinese MediaWiki fallback and safe JSON
  tool errors.
- Added URL/DNS/redirect validation, bounded streaming, content-type checks,
  and readable HTML extraction for webpage fetch.
- Added model-facing prompt-injection guidance: web tool output is untrusted
  data and instructions inside it must not be followed.
- Added `docs/prompt.md` and README links, including credentials, provider
  caveats, SSRF residual risk, and transparent-proxy behavior.
- Final gate: lock and locked sync passed; Ruff lint/format passed; 144 tests
  passed with warnings treated as errors.
- Separate live smoke: DuckDuckGo returned FastAPI documentation results and
  `https://1.1.1.1/cdn-cgi/trace` fetched as bounded plain text. The default
  fetch policy correctly rejected this environment's synthetic
  `198.18.0.0/15` DNS mapping for normal public hostnames.
