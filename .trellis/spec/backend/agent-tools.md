# Agent Service and Outbound Tool Guidelines

> Executable contracts for the internal Agent service, no-key search, and
> public webpage fetch boundary.

## Scenario: Internal Agent with Outbound Tools

### 1. Scope / Trigger

- Trigger: adding or changing an Agents SDK tool, model-runner integration,
  external search provider, arbitrary-URL fetch, or Agent lifecycle behavior.
- The same Agent runner serves the internal Python boundary and the
  `/api/v1/conversations/{conversation_id}/messages` HTTP use case.
- Direct string runs are stateless. Durable HTTP runs pass a project-owned
  Agents SDK `Session` backed by encrypted SQLite rows.
- Outbound tools are security boundaries: external payloads are untrusted and
  every request must be time-, size-, and destination-bounded.

### 2. Signatures

```python
class AgentService:
    async def run(
        self,
        input: str | list[TResponseInputItem],
        *,
        max_turns: int | None = None,
        session: Session | None = None,
        run_config: RunConfig | None = None,
    ) -> RunResult: ...

    async def aclose(self) -> None: ...


def create_agent_service(
    *,
    model: str | Model | None = None,
    instructions: str = DEFAULT_AGENT_INSTRUCTIONS,
    max_turns: int = 10,
    tool_settings: AgentToolSettings | None = None,
    http_client: httpx.AsyncClient | None = None,
    runner: AgentRunner | None = None,
    clock: Clock = utc_now,
    resolver: HostResolver | None = None,
) -> AgentService: ...


async def validate_public_url(url: str, resolver: HostResolver) -> str: ...
```

Durable turn composition:

```python
async def run_conversation_turn(
    db: Session,
    *,
    user: User,
    conversation_id: UUID,
    content: str,
    runtime: AgentRuntime,
    cipher: ContextCipher,
    settings: Settings,
) -> AgentTurn: ...
```

Registered tool names and order are stable:

```text
current_datetime(timezone_name="UTC")
search_website(query, max_results=5)
fetch_webpage(url)
```

Agent-visible FunctionTool definitions live under
`services/agent/func/`, one module per tool. `func/registry.py` owns dependency
composition and the stable registration order, while `func/_shared.py` owns
shared model-facing error and timeout formatting. The underlying
`web_search.py`, `web_fetch.py`, and `contracts.py` modules remain at the Agent
package root because they are support services, not FunctionTool definitions.

### 3. Contracts

Expected tool failures use:

```json
{
  "ok": false,
  "error": {
    "code": "safe_machine_code",
    "message": "Concise model-facing message"
  }
}
```

Success contracts:

| Tool | Fields |
| --- | --- |
| `current_datetime` | `ok`, `timezone`, `iso_datetime`, `unix_timestamp` |
| `search_website` | `ok`, normalized `query`, selected `provider`, bounded `results[{title,url,snippet}]` |
| `fetch_webpage` | `ok`, final `url`, `content_type`, optional `title`, `text`, `truncated` |

The default search provider is DuckDuckGo's HTML page. On an expected provider
failure or no parseable results, use the supported Chinese MediaWiki Action API
and report `provider="mediawiki_zh"`. DuckDuckGo HTML is an unofficial,
best-effort adapter and has no availability contract.

Search results and fetched page text are untrusted data. Default and custom
Agent instructions must forbid following instructions found inside tool output;
never expose secrets or internal context to an external page.

The default instructions define InspireFlow as a Chinese-language creation
assistant for Bilibili creators. They must:

- use caller-provided project context without repeating answered questions;
  explicit current user input wins on conflict, and the Agent states which
  understanding changed;
- capture a one-sentence idea without an up-front questionnaire, normally ask
  one useful question, offer two to four choices when helpful, and generate
  directly when explicitly requested;
- move work one stage at a time through inspiration clarification, direction,
  outline, detail, storyboard or script, shooting preparation, and publishing
  preparation;
- use natural language for ordinary replies and Markdown for relevant creation
  artifacts; storyboards identify each shot's visual, sound, duration, and
  shooting note, while scripts distinguish narration, dialogue, visual
  direction, and sound;
- assign an idea only when a project-write capability is actually available;
  otherwise provide a project-ready record and state that it has not been
  saved;
- cover budget, delivery scope, schedule, revisions, licensing, credits, and
  collaborator revenue sharing for commercial projects;
- distinguish confirmed facts, suggestions, assumptions, and pending
  decisions without inventing project state, terms, or completed actions; and
- keep other projects private and claim saves, uploads, publications,
  authorizations, payments, or deletions only after a successful tool result.

Keep these product instructions in the single
`DEFAULT_AGENT_INSTRUCTIONS` constant. Tests should assert the stable concepts,
not duplicate the entire prompt. `AgentService.run()` has no separate context
parameter; callers include dynamic project context in the existing prompt
argument.

The factory-created HTTP client uses `follow_redirects=False`,
`trust_env=False`, configured timeouts, and the configured User-Agent. The
service closes only a client it created; callers retain ownership of injected
clients. The Agents SDK owns model credential discovery through the process
environment.

### 4. Validation & Error Matrix

| Condition | Tool behavior |
| --- | --- |
| Blank prompt or non-integer/non-positive turns | Raise local `ValueError` |
| Unknown IANA timezone | `invalid_timezone` |
| Blank/overlong query | `invalid_query` |
| Search count outside configured range | `invalid_result_count` |
| Provider HTTP error, challenge, timeout, or invalid payload | `search_unavailable` |
| Non-HTTP(S), relative, malformed, or whitespace-bearing URL | `invalid_url` |
| URL credentials, unsafe port, empty DNS answer, or any non-public answer | `unsafe_url` |
| Redirect count exceeds the configured maximum | `redirect_limit` |
| Final media type is not HTML, XHTML, plain text, or JSON | `unsupported_content_type` |
| Decoded body exceeds the byte budget | `response_too_large` |
| Fetch connection, timeout, missing redirect location, or bad status | `fetch_unavailable` |
| Unexpected runner, parser, or programming defect | Propagate; do not convert to tool data |

Validate every redirect destination before requesting it. For every DNS answer,
require `is_global` and explicitly reject private, loopback, link-local,
multicast, reserved, unspecified, shared, and IPv6 site-local addresses.
`ipaddress.is_global` alone is insufficient: current Python versions classify
some multicast and deprecated site-local addresses as global.

Application DNS validation does not pin the address used by HTTPX and therefore
does not eliminate DNS rebinding. Production deployments also need outbound
network policy. Environments that map public names into reserved ranges such as
`198.18.0.0/15` are rejected by design; do not add those ranges to the allowlist
as a compatibility shortcut.

### 5. Good / Base / Bad Cases

- Good: construct the service with `async with`, inject a fake runner and
  `MockTransport` in tests, return source URLs after using web tools, reuse
  supplied project context, move a rough creator idea to the most useful
  next-stage deliverable, and add each Agent-visible function in its own
  `func/` module.
- Base: DuckDuckGo returns bounded results; when its markup is unavailable,
  MediaWiki returns a clearly identified narrower fallback. A one-sentence
  creator idea gets one focused question or becomes a project-ready record when
  enough context exists, even without a persistence tool.
- Bad: create a module-global Agent, let HTTPX follow redirects automatically,
  accept one public DNS result when another answer is private, trust
  `is_global` without multicast/site-local checks, return `str(error)` to the
  model, repeat questions answered in project context, jump across several
  creation stages, claim an external operation without a successful tool
  result, or recreate a flat `tools.py` that mixes all FunctionTool
  definitions.

### 6. Tests Required

- Assert the exact tool names, order, JSON schemas, and timeout formatters.
- Assert that tool factories are defined in their matching
  `services.agent.func` modules and that the registry is the single builder.
- Inject a fake runner; assert prompt/turn delegation, exception identity, and
  owned-versus-injected HTTP client closure.
- Assert that the default instructions retain the Bilibili creator workflow,
  context precedence, dialogue pacing, creation stages, artifact fields,
  commercial-project fields, honest external-operation boundary, privacy, and
  untrusted-web safety rules. Match stable concepts instead of the complete
  prompt text.
- Inject a fixed aware clock for UTC and named-timezone results.
- Use `httpx.MockTransport` for DuckDuckGo and MediaWiki; test the fixed
  endpoints, `uddg` unwrapping, fallback selection, byte caps, invalid payloads,
  and that parser defects propagate.
- Use a fake resolver for fetch tests. Cover IPv4 and IPv6 loopback, private,
  link-local, multicast, reserved, unspecified, shared, and site-local
  destinations plus mixed DNS answers.
- Assert every redirect is revalidated before transport invocation. Cover
  media types, decoded byte caps, character truncation, charset fallback, and
  removal of blocked HTML elements.
- Automated tests must not call an LLM, public DNS, or the public network.
  Keep real DuckDuckGo and webpage checks as separate best-effort smoke checks.

### 7. Wrong vs Correct

#### Wrong

```python
response = await client.get(url, follow_redirects=True)
return response.text
```

This lets redirects bypass destination validation, reads an unbounded body, and
may return binary or unsafe content.

#### Correct

```python
current_url = await validate_public_url(url, resolver)
async with client.stream("GET", current_url, follow_redirects=False) as response:
    # Revalidate each Location before the next request, check the media type,
    # and count decoded bytes while streaming.
    ...
```

Keep expected external failures in the stable tool error envelope. Leave
unexpected defects visible to the internal caller so they can be fixed.

## Scenario: Provider-Neutral Chat Completions Runtime

### 1. Scope / Trigger

- Trigger: adding or changing the REST Agent model provider, credential
  wiring, model name, or OpenAI-compatible endpoint.
- The REST Agent, compactor, and memory extractor share one per-request model
  runtime. Direct `create_agent_service()` calls keep the Agents SDK's own
  model-discovery behavior.

### 2. Signatures

```python
class ModelSettings(BaseSettings):
    api_key: SecretStr | None
    name: str | None
    base_url: AnyHttpUrl | None


def get_model_settings() -> ModelSettings: ...


def create_agent_runtime(
    settings: ModelSettings | None = None,
) -> AgentRuntime: ...
```

### 3. Contracts

| Environment key | Required for model calls | Meaning |
| --- | --- | --- |
| `MODEL_API_KEY` | Yes | Provider credential, stored as `SecretStr` |
| `MODEL_NAME` | Yes | Chat Completions model identifier |
| `MODEL_BASE_URL` | Yes | API root or complete `/chat/completions` endpoint |

All three values are provider-neutral. The provider must implement an
OpenAI-compatible Chat Completions API. If `MODEL_BASE_URL` ends with
`/chat/completions`, the runtime strips that suffix before constructing
`AsyncOpenAI` because the client appends it when sending a request.

### 4. Validation & Error Matrix

| Condition | Behavior |
| --- | --- |
| Any required `MODEL_*` value is absent or blank | Raise `AgentUnavailableError` when constructing the REST runtime |
| `MODEL_BASE_URL` is not an HTTP(S) URL | Pydantic settings validation fails |
| API root URL is supplied | Preserve the root after trimming a trailing slash |
| Complete `/chat/completions` URL is supplied | Normalize it to the API root |
| Legacy provider-specific variables are supplied alone | Treat the model runtime as unconfigured |
| Provider rejects the key, model, or request | Propagate the provider/client error |

### 5. Good / Base / Bad Cases

- Good: inject all `MODEL_*` values from deployment secrets and select any
  compatible provider without changing application code.
- Base: place the three values in the ignored local `.env` for development.
- Bad: add provider names to settings classes, commit a real key, configure
  `MODEL_MODEL`, or silently fall back to obsolete environment names.

### 6. Tests Required

- Parse all three `MODEL_*` variables through the real settings class.
- Assert blank optional values normalize to `None`.
- Assert obsolete provider-specific variables do not configure the runtime.
- Assert both API-root and complete Chat Completions URLs normalize correctly.
- Keep live provider calls outside the deterministic automated suite.

### 7. Wrong vs Correct

#### Wrong

```python
class VendorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VENDOR_")
    model: str
```

This couples the runtime contract to one provider and would produce ambiguous
names if only the prefix were generalized.

#### Correct

```python
class ModelSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MODEL_")
    api_key: SecretStr | None = None
    name: str | None = None
    base_url: AnyHttpUrl | None = None
```

## Scenario: Durable Agent Context and Memory

- `DatabaseAgentSession` is the sole persistence adapter for Agents SDK input
  items. It verifies `user_id`, `conversation_id`, and the committed
  `active_run_id` on every operation.
- SDK items are recursively credential-redacted, normalized once in
  `session_items.py`, encrypted, and assigned a monotonic per-conversation
  sequence. The session returns only items after
  `summary_through_sequence`; a supplied `limit` means the latest N items in
  chronological order.
- `RunConfig.call_model_input_filter` prepends profile, active memories, and
  rolling summary as untrusted model-only context. Synthetic context is never
  passed to `Session.add_items()`.
- Compaction retains the configured recent complete-turn window, writes only a
  bounded encrypted summary plus a monotonic cursor, and never deletes raw
  rows. The update requires both the previous cursor and current run ID.
- Automatic memory candidates require literal evidence in the latest
  redacted user message. Local rules may upgrade sensitivity. Sensitive
  candidates require an explicit remember phrase; credential-shaped content
  is always rejected.
- Automated Agent tests use fake runners, compactors, extractors, HTTP
  transports, clocks, and DNS resolvers. They must not call a live model or
  public network.
