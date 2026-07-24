# Agent memory and context retention design

## Architecture summary

Keep authentication sessions unchanged and add four application-owned
boundaries:

```text
Bearer auth -> user_id
                 |
                 +-> user_profiles --------+
                 +-> user_memories --------+--> bounded dynamic context
                 +-> agent_conversations --+          |
                             |                         v
                             +-> agent_messages -> Agents SDK runner
                                      |
                                      +-> rolling summary cursor
```

The configured model still generates replies, summaries and memory candidates,
but SQLite remains the source of truth. No provider conversation ID,
`previous_response_id` or Responses compaction endpoint is used.

The HTTP request owns a synchronous SQLAlchemy `Session`. The Agent call is
asynchronous; small SQLite operations happen before, between and after model
awaits. Services own every commit. Repositories only query or mutate.

## Evidence and compatibility

- The project uses synchronous SQLAlchemy 2.0, SQLite and Alembic.
- Authentication sessions are already user-scoped and contain no conversation
  state.
- Installed `openai-agents==0.18.3` accepts a custom `Session` in
  `Runner.run(...)`.
- The SDK reads `Session.get_items()` before a run and persists only new input
  and generated items through `Session.add_items()`.
- `RunConfig.call_model_input_filter` can add bounded dynamic context
  immediately before each model call without adding synthetic items to session
  persistence.
- `OpenAIResponsesCompactionSession` is not usable with the configured
  DeepSeek Chat Completions model.
- The custom model remains `OpenAIChatCompletionsModel` backed by an
  `AsyncOpenAI` client configured from the existing `DEEPSEEK_*` environment
  values.

## Persistence model

All UUID columns use `Uuid(as_uuid=True, native_uuid=False)`. All timestamps
use `UTCDateTime`.

### `user_profiles`

| Column | Type | Rules |
| --- | --- | --- |
| `user_id` | UUID | PK, FK `users.id`, cascade delete |
| `bio` | Text, nullable | maximum 1,000 characters at API boundary |
| `timezone` | String(64), nullable | valid IANA zone |
| `preferred_language` | String(35), nullable | trimmed, nonblank |
| `creator_identity` | String(100), nullable | trimmed, nonblank |
| `content_focus` | JSON | list of unique strings, default `[]` |
| `collaboration_preferences` | Text, nullable | maximum 2,000 characters |
| `created_at` | UTC datetime | required |
| `updated_at` | UTC datetime | required, changes only on real mutation |

Registration creates a profile in the same transaction as the user. The
migration backfills one empty profile for every existing user.

### `agent_conversations`

| Column | Type | Rules |
| --- | --- | --- |
| `id` | UUID | PK |
| `user_id` | UUID | FK `users.id`, cascade delete, indexed |
| `title` | String(120), nullable | caller supplied or first-message fallback |
| `archived_at` | UTC datetime, nullable | null means active |
| `summary_ciphertext` | Text, nullable | encrypted rolling summary |
| `summary_through_sequence` | Integer | nonnegative, default `0` |
| `summary_updated_at` | UTC datetime, nullable | set after successful compaction |
| `next_sequence` | Integer | positive, default `1` |
| `active_run_id` | UUID, nullable | optimistic per-conversation turn lock |
| `active_run_started_at` | UTC datetime, nullable | permits stale-lock recovery |
| `created_at` | UTC datetime | required |
| `updated_at` | UTC datetime | required |

Indexes support `(user_id, updated_at)` and archived filtering.

### `agent_messages`

One row stores one normalized Agents SDK input item. This preserves tool-call
pairs and assistant items without inventing a second transcript format.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | UUID | PK |
| `conversation_id` | UUID | FK conversation, cascade delete |
| `turn_id` | UUID | groups all SDK items produced by one user turn |
| `sequence` | Integer | monotonic within conversation |
| `item_type` | String(64) | normalized SDK item type |
| `role` | String(16), nullable | `user`, `assistant`, `system` or null |
| `payload_ciphertext` | Text | encrypted normalized JSON |
| `created_at` | UTC datetime | required |

`(conversation_id, sequence)` is unique. Indexes support conversation sequence
and `(conversation_id, turn_id)`. Only textual user and assistant message items
are projected to public `ConversationMessage` responses; tool items remain
internal.

### `user_memories`

| Column | Type | Rules |
| --- | --- | --- |
| `id` | UUID | PK |
| `user_id` | UUID | FK user, cascade delete |
| `category` | String(32) | validated memory category |
| `content_ciphertext` | Text | encrypted memory text |
| `content_fingerprint` | String(64) | keyed HMAC for user-local deduplication |
| `status` | String(16) | `active` or `inactive` |
| `origin` | String(16) | `automatic`, `explicit` or `manual` |
| `is_sensitive` | Boolean | required |
| `is_pinned` | Boolean | default false |
| `user_edited` | Boolean | default false |
| `source_conversation_id` | UUID, nullable | FK conversation, set null |
| `source_message_id` | UUID, nullable | FK message, set null |
| `source_deleted_at` | UTC datetime, nullable | provenance tombstone |
| `created_at` | UTC datetime | required |
| `updated_at` | UTC datetime | changes only on real mutation |

`(user_id, content_fingerprint)` is unique. Query indexes cover
`(user_id, status, is_pinned, updated_at)` and source conversation.

## Local encryption and credential handling

Add a small `ContextCipher` boundary using Fernet authenticated encryption.
`cryptography` becomes a direct runtime dependency.

Key resolution order:

1. `APP_CONTEXT_ENCRYPTION_KEY`, intended for deployed secret injection.
2. `APP_CONTEXT_ENCRYPTION_KEY_FILE`, defaulting to
   `.inspireflow-context.key`.

When the environment key is absent, local development atomically creates the
key file with owner-only permissions. The key file is Git-ignored. Failure to
load or create a valid key raises `ContextStorageUnavailableError`; plaintext
fallback is forbidden. Losing the key makes encrypted history unrecoverable,
so the README must call out backup requirements.

The cipher also creates an HMAC fingerprint over
`user_id + category + normalized_content` for deduplication without storing a
plaintext hash.

Before a user message is sent to the Agent or persisted, a shared recursive
redactor replaces recognized credential material with
`[REDACTED_CREDENTIAL]`. It covers at minimum:

- PEM private-key blocks;
- common `sk-...` API-key forms;
- bearer authorization values;
- JWT-shaped tokens; and
- explicit password/API-key/token assignments.

The same redactor processes every SDK item before encryption because tool
outputs may also contain credentials. Manual memory creation rejects any
content changed by the redactor. Automatic extraction receives only redacted
text, and persistence repeats the rejection check.

## Agents SDK session adapter

`DatabaseAgentSession` implements the SDK `Session` protocol:

```python
class DatabaseAgentSession:
    session_id: str
    session_settings = None

    async def get_items(self, limit: int | None = None) -> list[TResponseInputItem]: ...
    async def add_items(self, items: list[TResponseInputItem]) -> None: ...
    async def pop_item(self) -> TResponseInputItem | None: ...
    async def clear_session(self) -> None: ...
```

The adapter receives the request-owned database session, authenticated
`user_id`, `conversation_id`, current `turn_id`, active `run_id` and cipher.
Every operation verifies both ownership and the run lock.

`get_items()` returns only decrypted persisted items after the summary cursor.
When `limit` is supplied, it returns at most the latest `limit` persisted items
in chronological order, exactly matching the SDK protocol. It never returns a
synthetic item.

`add_items()` recursively redacts, normalizes, encrypts and appends SDK items.
It reserves a contiguous sequence range from `next_sequence`, inserts the
batch, updates conversation time and commits. `pop_item()` and
`clear_session()` exist for SDK compatibility and remain ownership/run-lock
scoped.

The conversation service saves the redacted user item first, then calls:

```python
Runner.run(
    agent,
    [],
    session=database_session,
    run_config=RunConfig(
        trace_include_sensitive_data=False,
        group_id=str(conversation.id),
        call_model_input_filter=context_input_filter,
    ),
)
```

Passing an empty new-input list prevents the user item from being duplicated;
the latest stored user item is already present in session history. Generated
assistant and tool items are persisted by the SDK adapter.

`context_input_filter` is a closure over the preloaded, user-scoped dynamic
context. Immediately before every model call it:

1. prepends one synthetic system item containing bounded profile, memory and
   summary sections labelled as untrusted contextual data;
2. keeps the newest complete persisted turns that fit;
3. preserves items produced during the active turn, including tool-call/output
   pairs; and
4. trims oversized model-facing tool output without modifying stored
   ciphertext.

Because this uses `call_model_input_filter`, synthetic context affects model
input only and can never be mistaken for a newly persisted session item.

The existing stateless `AgentService.run("...")` behavior remains available.
Its runner protocol gains optional `session` and `run_config` arguments.

## Context assembly and compaction

Configuration defaults are provider-neutral character budgets:

| Setting | Default |
| --- | ---: |
| `APP_AGENT_CONTEXT_TRIGGER_CHARACTERS` | 24,000 |
| `APP_AGENT_CONTEXT_MAX_CHARACTERS` | 48,000 |
| `APP_AGENT_CONTEXT_RECENT_TURNS` | 8 |
| `APP_AGENT_CONTEXT_SUMMARY_MAX_CHARACTERS` | 6,000 |
| `APP_AGENT_MEMORY_MAX_ITEMS` | 30 |
| `APP_AGENT_MEMORY_MAX_CHARACTERS` | 8,000 |
| `APP_AGENT_RUN_LOCK_TTL_SECONDS` | 600 |

Pydantic settings validate positive values and cross-field budget invariants.
Character accounting is intentional because the configured provider does not
expose a stable tokenizer through this application.

Before saving the current user item:

1. Load unsummarized SDK items after `summary_through_sequence`.
2. If their normalized text size is below the trigger, do nothing.
3. Group items into complete turns and keep the newest configured turn window.
4. Pass the previous summary plus older candidate turns to an injectable
   `ContextCompactor`.
5. Validate and hard-limit the resulting summary.
6. Update ciphertext, cursor and timestamp only when the cursor still matches
   the snapshot and the current run lock is held.

The default compactor uses a separate no-tool Agent with the same configured
model. Its prompt preserves confirmed facts, decisions, unresolved questions
and generated artifact state while distinguishing assumptions.

If compaction fails, no summary fields change. The context input filter still
enforces the hard limit by taking newest complete turns that fit. Oversized
tool output is truncated only in the model-facing copy; the encrypted raw item
remains unchanged.

## Automatic memory extraction

After a successful assistant response, an injectable `MemoryExtractor`
receives only the redacted latest user message and asks a no-tool Agent for
bounded JSON candidates:

```json
{
  "candidates": [
    {
      "category": "creative_focus",
      "content": "用户主要制作科技类视频",
      "evidence": "我主要做科技区视频",
      "sensitive": false
    }
  ]
}
```

The persistence policy is deterministic even though candidate generation uses
a model:

- `evidence` must be a literal substring of the latest user message;
- a local sensitive-category detector may upgrade a candidate to sensitive but
  never downgrade it;
- sensitive candidates require a local explicit-memory phrase such as
  “请记住” or “以后要记得” in the same user message;
- credential redaction/rejection runs again;
- at most five candidates are considered per turn;
- a fingerprint collision becomes a no-op or a safe touch, never an overwrite
  of a user-edited/pinned memory.

Low-sensitivity accepted candidates use `origin=automatic`. Candidates from an
explicit remember request use `origin=explicit`. Invalid JSON, invalid
evidence, policy rejection or extractor failure does not roll back the Agent
reply. The turn response reports extraction status without exposing exception
details.

Manual REST creation uses `origin=manual` and is always protected from
source-conversation cascading.

## Conversation lifecycle and concurrency

Starting a turn performs an atomic conditional update that sets a new
`active_run_id` only when no live run exists. A lock older than the configured
TTL is reclaimable. A competing request receives
`409 conversation_busy`.

The run lock stays committed while the model is awaited. Every message and
summary write verifies the same run ID. The service clears the lock in
`finally`; a crashed process is recovered by TTL rather than a permanently
open database transaction.

Archived conversations remain readable but reject new messages with
`409 conversation_archived` until unarchived.

Deleting a conversation uses one service transaction:

1. delete `origin=automatic` memories that are neither edited nor pinned;
2. set `source_deleted_at` on protected source memories;
3. delete the conversation, cascading messages and summary state;
4. let `ON DELETE SET NULL` clear surviving source foreign keys; and
5. commit once.

## REST contracts

All endpoints require bearer authentication except existing registration and
login endpoints.

### User profile

```text
GET   /api/v1/users/me/profile -> 200 UserProfilePublic
PATCH /api/v1/users/me/profile -> 200 UserProfilePublic
```

The PATCH body is strict, requires at least one supplied field and supports
explicit null to clear nullable fields. A no-op preserves `updated_at`.

### Long-term memory

```text
POST   /api/v1/users/me/memories              -> 201 UserMemoryPublic
GET    /api/v1/users/me/memories              -> 200 UserMemoryPage
GET    /api/v1/users/me/memories/{memory_id}  -> 200 UserMemoryPublic
PATCH  /api/v1/users/me/memories/{memory_id}  -> 200 UserMemoryPublic
DELETE /api/v1/users/me/memories/{memory_id}  -> 204
```

Collection reads accept bounded `limit`, `offset` and optional status/category
filters. Memory content is decrypted only after user-scoped lookup.

### Conversations and messages

```text
POST   /api/v1/conversations                              -> 201 ConversationPublic
GET    /api/v1/conversations                              -> 200 ConversationPage
GET    /api/v1/conversations/{conversation_id}            -> 200 ConversationPublic
PATCH  /api/v1/conversations/{conversation_id}            -> 200 ConversationPublic
DELETE /api/v1/conversations/{conversation_id}            -> 204
GET    /api/v1/conversations/{conversation_id}/messages   -> 200 MessagePage
POST   /api/v1/conversations/{conversation_id}/messages   -> 201 AgentTurnPublic
```

Conversation listing excludes archived rows unless requested. Message reads
use a bounded sequence cursor and return chronological public user/assistant
messages. `AgentTurnPublic` contains `turn_id`, the persisted user message, the
assistant message, accepted memory updates and
`memory_extraction_status`.

## Domain errors

All errors use the existing envelope.

| Condition | Status | Code |
| --- | ---: | --- |
| Foreign or unknown conversation | 404 | `conversation_not_found` |
| Foreign or unknown memory | 404 | `memory_not_found` |
| Archived conversation turn | 409 | `conversation_archived` |
| Concurrent conversation turn | 409 | `conversation_busy` |
| Credential-shaped memory | 422 | `credential_memory_forbidden` |
| Context key unavailable/invalid | 503 | `context_storage_unavailable` |
| Agent credentials/config unavailable | 503 | `agent_unavailable` |
| Expected upstream model failure | 502 | `agent_run_failed` |

Known OpenAI transport/API failures, max-turn exhaustion and model-behavior
failures map to the safe Agent error. Unexpected programming defects still
propagate.

## Runtime composition

`get_agent_runtime` is an async FastAPI dependency and may be overridden in
tests. It:

- loads the existing `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL` and
  `DEEPSEEK_BASE_URL` values through a dedicated settings class;
- constructs one `AsyncOpenAI` client and one
  `OpenAIChatCompletionsModel`;
- creates the main tool-enabled InspireFlow Agent plus no-tool compactor and
  extractor Agents;
- shares the model client for the request; and
- closes both the model client and any factory-owned tool HTTP client.

CRUD endpoints that do not invoke a model do not require model credentials.

## Migration and rollback

Create revision `20260724_0002` after the existing user/session revision.
Create tables in this order:

1. `user_profiles`;
2. `agent_conversations`;
3. `agent_messages`;
4. `user_memories`;
5. indexes and checks;
6. profile backfill from `users`.

Downgrade drops memories, messages, conversations and profiles in reverse
dependency order. Downgrade is destructive and requires a backup. The existing
user and authentication-session tables remain unchanged.

No rollout flag is needed because no existing endpoint changes shape. Missing
model configuration affects only the Agent-turn endpoint. Missing encryption
configuration fails closed for encrypted resources.

## File ownership map

### New files

- `migrations/versions/20260724_0002_add_agent_memory_context.py`
- `src/inspire_flow_backend/core/context_security.py`
- `src/inspire_flow_backend/data/models/user_profile.py`
- `src/inspire_flow_backend/data/models/agent_conversation.py`
- `src/inspire_flow_backend/data/models/agent_message.py`
- `src/inspire_flow_backend/data/models/user_memory.py`
- `src/inspire_flow_backend/data/repositories/profiles.py`
- `src/inspire_flow_backend/data/repositories/conversations.py`
- `src/inspire_flow_backend/data/repositories/messages.py`
- `src/inspire_flow_backend/data/repositories/memories.py`
- `src/inspire_flow_backend/schemas/profiles.py`
- `src/inspire_flow_backend/schemas/conversations.py`
- `src/inspire_flow_backend/schemas/memories.py`
- `src/inspire_flow_backend/services/profiles.py`
- `src/inspire_flow_backend/services/conversations.py`
- `src/inspire_flow_backend/services/memories.py`
- `src/inspire_flow_backend/services/agent/session_items.py`
- `src/inspire_flow_backend/services/agent/session.py`
- `src/inspire_flow_backend/services/agent/context.py`
- `src/inspire_flow_backend/services/agent/compaction.py`
- `src/inspire_flow_backend/services/agent/memory_extraction.py`
- `src/inspire_flow_backend/services/agent/conversation.py`
- `src/inspire_flow_backend/services/agent/runtime.py`
- `src/inspire_flow_backend/api/routes/conversations.py`
- `src/inspire_flow_backend/api/routes/memories.py`
- `tests/core/test_context_security.py`
- `tests/services/test_profiles.py`
- `tests/services/test_memories.py`
- `tests/services/test_conversations.py`
- `tests/services/agent/test_session.py`
- `tests/services/agent/test_context.py`
- `tests/services/agent/test_compaction.py`
- `tests/services/agent/test_memory_extraction.py`
- `tests/services/agent/test_conversation.py`
- `tests/api/test_profiles.py`
- `tests/api/test_memories.py`
- `tests/api/test_conversations.py`
- `docs/HANDOFF_AGENT_MEMORY.md`

### Modified files

- `pyproject.toml` and `uv.lock`
- `.gitignore`, `.env.example`, `README.md`, `docs/prompt.md` and
  `docs/HANDOFF_USERSYS.MD`
- `src/inspire_flow_backend/core/config.py`
- `src/inspire_flow_backend/core/errors.py`
- `src/inspire_flow_backend/data/models/user.py`
- `src/inspire_flow_backend/data/repositories/users.py`
- `src/inspire_flow_backend/services/users.py`
- `src/inspire_flow_backend/services/agent/agent.py`
- `src/inspire_flow_backend/api/dependencies.py`
- `src/inspire_flow_backend/api/router.py`
- `src/inspire_flow_backend/api/routes/users.py`
- `migrations/env.py`
- `tests/api/conftest.py`
- `tests/data/test_migrations.py`
- `tests/services/agent/test_agent.py`
- `tests/test_config.py`

Package `__init__.py` files remain free of import side effects.

## Verification strategy

- Unit tests cover encryption, key loading, redaction, profile validation,
  memory policy, SDK item normalization, context budgeting, compaction cursor
  updates and run-lock behavior.
- Repository/service tests use file-backed temporary SQLite databases.
- API tests override the Agent runtime with fakes and cover exact REST
  contracts, ownership, auth, failures and cross-session continuation.
- Migration tests upgrade a fresh database, test profile backfill from the
  previous revision, inspect keys/indexes/checks and downgrade to base.
- No automated test invokes an LLM, public DNS or public network.
- A final local smoke test may call the configured DeepSeek model only when
  credentials are available; it is not part of the deterministic suite.
