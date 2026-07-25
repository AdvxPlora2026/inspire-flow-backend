# Agent Service and Outbound Tool Guidelines

> Executable contracts for the internal Agent service, no-key search, public
> webpage fetch boundary, and evidence-backed brand advisory.

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
        context: AgentRunContext | None = None,
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
    brand_advisor: BrandAdvisor | None = None,
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
create_project(title, type, audience, summary, icon_url=None,
               inspiration_ids=None, confirmed=False)
list_projects(limit=50, offset=0)
get_project(project_id)
update_project(project_id, title=None, type=None, audience=None, summary=None,
               icon_url=None, clear_icon=False)
delete_project(project_id, confirmed=False, delete_orphan_inspirations=False)
create_inspiration(content, title=None, project_ids=None, status="inbox")
list_inspirations(project_id=None, status=None, source_type=None, query=None,
                  sort_by="updated_at", sort_order="desc", limit=50, offset=0)
get_inspiration(inspiration_id)
update_inspiration(inspiration_id, title=None, content=None, status=None,
                   project_ids=None, clear_title=False)
delete_inspiration(inspiration_id, confirmed=False)
add_inspiration_project(inspiration_id, project_id)
remove_inspiration_project(inspiration_id, project_id)
update_current_user(nickname=None, avatar_url=None, clear_avatar=False)
update_user_profile_text(profile_text=None, clear_profile_text=False)
list_brands(limit=50, offset=0)
analyze_brand_project(brand_id, project_brief, project_id=None,
                      market="China mainland", focus_topics=None,
                      lookback_days=7)
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
| `fetch_webpage` | `ok`, final `url`, `content_type`, optional `title`, `text`, `truncated`, optional verified `published_at` |
| `create_project` | confirmation status plus `draft`, or created `project` |
| `list_projects` | owned `projects`, `total`, `limit`, `offset` |
| `get_project` / `update_project` | owned `project` |
| `delete_project` | confirmation preview, or deleted `project_id` |
| `create_inspiration` | immediately created owned `inspiration` |
| `list_inspirations` | owned `inspirations`, `total`, `limit`, `offset` |
| `get_inspiration` / `update_inspiration` | owned `inspiration` |
| `delete_inspiration` | confirmation preview, or deleted `inspiration_id` |
| inspiration-project link tools | mutation status plus both UUIDs |
| `update_current_user` | safe current `user` projection |
| `update_user_profile_text` | normalized nullable `profile_text` |
| `list_brands` | membership-scoped `brands`, `total`, `limit`, `offset` |
| `analyze_brand_project` | typed `report` with evidence, reasoning, uncertainty, and next research steps |

Project FunctionTools receive `AgentRunContext(db, user_id)` through
`RunContextWrapper`; this first parameter is removed from the model-visible
schema. Never accept `user_id` as a tool argument. Missing context returns
`project_context_unavailable`; unknown and foreign UUIDs both return
`project_not_found`.

Creation is draft-first. `confirmed=false` validates and displays the draft
without inserting a row. A later explicit user confirmation permits
`confirmed=true`. Deletion likewise previews the UUID and title first, then
requires explicit confirmation in a separate user turn before
`confirmed=true`. Do not use the SDK's resumable approval mechanism until the
HTTP conversation API persists and resumes suspended runs.

Project icon URLs are optional HTTP(S) values up to 2,048 characters. Project
responses always include `icon_url`, using JSON `null` when unset.
`update_project(clear_icon=true)` clears the icon; sending both a replacement
URL and `clear_icon=true` returns `invalid_project`.

Inspiration FunctionTools use the same trusted `AgentRunContext`; the durable
conversation path also supplies optional `conversation_id` and
`source_message_id`. These provenance fields and `user_id` are hidden from the
model-visible schema. Direct Agent calls may omit provenance.

A clear creative idea may call `create_inspiration` immediately and report the
successful result. Ambiguous discussion requires a question before saving.
Inspiration deletion remains preview-first and requires confirmation in a
later user turn. Project deletion previews `orphaned_inspirations`; a confirmed
cascade requires both `confirmed=true` and
`delete_orphan_inspirations=true`.

`create_project` accepts optional owned `inspiration_ids`. The confirmation
preview lists them, and confirmed creation inserts the project and links in one
transaction. Inspiration project-link tools are idempotent and never accept an
owner ID from the model.

User mutation FunctionTools also use `AgentRunContext.user_id` and never accept
an owner ID from the model. `update_current_user` may change nickname or avatar
only after the user explicitly asks; normalized nickname conflicts return a
safe `nickname_conflict` tool result. `update_user_profile_text` replaces the
complete durable summary or clears it, with an 8,000-character limit.

The Agent may proactively refresh the profile summary from ordinary
conversation only when the content is a durable fact explicitly stated by the
user. It must preserve still-valid existing facts, never promote an inference
to fact, and include sensitive information only after an explicit request to
remember it. Credential-shaped content is always rejected. The saved profile
text is included in the next turn's bounded, untrusted dynamic context but is
intentionally absent from `UserPublic` and the public `/users/me` patch
contract.

Brand tools use the same trusted context. `list_brands` returns only active
memberships. `analyze_brand_project` accepts a concrete request brief, optional
current-user project UUID, free-form market, up to five focus topics, and a
1..30 day lookback. It delegates to the same application service as
`POST /api/v1/brands/{brand_id}/advisory-reports`; no model-visible `user_id`
or alternate authorization path exists. Missing/non-member brands share
`brand_not_found`, while unknown/foreign optional projects share
`project_not_found`.

The dedicated `ModelBrandAdvisor` may call only `search_website` and
`fetch_webpage`. Its structured output is a draft. Application code rebuilds a
ledger from that run's actual successful tool call/output pairs, canonicalizes
and deduplicates public HTTP(S) URLs, rejects fabricated citations, derives
executed queries and source domains, and overlays verified fetch metadata.
SDK run-item parsing must support typed and mapping-backed `raw_item` values.
Only the first draft evidence item for a canonical URL is accepted, and its
public summary is a bounded excerpt of the actual search snippet or fetched
page text rather than model-authored evidence prose. Empty search snippets do
not create evidence; an empty fetch preserves an existing search excerpt and
otherwise does not create a ledger entry.
`sufficient` requires at least three accepted relevant items, two source
domains, and at least one verified publication inside the requested window.
Weak evidence cannot retain `high` confidence. No advisory report is persisted.

The default search provider is DuckDuckGo's HTML page. On an expected provider
failure or no parseable results, use the supported Chinese MediaWiki Action API
and report `provider="mediawiki_zh"`. DuckDuckGo HTML is an unofficial,
best-effort adapter and has no availability contract.

Search results and fetched page text are untrusted data. Default and custom
Agent instructions must forbid following instructions found inside tool output;
never expose secrets or internal context to an external page.

HTML publication time is accepted only from machine-readable
`article:published_time`, JSON-LD `datePublished`, or `<time datetime>` values.
Accepted timestamps must include a timezone and are normalized to UTC. Invalid,
undated, or conflicting metadata remains `null`; never infer a date from prose.

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
- prepare a project draft before saving and require explicit confirmation
  before project creation or deletion;
- cover budget, delivery scope, schedule, revisions, licensing, credits, and
  collaborator revenue sharing for commercial projects;
- distinguish confirmed facts, suggestions, assumptions, and pending
  decisions without inventing project state, terms, or completed actions; and
- keep other projects private and claim saves, uploads, publications,
  authorizations, payments, or deletions only after a successful tool result.
- gather a concrete brand project brief, use membership-scoped brand discovery
  when necessary, call the structured advisory tool for advice requests, and
  preserve its evidence status and confidence when summarizing the result.

Keep these product instructions in the single
`DEFAULT_AGENT_INSTRUCTIONS` constant. Tests should assert the stable concepts,
not duplicate the entire prompt. Durable callers pass authenticated ownership
in `AgentRunContext`; dynamic creative context remains in the filtered model
input.

The factory-created HTTP client uses `follow_redirects=False`,
`trust_env=False`, configured timeouts, and the configured User-Agent. The
service closes only a client it created; callers retain ownership of injected
clients. The Agents SDK owns model credential discovery through the process
environment.

`AgentRuntime` owns one bounded outbound HTTPX client and injects it into both
the conversation Agent's research tools and `ModelBrandAdvisor`. The runtime
closes the conversation Agent, outbound client, and shared model client exactly
once. Stable tests inject a fake Advisor and never require model credentials,
DNS, or public network access.

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
| Missing authenticated project run context | `project_context_unavailable` |
| Invalid project fields | `invalid_project` |
| Unknown or foreign project UUID | `project_not_found` |
| Missing authenticated inspiration run context | `inspiration_context_unavailable` |
| Invalid inspiration fields or association state | `invalid_inspiration` |
| Unknown or foreign inspiration UUID | `inspiration_not_found` |
| Missing authenticated user run context | `user_context_unavailable` |
| Invalid nickname/avatar mutation | `invalid_user` |
| Duplicate normalized nickname | `nickname_conflict` |
| Invalid or overlong profile summary | `invalid_user_profile_text` |
| Missing authenticated brand run context | `brand_context_unavailable` |
| Invalid brand advisory request | `invalid_advisory_request` |
| Unknown or inaccessible brand UUID | `brand_not_found` |
| Advisor absent or expected model/provider failure | `advisory_unavailable` |
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
- Test trusted inspiration provenance, cross-user isolation, clear-idea
  creation, filters, full/incremental links, preview-first deletion, project
  creation from inspirations, and orphan-cascade previews without a live model.
- Test user-tool schemas without `user_id`, visible-profile explicit
  authorization, profile-summary normalization/clearing, nickname conflicts,
  missing context, and cross-user isolation.
- Test brand-tool schemas without `user_id`, membership-only listing,
  brand/project non-disclosure, shared service delegation, and safe expected
  errors. Test deterministic evidence extraction, citation rejection, URL
  deduplication, publication freshness, source thresholds, and confidence
  downgrade with synthetic SDK run items.

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
