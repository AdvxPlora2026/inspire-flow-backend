# Optimize agent service and add public web tools

## Goal

Turn the existing OpenAI Agents SDK draft into a testable Agent service with a
clear construction and execution boundary. Give the Agent a small set of
reliable tools for current date/time, public web search, and safe webpage
retrieval while preferring free or no-key data sources.

The result should be easy for another service or future API route to call
without depending on module globals or knowing how individual tools perform
network requests.

## Background

- The working tree already contains an uncommitted
  `openai-agents>=0.18.3` dependency and a new
  `src/inspire_flow_backend/services/agent/` package.
- `agent.py` currently constructs one module-level Agent with no instructions
  or tools. `get_agent()` uses a wildcard import, catches every exception,
  prints it, returns `None`, and has an inaccurate coroutine return annotation.
- `tools.py` and `docs/prompt.md` are currently empty.
- No route, test, or other source module imports the Agent package, so there is
  no established HTTP or internal caller contract to preserve.
- The existing project uses layered FastAPI services, Pydantic settings, uv,
  Ruff, pytest, and warning-free test execution.

## Requirements

### Agent service

- Replace the global execution function with an explicit, typed service that
  owns Agent construction and delegates runs to the Agents SDK.
- Expose the service as an internal Python API only; do not add a FastAPI route
  or HTTP schema in this iteration.
- Support dependency injection for the runner and web client so tests do not
  call an LLM or the public internet.
- Use explicit imports and a deterministic tool registry.
- Do not print, swallow, or convert arbitrary SDK failures into `None`.
- Keep model selection and run-turn limits configurable without embedding an
  API key in source or documentation.
- Preserve the current uncommitted dependency work unless research shows an
  incompatibility.

### Date/time tool

- Register the Agent-facing name `current_datetime`.
- Return the current time as an ISO 8601 timezone-aware value.
- Accept an IANA timezone name and default to UTC.
- Reject an unknown timezone with a concise tool-safe error.
- Use only the Python standard library and allow clock injection in tests.

### Web search tool

- Register the Agent-facing name `search_website`.
- Accept a non-empty query and a bounded result count.
- Return stable result records containing at least title, URL, and snippet.
- Use DuckDuckGo's HTML search surface as the default no-key general-web
  provider. Treat it as an unofficial, best-effort integration whose markup or
  rate limits can change.
- Do not claim that DuckDuckGo HTML is a supported public API.
- Keep a supported no-key MediaWiki search provider available as a fallback
  for knowledge-oriented searches.
- Hide provider response formats behind a search-provider interface so a
  keyed or self-hosted provider can be added later.
- Apply explicit timeout, response-size, and provider-error handling.

### Web fetch tool

- Register the Agent-facing name `fetch_webpage`.
- Fetch only HTTP or HTTPS pages and return bounded readable text plus source
  metadata.
- Reject loopback, private, link-local, multicast, reserved, unspecified, and
  credential-bearing destinations before issuing a request.
- Revalidate each redirect target rather than following redirects blindly.
- Enforce timeouts, maximum redirects, maximum response bytes, and an allowed
  content-type set.
- Remove scripts, styles, and markup from HTML while retaining readable text.
- Return a concise tool-facing failure without exposing stack traces or local
  network details.

### Quality and documentation

- Add unit tests before production code and observe the intended failures.
- Tests must use fakes or injected transports; the normal test suite must not
  require an OpenAI key or public-network access.
- Document tool names, inputs, outputs, limits, configuration, provider
  caveats, and a minimal internal service call example.
- Keep uv lock state, Ruff, formatting, and the warning-free pytest suite
  green.

## Acceptance Criteria

- [x] Agent construction registers the date/time, search, and fetch tools in a
      deterministic order without module-level mutable state.
- [x] A caller can run the Agent through one typed service method and SDK
      exceptions remain observable to the caller.
- [x] The date/time tool returns deterministic aware timestamps in tests and
      handles valid and invalid IANA timezones.
- [x] Search maps a provider response into bounded title/URL/snippet records,
      validates query and result count, and exposes safe provider failures.
- [x] The default search provider returns general-web results from DuckDuckGo
      without an API key, while provider-specific markup stays outside the
      Agent tool contract.
- [x] An expected DuckDuckGo failure or empty result can fall back to
      MediaWiki and identifies the fallback provider in its output.
- [x] Web fetch blocks unsafe destinations and unsafe redirects before a
      network request, rejects unsupported content, and truncates or rejects
      oversized responses according to the documented contract.
- [x] HTML fetch output omits script/style content and presents compact
      readable text.
- [x] No test performs a real LLM or internet call.
- [x] Existing user, session, migration, and health tests remain compatible.
- [x] `uv lock --check`, locked sync, Ruff lint/format, and
      `pytest -W error` pass.

## Out of Scope

- A chat UI, conversation database, streaming protocol, tool-call audit
  persistence, RAG/vector search, browser automation, or arbitrary code
  execution.
- A FastAPI endpoint for invoking the Agent.
- Brave and SearXNG provider implementations in this iteration; the provider
  interface should allow them later.
- Production guarantees for an unauthenticated third-party search source.
- Recursive crawling, `robots.txt` orchestration, JavaScript rendering, file
  downloads, and non-text media extraction.
- Bypassing robots, paywalls, access controls, or anti-bot measures.
