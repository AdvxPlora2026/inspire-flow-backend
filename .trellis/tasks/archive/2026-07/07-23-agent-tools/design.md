# Agent Service and Basic Tool Technical Design

## Overview

The feature remains an internal Python service. It does not add an HTTP route,
conversation store, or streaming transport. `AgentService` owns one configured
OpenAI Agents SDK `Agent`, one runner adapter, and the lifetime of the HTTPX
client used by network tools.

The Agent receives three local function tools in deterministic order:

1. `current_datetime`
2. `search_website`
3. `fetch_webpage`

Expected tool failures become small JSON error results that the model can
reason about. Unexpected programming errors and Agents SDK failures are not
printed or swallowed; they propagate to the internal caller.

## Existing Draft and Compatibility

The working tree already contains:

- an `openai-agents>=0.18.3` dependency and regenerated `uv.lock`;
- an empty `services/agent/__init__.py`;
- a draft `agent.py` with a module-level Agent and `get_agent()`;
- an empty `tools.py`;
- an empty `docs/prompt.md`.

No committed or uncommitted caller imports `get_agent()`, so the draft has no
compatibility contract. Implementation may replace it with the typed API below
while preserving the user's dependency addition. `__init__.py` remains
side-effect free.

HTTPX is already transitive through the Agents SDK. Because production code
will import it directly, add `httpx>=0.28,<1` as a direct runtime dependency
through `uv add`; do not hand-edit the lockfile.

## Package Layout

```text
src/inspire_flow_backend/services/agent/
├── __init__.py       # Side-effect-free package marker
├── agent.py          # AgentService, runner protocol/adapter, factory
├── contracts.py      # Typed tool success/error payloads and settings
├── tools.py          # Agents SDK FunctionTool construction and registry
├── web_fetch.py      # URL policy, DNS validation, redirects, text extraction
└── web_search.py     # Search provider protocol, DuckDuckGo and MediaWiki

tests/services/agent/
├── test_agent.py
├── test_tools.py
├── test_web_fetch.py
└── test_web_search.py

docs/prompt.md        # Internal usage, default behavior, tool/provider caveats
```

Splitting search and fetch keeps provider-specific HTML parsing separate from
the security boundary that accepts arbitrary URLs.

## Agent Service Boundary

### Public signatures

```python
class AgentRunner(Protocol):
    async def run(
        self,
        starting_agent: Agent,
        prompt: str,
        *,
        max_turns: int,
    ) -> RunResult: ...


class AgentService:
    @property
    def agent(self) -> Agent: ...

    async def run(
        self,
        prompt: str,
        *,
        max_turns: int | None = None,
    ) -> RunResult: ...

    async def aclose(self) -> None: ...
    async def __aenter__(self) -> AgentService: ...
    async def __aexit__(self, ...) -> None: ...


def create_agent_service(
    *,
    model: str | Model | None = None,
    instructions: str = DEFAULT_AGENT_INSTRUCTIONS,
    max_turns: int = 10,
    tool_settings: AgentToolSettings | None = None,
    http_client: httpx.AsyncClient | None = None,
    runner: AgentRunner | None = None,
    clock: Clock = utc_now,
    resolver: HostResolver = resolve_hostname,
) -> AgentService: ...
```

`AgentService.run()` rejects blank input and non-positive per-call turn
overrides. It returns the SDK's `RunResult` without inventing a parallel result
model. The service closes only an HTTP client it created; injected clients
remain owned by their caller.

The default runner adapter is the only location that calls `Runner.run()`.
Tests inject a fake runner and never contact an LLM.

### Default instructions

The default Agent:

- answers directly when no tool is needed;
- uses `current_datetime` for current-time claims;
- uses `search_website` for fresh or externally verifiable information;
- uses `fetch_webpage` when a search snippet is insufficient;
- includes source URLs when web tools were used;
- treats tool error payloads as failures rather than facts.

Callers may replace the complete instruction string and model at construction.
The service does not read or persist `OPENAI_API_KEY`; the SDK retains ownership
of its normal credential resolution.

## Shared Tool Contracts

Pydantic models serialize every tool output with
`model_dump_json(exclude_none=True)`.

### Error envelope

```json
{
  "ok": false,
  "error": {
    "code": "safe_machine_code",
    "message": "Concise model-facing message"
  }
}
```

Expected errors use stable codes:

| Code | Meaning |
| --- | --- |
| `invalid_timezone` | Unknown IANA timezone |
| `invalid_query` | Empty or overlong search text |
| `invalid_result_count` | Search limit outside the supported range |
| `search_unavailable` | Provider timeout, HTTP failure, block page, or unparseable response |
| `invalid_url` | Unsupported or malformed target URL |
| `unsafe_url` | Credentials, unsafe port, or non-global destination |
| `redirect_limit` | Too many redirects |
| `unsupported_content_type` | Response is not supported text content |
| `response_too_large` | Decoded response exceeds its byte budget |
| `fetch_unavailable` | Timeout, HTTP failure, or connection error |

The tool wrappers catch only the feature's expected `AgentToolError` and return
this envelope. `function_tool(failure_error_function=None)` lets unexpected
exceptions fail the run. Async tools also configure a model-safe timeout
result.

### Limits

`AgentToolSettings` is a frozen dataclass with validated construction:

| Setting | Default |
| --- | --- |
| Request timeout | 10 seconds |
| Function-tool timeout | 15 seconds |
| Search result default / maximum | 5 / 10 |
| Query maximum | 300 characters |
| Search response bytes | 512 KiB |
| Fetch response bytes | 1 MiB |
| Fetch output characters | 20,000 |
| Redirect maximum | 3 |
| Allowed destination ports | 80 and 443 |
| User-Agent | `InspireFlowBackend/0.1` |

Callers can supply different bounded settings without environment mutation.

## Date and Time Tool

### Tool signature

```python
current_datetime(timezone_name: str = "UTC") -> str
```

Successful output:

```json
{
  "ok": true,
  "timezone": "Asia/Shanghai",
  "iso_datetime": "2026-07-23T18:30:00+08:00",
  "unix_timestamp": 1784802600
}
```

The clock returns an aware datetime. The implementation converts it through
`zoneinfo.ZoneInfo`; it does not change the process timezone. Tests inject a
fixed UTC clock.

## Search Design

### Provider boundary

```python
class SearchProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def search(self, query: str, limit: int) -> list[SearchResult]: ...
```

`SearchResult` contains exactly `title`, `url`, and `snippet`.
`SearchResponse` contains `ok`, `query`, `provider`, and a bounded result list.
The Agent-facing contract never exposes DuckDuckGo class names or raw HTML.

### Default provider chain

```text
search_website
  -> DuckDuckGoHtmlSearchProvider
  -> on expected provider failure or empty results:
       MediaWikiSearchProvider(language="zh")
```

The response's `provider` identifies which source produced the result. The
MediaWiki fallback is not described as general-web coverage.

### DuckDuckGo HTML adapter

The provider sends a GET request to:

```text
https://html.duckduckgo.com/html/?q=<encoded query>
```

It uses a bounded streamed response and a small standard-library `HTMLParser`.
The parser recognizes `result__a` and `result__snippet`, strips markup, decodes
HTML entities, normalizes whitespace, and unwraps DuckDuckGo redirect URLs
through the `uddg` query parameter. It keeps only HTTP/HTTPS result URLs without
embedded credentials.

The adapter is explicitly unofficial and best-effort. A non-200 response,
oversized page, obvious challenge page, or no parseable result becomes
`search_unavailable`, allowing the provider chain to try MediaWiki.

### MediaWiki fallback

The fallback calls the supported JSON Action API:

```text
https://zh.wikipedia.org/w/api.php
  ?action=query
  &list=search
  &format=json
  &formatversion=2
  &srsearch=<query>
  &srlimit=<limit>
```

It maps titles, stripped snippets, and canonical article URLs into the shared
result model. Invalid JSON or response structure is a provider failure rather
than an empty success.

## Safe Web Fetch Design

### Tool signature

```python
fetch_webpage(url: str) -> str
```

Successful output:

```json
{
  "ok": true,
  "url": "https://example.com/article",
  "content_type": "text/html",
  "title": "Example article",
  "text": "Readable normalized page text...",
  "truncated": false
}
```

### URL policy

Before every request, including redirects:

1. Parse with `urllib.parse.urlsplit`.
2. Require `http` or `https`, a hostname, no username/password, and port 80 or
   443 when a port is explicit.
3. Resolve the hostname through an injected async resolver.
4. Parse every returned IPv4/IPv6 address with `ipaddress.ip_address`.
5. Require every address to have `is_global == True`.

Requiring all answers to be global blocks loopback, private, link-local,
multicast, reserved, unspecified, and shared-address-space destinations. IP
literals pass through the same rule. Tests inject a resolver and never perform
DNS.

This check substantially reduces SSRF exposure but does not claim to eliminate
DNS rebinding between validation and the HTTP client's connection. A
production environment should also enforce outbound network policy.

### Request and redirect flow

HTTPX is configured with `follow_redirects=False` and `trust_env=False`.
Redirects are handled manually:

```text
validate URL
  -> stream GET
  -> 3xx with Location:
       resolve relative Location
       validate new URL
       repeat up to max_redirects
  -> final response
```

An unsafe redirect is rejected before its destination is requested. Missing
`Location`, non-success final status, timeout, and connection failure become
safe fetch errors.

### Body and text handling

Allowed media types:

- `text/html`
- `application/xhtml+xml`
- `text/plain`
- `application/json`

The response is streamed and counted after HTTP content decoding. A body over
1 MiB is rejected. HTML uses a standard-library parser that ignores
`script`, `style`, `noscript`, `template`, and SVG content, captures the title,
and normalizes visible whitespace. Plain text and JSON are decoded using the
declared encoding or UTF-8 replacement.

Text longer than 20,000 characters is truncated with `truncated=true`.
Binary content, downloads, JavaScript rendering, and recursive crawling are
outside this task.

## Data Flow

```text
Internal caller
  -> AgentService.run(prompt)
  -> AgentRunner adapter
  -> OpenAI Agents SDK Agent
  -> FunctionTool wrapper
  -> typed date/search/fetch implementation
  -> fixed provider or validated public URL
  -> bounded typed JSON result
  -> Agent loop
  -> RunResult to caller
```

Validation has one owner at each boundary:

- Agent service validates prompt and turn count.
- Tool entry functions validate tool arguments.
- Search providers validate external provider payloads.
- URL policy owns destination validation.
- Pydantic models own serialized result shapes.

## Error and Failure Matrix

| Failure | Model sees | Internal caller sees |
| --- | --- | --- |
| Invalid timezone/query/limit/URL | Stable JSON tool error | Normal Agent run can recover |
| Provider timeout or HTTP failure | Stable search/fetch error | Normal Agent run can recover |
| Unsafe redirect | `unsafe_url` | Normal Agent run can recover |
| Tool timeout | Stable timeout result | Normal Agent run can recover |
| Parser/programming defect | Nothing fabricated | SDK run exception propagates |
| Invalid model output/tool JSON | SDK behavior | SDK run exception propagates |
| Missing/invalid OpenAI credential | No console print or `None` | SDK exception propagates |

No tool error contains response bodies, resolved private addresses, stack
traces, API keys, or the full underlying exception string.

## Testing Strategy

Tests follow red, green, refactor:

1. Service tests define the desired constructor, deterministic tool list,
   runner delegation, lifecycle ownership, and exception propagation.
2. Date tests define timezone output and invalid-zone errors with a fixed
   clock.
3. Search tests use `httpx.MockTransport` with stored minimal HTML/JSON
   fixtures; no public request is made.
4. Fetch tests use `MockTransport` plus a fake resolver to cover safe pages,
   every blocked address category, redirect revalidation, type/size limits,
   HTML cleanup, and truncation.
5. Registry tests inspect Agents SDK tool names and JSON schemas.
6. The full existing suite runs with warnings treated as errors.

After automated checks, one separate opt-in smoke command may call DuckDuckGo
to confirm the current adapter against live markup. A live failure does not
weaken deterministic tests; it is reported as the documented provider risk.

## Documentation

`docs/prompt.md` becomes the internal handoff for:

- async context-managed service construction;
- model/API-key ownership;
- tool names and input/output examples;
- default limits and error codes;
- DuckDuckGo's unofficial status and MediaWiki fallback;
- safe-fetch restrictions and residual DNS-rebinding risk;
- a no-network test example.

The README receives a short link to this document without presenting an Agent
HTTP endpoint.

## Rollback and Deferred Work

Rollback removes the new Agent modules/tests/docs and removes the direct HTTPX
dependency only if no other direct consumer exists. The pre-existing
`openai-agents` addition is part of this feature and is retained unless the
whole Agent draft is rolled back.

Deferred:

- FastAPI invocation and streaming;
- conversation/session persistence;
- Brave and SearXNG providers;
- retries, distributed rate limiting, caching, and provider telemetry;
- DNS pinning or network-sandbox enforcement;
- JavaScript/browser rendering and recursive crawling.

## Research References

Detailed source notes are in `research/search-and-tool-sources.md`.
