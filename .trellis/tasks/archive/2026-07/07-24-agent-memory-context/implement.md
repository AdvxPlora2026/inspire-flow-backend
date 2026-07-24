# Agent Memory and Context Retention Implementation Plan

> **For the implementing agent:** Load `trellis-before-dev` before product-code
> edits, follow red-green-refactor, and execute these checkboxes in order. Do
> not use a live model or public network in automated tests.

**Goal:** Add encrypted, user-scoped Agent conversations, local rolling context
compression, cross-conversation long-term memory and editable creator profiles.

**Architecture:** A project-owned Agents SDK `Session` adapter persists
encrypted SDK items in SQLite. A bounded context builder combines profile,
active memories, the rolling summary and recent turns. Separate injectable
no-tool model components summarize history and extract evidence-backed memory
candidates.

**Tech Stack:** Python 3.13, FastAPI, Pydantic Settings, synchronous SQLAlchemy
2.0, SQLite, Alembic, OpenAI Agents SDK 0.18.3, `cryptography` Fernet, uv,
pytest and Ruff.

---

## Task 1: Configuration, encryption and credential redaction

**Files:**

- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `.gitignore`
- Modify: `.env.example`
- Modify: `src/inspire_flow_backend/core/config.py`
- Create: `src/inspire_flow_backend/core/context_security.py`
- Create: `tests/core/test_context_security.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing settings tests**

Add tests proving the exact defaults, environment parsing and invalid budget
combinations:

```python
def test_agent_memory_settings_have_bounded_defaults(monkeypatch) -> None:
    clear_settings_caches()
    settings = get_settings()
    assert settings.agent_context_trigger_characters == 24_000
    assert settings.agent_context_max_characters == 48_000
    assert settings.agent_context_recent_turns == 8
    assert settings.agent_context_summary_max_characters == 6_000
    assert settings.agent_memory_max_items == 30
    assert settings.agent_memory_max_characters == 8_000
    assert settings.agent_run_lock_ttl_seconds == 600


def test_deepseek_settings_load_existing_environment_names(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "test-model")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://model.example/v1")
    settings = get_deepseek_settings()
    assert settings.api_key.get_secret_value() == "test-key"
    assert settings.model == "test-model"
    assert str(settings.base_url) == "https://model.example/v1"
```

- [ ] **Step 2: Write failing context-security tests**

Add these named cases:

- `test_context_cipher_round_trips_text_and_json`
- `test_key_file_is_created_once_with_owner_only_permissions`
- `test_environment_key_takes_precedence_over_key_file`
- `test_invalid_key_fails_closed`
- `test_fingerprint_is_stable_but_not_plain_sha256`
- `test_redactor_removes_api_key_bearer_jwt_password_and_private_key`
- `test_recursive_redaction_preserves_non_secret_sdk_item_shape`

Use a fixed test-only Fernet key and assert ciphertext does not contain the
plaintext.

- [ ] **Step 3: Run the focused tests and verify red**

Run:

```bash
uv run pytest tests/test_config.py tests/core/test_context_security.py -q
```

Expected: failures for missing settings and `context_security` imports.

- [ ] **Step 4: Add the direct encryption dependency**

Run:

```bash
uv add "cryptography>=49,<50"
```

Expected: `pyproject.toml` declares `cryptography` directly and `uv.lock`
remains valid.

- [ ] **Step 5: Implement settings contracts**

Add these configuration owners:

```python
class Settings(BaseSettings):
    agent_context_trigger_characters: int = Field(default=24_000, gt=0)
    agent_context_max_characters: int = Field(default=48_000, gt=0)
    agent_context_recent_turns: int = Field(default=8, gt=0)
    agent_context_summary_max_characters: int = Field(default=6_000, gt=0)
    agent_memory_max_items: int = Field(default=30, gt=0, le=200)
    agent_memory_max_characters: int = Field(default=8_000, gt=0)
    agent_run_lock_ttl_seconds: int = Field(default=600, gt=0)
    context_encryption_key: SecretStr | None = None
    context_encryption_key_file: Path = Path(".inspireflow-context.key")


class DeepSeekSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="DEEPSEEK_",
        extra="ignore",
    )
    api_key: SecretStr | None = None
    model: str | None = None
    base_url: AnyHttpUrl | None = None
```

Validate that trigger and component budgets cannot exceed the hard context
budget. Add cached `get_deepseek_settings()` beside `get_settings()`.

- [ ] **Step 6: Implement encryption, key resolution and redaction**

Expose one owner for all persisted context security. `ContextCipher` has the
exact public methods `from_settings(settings)`, `encrypt_text(value)`,
`decrypt_text(token)`, `encrypt_json(value)`, `decrypt_json(token)` and
`fingerprint(user_id, category, content)`. The module also exports
`redact_credentials(value) -> RedactionResult` and
`redact_json_credentials(value) -> object`.

Use an atomic create with mode `0o600` for the local key file. Never log or
return the key. Replace matches with the literal `[REDACTED_CREDENTIAL]`.

- [ ] **Step 7: Document safe configuration and ignore the key file**

Add `.inspireflow-context.key` to `.gitignore`. Add safe defaults and blank
secret fields to `.env.example`; never copy the real local DeepSeek key.

- [ ] **Step 8: Run focused checks**

Run:

```bash
uv run pytest tests/test_config.py tests/core/test_context_security.py -q
uv run ruff check src/inspire_flow_backend/core tests/core tests/test_config.py
```

Expected: all tests pass and Ruff reports no errors.

- [ ] **Step 9: Commit the security foundation**

```bash
git add pyproject.toml uv.lock .gitignore .env.example \
  src/inspire_flow_backend/core/config.py \
  src/inspire_flow_backend/core/context_security.py \
  tests/core/test_context_security.py tests/test_config.py
git commit -m "feat(agent): add encrypted context foundation"
```

## Task 2: Schema migration and SQLAlchemy models

**Files:**

- Create: `migrations/versions/20260724_0002_add_agent_memory_context.py`
- Create: `src/inspire_flow_backend/data/models/user_profile.py`
- Create: `src/inspire_flow_backend/data/models/agent_conversation.py`
- Create: `src/inspire_flow_backend/data/models/agent_message.py`
- Create: `src/inspire_flow_backend/data/models/user_memory.py`
- Modify: `src/inspire_flow_backend/data/models/user.py`
- Modify: `migrations/env.py`
- Modify: `tests/api/conftest.py`
- Modify: `tests/data/test_migrations.py`

- [ ] **Step 1: Extend migration tests before writing the revision**

Upgrade to `20260723_0001`, insert one existing user, then upgrade to head.
Assert:

```python
assert {
    "user_profiles",
    "agent_conversations",
    "agent_messages",
    "user_memories",
} <= set(inspector.get_table_names())
assert connection.scalar(
    sa.text("SELECT COUNT(*) FROM user_profiles WHERE user_id = :id"),
    {"id": str(existing_user_id)},
) == 1
```

Inspect exact columns, named unique constraints, checks, indexes and foreign-key
delete behavior from `design.md`. Downgrade to `20260723_0001` and assert only
the four new tables disappear; downgrade to base and assert all application
tables disappear.

- [ ] **Step 2: Run migration tests and verify red**

Run:

```bash
uv run pytest tests/data/test_migrations.py -q
```

Expected: new tables and revision are missing.

- [ ] **Step 3: Define the four SQLAlchemy entities**

Use the exact columns in `design.md`. Add typed relationships to `User`:

```python
profile: Mapped["UserProfile"] = relationship(
    back_populates="user",
    cascade="all, delete-orphan",
    passive_deletes=True,
    uselist=False,
)
conversations: Mapped[list["AgentConversation"]] = relationship(
    back_populates="user",
    cascade="all, delete-orphan",
    passive_deletes=True,
)
memories: Mapped[list["UserMemory"]] = relationship(
    back_populates="user",
    cascade="all, delete-orphan",
    passive_deletes=True,
)
```

Keep package `__init__.py` files side-effect free.

- [ ] **Step 4: Add the reversible Alembic revision**

Create tables in profile, conversation, message, memory order. Use explicit
named indexes and checks. Backfill profiles with one SQL insert-from-select
using the existing users' timestamps.

Import each concrete model in `migrations/env.py` and extend its metadata
assertion to all six application models.

- [ ] **Step 5: Register models in API test setup**

Import the four concrete model modules in `tests/api/conftest.py` before
`Base.metadata.create_all()`, and assert all table names are registered.

- [ ] **Step 6: Run schema checks**

Run:

```bash
uv run pytest tests/data/test_migrations.py tests/data/test_database.py -q
uv run ruff check migrations src/inspire_flow_backend/data tests/data
```

Expected: upgrade, backfill, foreign-key behavior and downgrade pass.

- [ ] **Step 7: Commit the schema**

```bash
git add migrations src/inspire_flow_backend/data/models \
  tests/api/conftest.py tests/data/test_migrations.py
git commit -m "feat(agent): add conversation and memory schema"
```

## Task 3: Creator profile service and REST resource

**Files:**

- Create: `src/inspire_flow_backend/data/repositories/profiles.py`
- Create: `src/inspire_flow_backend/schemas/profiles.py`
- Create: `src/inspire_flow_backend/services/profiles.py`
- Modify: `src/inspire_flow_backend/services/users.py`
- Modify: `src/inspire_flow_backend/data/repositories/users.py`
- Modify: `src/inspire_flow_backend/api/routes/users.py`
- Create: `tests/services/test_profiles.py`
- Create: `tests/api/test_profiles.py`
- Modify: `tests/api/test_users.py`

- [ ] **Step 1: Write failing profile schema and service tests**

Cover valid and invalid IANA zones, content-focus normalization, clearing
nullable values, empty PATCH rejection, no-op timestamp behavior and ownership.
Use this stable public shape:

```json
{
  "user_id": "00000000-0000-0000-0000-000000000001",
  "bio": null,
  "timezone": "Asia/Shanghai",
  "preferred_language": "zh-CN",
  "creator_identity": "科技区 UP 主",
  "content_focus": ["AI", "数码"],
  "collaboration_preferences": null,
  "created_at": "2026-07-24T00:00:00Z",
  "updated_at": "2026-07-24T00:00:00Z"
}
```

- [ ] **Step 2: Write failing API tests**

Assert bearer authentication and exact behavior for:

```text
GET   /api/v1/users/me/profile
PATCH /api/v1/users/me/profile
```

Also assert a newly registered user has one profile and an unknown JSON field
returns the safe `422 validation_error` envelope without echoing its value.

- [ ] **Step 3: Run profile tests and verify red**

Run:

```bash
uv run pytest tests/services/test_profiles.py tests/api/test_profiles.py \
  tests/api/test_users.py -q
```

Expected: imports/endpoints are missing.

- [ ] **Step 4: Implement profile schemas and service**

Create strict `UserProfileUpdate` and ORM-backed `UserProfilePublic`. Normalize
trimmed strings and unique `content_focus` values. `update_profile()` commits
only when at least one value actually changes.

Create the empty profile in `register_user()` before its existing commit so
user and profile remain one transaction.

- [ ] **Step 5: Add the nested profile routes**

Routes depend on `get_current_session`, delegate to the profile service and
declare `ErrorResponse` models. Routes never import repositories or models.

- [ ] **Step 6: Run focused checks**

Run:

```bash
uv run pytest tests/services/test_profiles.py tests/api/test_profiles.py \
  tests/api/test_users.py -q
uv run ruff check src/inspire_flow_backend tests/services/test_profiles.py \
  tests/api/test_profiles.py tests/api/test_users.py
```

Expected: profile and existing user behavior pass.

- [ ] **Step 7: Commit the profile resource**

```bash
git add src/inspire_flow_backend/data/repositories/profiles.py \
  src/inspire_flow_backend/data/repositories/users.py \
  src/inspire_flow_backend/schemas/profiles.py \
  src/inspire_flow_backend/services/profiles.py \
  src/inspire_flow_backend/services/users.py \
  src/inspire_flow_backend/api/routes/users.py \
  tests/services/test_profiles.py tests/api/test_profiles.py tests/api/test_users.py
git commit -m "feat(users): add creator collaboration profiles"
```

## Task 4: Long-term memory CRUD and policy

**Files:**

- Create: `src/inspire_flow_backend/data/repositories/memories.py`
- Create: `src/inspire_flow_backend/schemas/memories.py`
- Create: `src/inspire_flow_backend/services/memories.py`
- Create: `src/inspire_flow_backend/api/routes/memories.py`
- Modify: `src/inspire_flow_backend/api/router.py`
- Modify: `src/inspire_flow_backend/core/errors.py`
- Create: `tests/services/test_memories.py`
- Create: `tests/api/test_memories.py`

- [ ] **Step 1: Write failing memory-policy tests**

Test exact categories, deterministic ordering, encrypted persistence,
fingerprint deduplication and no-op updates with these named cases:

- `test_manual_memory_is_encrypted_and_returned_to_owner`
- `test_credential_memory_is_rejected_before_persistence`
- `test_foreign_memory_id_is_indistinguishable_from_unknown_id`
- `test_edit_marks_automatic_memory_as_user_edited`
- `test_inactive_memory_is_excluded_from_context_query`

- [ ] **Step 2: Write failing REST tests**

Cover `POST`, collection `GET`, item `GET`, `PATCH` and `DELETE` under
`/api/v1/users/me/memories`. Assert `limit` is 1 through 100, `offset` is
nonnegative, filters are strict and deletion returns an empty 204.

- [ ] **Step 3: Run memory tests and verify red**

Run:

```bash
uv run pytest tests/services/test_memories.py tests/api/test_memories.py -q
```

Expected: memory modules and routes are missing.

- [ ] **Step 4: Implement the repository and service contracts**

Repository functions always include `user_id`. Implement these exact
contracts:

- `get_memory(db, user_id, memory_id) -> UserMemory | None`
- `list_memories(db, user_id, *, status, category, limit, offset) ->
  tuple[list[UserMemory], int]`
- `list_active_memories_for_context(db, user_id, *, limit) ->
  list[UserMemory]`

Services decrypt only after ownership lookup. Manual creation uses
`origin=manual`; PATCH sets `user_edited=True`; unchanged payloads preserve
`updated_at`.

- [ ] **Step 5: Add memory errors and routes**

Add `MemoryNotFoundError` and `CredentialMemoryForbiddenError` to the shared
error system. Include `memories_router` under `/users/me/memories`.

- [ ] **Step 6: Run focused checks**

Run:

```bash
uv run pytest tests/services/test_memories.py tests/api/test_memories.py -q
uv run ruff check src/inspire_flow_backend tests/services/test_memories.py \
  tests/api/test_memories.py
```

Expected: memory CRUD, isolation and encrypted storage pass.

- [ ] **Step 7: Commit the memory resource**

```bash
git add src/inspire_flow_backend/core/errors.py \
  src/inspire_flow_backend/data/repositories/memories.py \
  src/inspire_flow_backend/schemas/memories.py \
  src/inspire_flow_backend/services/memories.py \
  src/inspire_flow_backend/api/routes/memories.py \
  src/inspire_flow_backend/api/router.py \
  tests/services/test_memories.py tests/api/test_memories.py
git commit -m "feat(agent): add user-scoped long-term memories"
```

## Task 5: Conversation resources, run lock and SDK session adapter

**Files:**

- Create: `src/inspire_flow_backend/data/repositories/conversations.py`
- Create: `src/inspire_flow_backend/data/repositories/messages.py`
- Create: `src/inspire_flow_backend/schemas/conversations.py`
- Create: `src/inspire_flow_backend/services/conversations.py`
- Create: `src/inspire_flow_backend/services/agent/session_items.py`
- Create: `src/inspire_flow_backend/services/agent/session.py`
- Create: `tests/services/test_conversations.py`
- Create: `tests/services/agent/test_session.py`

- [ ] **Step 1: Write failing conversation lifecycle tests**

Cover create/list/get/update/archive/unarchive/delete and user isolation with
these named cases:

- `test_delete_removes_unprotected_automatic_memories`
- `test_delete_keeps_explicit_edited_or_pinned_memories`
- `test_surviving_memory_marks_source_deleted_without_message_content`
- `test_second_live_run_cannot_claim_same_conversation`
- `test_stale_run_lock_can_be_reclaimed`

- [ ] **Step 2: Write failing SDK item and session tests**

Use representative user, assistant, function-call and function-output items.
Add these named cases:

- `test_session_appends_encrypted_items_with_monotonic_sequences`
- `test_session_get_items_returns_only_persisted_items_after_summary_cursor`
- `test_session_limit_returns_at_most_latest_items_in_order`
- `test_session_rejects_foreign_user_and_wrong_run_id`
- `test_session_pop_and_clear_update_conversation_state`

Read SQLite directly and prove message plaintext is absent.

- [ ] **Step 3: Run focused tests and verify red**

Run:

```bash
uv run pytest tests/services/test_conversations.py \
  tests/services/agent/test_session.py -q
```

Expected: conversation/session modules are missing.

- [ ] **Step 4: Implement repositories and conversation service**

Use an atomic SQLAlchemy `update()` for run claims. All resource reads include
`user_id`. Deletion applies the memory-survival rules before deleting the
conversation.

Expose
`claim_conversation_run(db, *, user_id, conversation_id, run_id, stale_before)
-> AgentConversation` and
`release_conversation_run(db, *, user_id, conversation_id, run_id) -> None`.

- [ ] **Step 5: Implement the single SDK-item contract owner**

`session_items.py` owns normalization, recursive redaction, JSON encoding,
role/type extraction, public text projection, tool-output truncation and
complete-turn grouping. No other module locally casts SDK item dictionaries.

- [ ] **Step 6: Implement `DatabaseAgentSession`**

Match the protocol and behavior in `design.md`. Reserve contiguous sequence
ranges, encrypt every normalized item and commit each SDK persistence batch.
Return only persisted items from `get_items()` and obey the requested limit
exactly. Synthetic context is owned by the model-input filter, not the session.

- [ ] **Step 7: Run focused checks**

Run:

```bash
uv run pytest tests/services/test_conversations.py \
  tests/services/agent/test_session.py -q
uv run ruff check src/inspire_flow_backend/data/repositories \
  src/inspire_flow_backend/services/conversations.py \
  src/inspire_flow_backend/services/agent/session.py \
  src/inspire_flow_backend/services/agent/session_items.py \
  tests/services
```

Expected: lifecycle, encryption, sequence and run-lock tests pass.

- [ ] **Step 8: Commit conversation persistence**

```bash
git add src/inspire_flow_backend/data/repositories/conversations.py \
  src/inspire_flow_backend/data/repositories/messages.py \
  src/inspire_flow_backend/schemas/conversations.py \
  src/inspire_flow_backend/services/conversations.py \
  src/inspire_flow_backend/services/agent/session.py \
  src/inspire_flow_backend/services/agent/session_items.py \
  tests/services/test_conversations.py tests/services/agent/test_session.py
git commit -m "feat(agent): persist isolated conversation sessions"
```

## Task 6: Bounded context builder and rolling compaction

**Files:**

- Create: `src/inspire_flow_backend/services/agent/context.py`
- Create: `src/inspire_flow_backend/services/agent/compaction.py`
- Modify: `src/inspire_flow_backend/services/agent/session.py`
- Create: `tests/services/agent/test_context.py`
- Create: `tests/services/agent/test_compaction.py`

- [ ] **Step 1: Write failing context-builder tests**

Build two users and two conversations. Exercise the model-input filter and
assert exact synthetic section order:

```text
用户资料
长期记忆
对话摘要
```

Then assert only the authenticated user's active memories are present, pinned
memories sort before recent memories, inactive/foreign data is absent,
sensitive entries are labelled, recent complete turns stay chronological and
the rendered context stays within the configured character budget.
Also assert the synthetic system item is not passed to
`DatabaseAgentSession.add_items()`.

- [ ] **Step 2: Write failing compaction tests**

Use an injectable fake:

```python
@dataclass
class FakeCompactor:
    result: str
    calls: list[CompactionInput] = field(default_factory=list)

    async def compact(self, value: CompactionInput) -> str:
        self.calls.append(value)
        return self.result
```

Cover threshold no-op, first compaction, repeated cursor advance, recent-turn
retention, raw-row preservation, optimistic cursor mismatch, empty/oversized
summary rejection and compactor exception rollback.

- [ ] **Step 3: Run focused tests and verify red**

Run:

```bash
uv run pytest tests/services/agent/test_context.py \
  tests/services/agent/test_compaction.py -q
```

Expected: context and compaction modules are missing.

- [ ] **Step 4: Implement bounded context rendering**

Define this immutable policy:

```python
@dataclass(frozen=True, slots=True)
class AgentContextPolicy:
    trigger_characters: int
    max_characters: int
    recent_turns: int
    summary_max_characters: int
    memory_max_items: int
    memory_max_characters: int
```

Implement
`build_dynamic_context(db, *, user, conversation, cipher, policy) ->
DynamicContext`. Treat every stored value as quoted context data. Fit sections
first, then add newest complete turns within the remaining budget. Truncate
model-facing tool output but never mutate stored ciphertext.

- [ ] **Step 5: Implement rolling compaction**

Define `ContextCompactor` protocol, `CompactionInput`, the model-backed
implementation and `compact_conversation_if_needed()`. Update summary
ciphertext/cursor only after a valid result and an unchanged cursor/run lock.

- [ ] **Step 6: Connect the session adapter to the context builder**

Build `ContextInputFilter` from `build_dynamic_context()`. It prepends the
synthetic system item and bounds the model-facing history through
`RunConfig.call_model_input_filter`; `DatabaseAgentSession.get_items()` remains
a protocol-correct persisted-item reader.

- [ ] **Step 7: Run focused checks**

Run:

```bash
uv run pytest tests/services/agent/test_context.py \
  tests/services/agent/test_compaction.py \
  tests/services/agent/test_session.py -q
uv run ruff check src/inspire_flow_backend/services/agent tests/services/agent
```

Expected: context limits and monotonic compaction pass.

- [ ] **Step 8: Commit local compaction**

```bash
git add src/inspire_flow_backend/services/agent/context.py \
  src/inspire_flow_backend/services/agent/compaction.py \
  src/inspire_flow_backend/services/agent/session.py \
  tests/services/agent/test_context.py \
  tests/services/agent/test_compaction.py \
  tests/services/agent/test_session.py
git commit -m "feat(agent): add bounded local context compaction"
```

## Task 7: Model runtime, evidence-backed extraction and turn orchestration

**Files:**

- Modify: `src/inspire_flow_backend/services/agent/agent.py`
- Create: `src/inspire_flow_backend/services/agent/memory_extraction.py`
- Create: `src/inspire_flow_backend/services/agent/conversation.py`
- Create: `src/inspire_flow_backend/services/agent/runtime.py`
- Modify: `src/inspire_flow_backend/api/dependencies.py`
- Modify: `src/inspire_flow_backend/core/errors.py`
- Modify: `tests/services/agent/test_agent.py`
- Create: `tests/services/agent/test_memory_extraction.py`
- Create: `tests/services/agent/test_conversation.py`

- [ ] **Step 1: Extend runner tests before changing the protocol**

Update `FakeRunner` and assert `AgentService` delegates an input list, custom
session and `RunConfig` while preserving current stateless prompt behavior:

```python
result = await service.run(
    [],
    session=expected_session,
    run_config=expected_config,
)
assert runner.calls[-1].session is expected_session
assert runner.calls[-1].run_config is expected_config
```

An empty list is valid only with a session; a blank string remains invalid.

- [ ] **Step 2: Write failing extraction-policy tests**

Add these named cases:

- `test_low_sensitivity_candidate_with_literal_evidence_is_accepted`
- `test_candidate_without_literal_user_evidence_is_rejected`
- `test_assistant_claim_is_not_saved_as_user_memory`
- `test_sensitive_candidate_requires_explicit_remember_phrase`
- `test_local_classifier_can_upgrade_sensitivity`
- `test_credential_candidate_is_always_rejected`
- `test_invalid_json_reports_failed_without_raising_into_turn`
- `test_extraction_is_limited_to_five_candidates`

- [ ] **Step 3: Write failing conversation-orchestration tests**

Use fake runner, compactor and extractor. Assert this order:

1. claim run;
2. attempt compaction;
3. redact and persist user message;
4. preload the user-scoped context input filter;
5. run Agent with `trace_include_sensitive_data=False` and that filter;
6. read persisted assistant message;
7. apply accepted memory candidates;
8. release run in `finally`.

Cover model failure, compaction fallback, extraction failure, archived
conversation, wrong owner and lock cleanup.

- [ ] **Step 4: Run focused tests and verify red**

Run:

```bash
uv run pytest tests/services/agent/test_agent.py \
  tests/services/agent/test_memory_extraction.py \
  tests/services/agent/test_conversation.py -q
```

Expected: the old runner signature and missing modules fail.

- [ ] **Step 5: Extend the runner boundary**

Change `AgentRunner.run` to accept
`starting_agent: Agent[Any]`, `input: str | list[TResponseInputItem]`, required
keyword `max_turns: int`, and optional keywords `session: Session | None` and
`run_config: RunConfig | None`, returning `RunResult`.

Pass both optional values unchanged to `Runner.run()`. Preserve existing tool
order and client ownership behavior.

- [ ] **Step 6: Implement memory extraction and policy**

Create the JSON candidate schema and no-tool extractor Agent. Verify literal
evidence and explicit remember phrases locally. Persist candidates through the
existing memory service so encryption, deduplication and credential rejection
have one owner.

- [ ] **Step 7: Implement DeepSeek runtime composition**

`create_agent_runtime()` validates all three `DEEPSEEK_*` values, creates
`AsyncOpenAI` plus `OpenAIChatCompletionsModel`, and returns an
`AgentRuntime` dataclass containing `conversation_agent: AgentService`,
`compactor: ContextCompactor` and `memory_extractor: MemoryExtractor`.
`AgentRuntime.aclose()` closes each resource it owns exactly once.

No module-global Agent or model client is created.

- [ ] **Step 8: Implement the conversation-turn service**

Expose
`run_conversation_turn(db, *, user, conversation_id, content, runtime, cipher,
settings) -> AgentTurn` as an async service function.

Map only known model/SDK failures to `AgentRunFailedError`. Always release the
run lock. Keep a successfully persisted Agent reply when extraction fails.

- [ ] **Step 9: Add injectable FastAPI dependencies**

Add async-generator `get_agent_runtime()` and cached/local
`get_context_cipher()` dependencies. Tests must be able to override both.
Profile, conversation-list and memory-list operations must not require model
credentials.

- [ ] **Step 10: Run focused checks**

Run:

```bash
uv run pytest tests/services/agent -q
uv run ruff check src/inspire_flow_backend/services/agent \
  src/inspire_flow_backend/api/dependencies.py \
  src/inspire_flow_backend/core/errors.py tests/services/agent
```

Expected: all Agent tests pass without model, DNS or network calls.

- [ ] **Step 11: Commit Agent orchestration**

```bash
git add src/inspire_flow_backend/services/agent \
  src/inspire_flow_backend/api/dependencies.py \
  src/inspire_flow_backend/core/errors.py tests/services/agent
git commit -m "feat(agent): orchestrate durable memory-aware turns"
```

## Task 8: Conversation REST API and cross-session integration

**Files:**

- Create: `src/inspire_flow_backend/api/routes/conversations.py`
- Modify: `src/inspire_flow_backend/api/router.py`
- Modify: `tests/api/conftest.py`
- Create: `tests/api/test_conversations.py`
- Modify: `tests/api/test_sessions.py`

- [ ] **Step 1: Add fake runtime fixtures**

Override `get_agent_runtime` and `get_context_cipher` in API tests. The fake
runner must persist an assistant SDK item through the supplied session so the
test exercises the real database adapter rather than returning an ad-hoc
response.

- [ ] **Step 2: Write failing REST contract tests**

Cover all endpoints from `design.md`, strict bodies, exact success statuses,
pagination and OpenAPI registration with these named cases:

- `test_new_login_session_continues_existing_conversation`
- `test_two_conversations_share_memory_but_not_raw_history`
- `test_foreign_conversation_and_messages_are_not_found`
- `test_concurrent_turn_returns_conversation_busy`
- `test_archived_conversation_rejects_turn_until_unarchived`
- `test_turn_returns_memory_updates_and_extraction_status`
- `test_agent_failure_uses_safe_error_and_preserves_user_message`

- [ ] **Step 3: Run API tests and verify red**

Run:

```bash
uv run pytest tests/api/test_conversations.py tests/api/test_sessions.py -q
```

Expected: conversation paths are absent.

- [ ] **Step 4: Implement routes as transport-only adapters**

Declare Pydantic response models and delegate every query/mutation to services.
Use authenticated `user`, request-owned `db`, cipher and runtime dependencies.
Add `conversations_router` at `/conversations`.

- [ ] **Step 5: Run API and OpenAPI checks**

Run:

```bash
uv run pytest tests/api -q
uv run ruff check src/inspire_flow_backend/api tests/api
```

Expected: existing auth behavior and all new REST contracts pass.

- [ ] **Step 6: Commit the HTTP boundary**

```bash
git add src/inspire_flow_backend/api \
  tests/api/conftest.py tests/api/test_conversations.py tests/api/test_sessions.py
git commit -m "feat(api): expose memory-aware Agent conversations"
```

## Task 9: Documentation, executable specs and full verification

**Files:**

- Modify: `README.md`
- Modify: `docs/prompt.md`
- Modify: `docs/HANDOFF_USERSYS.MD`
- Create: `docs/HANDOFF_AGENT_MEMORY.md`
- Modify: `.trellis/spec/backend/agent-tools.md`
- Modify: `.trellis/spec/backend/database-guidelines.md`
- Modify: `.trellis/spec/backend/directory-structure.md`
- Modify: `.trellis/spec/backend/error-handling.md`
- Modify: `.trellis/spec/backend/quality-guidelines.md`

- [ ] **Step 1: Update handoff documentation**

Document:

- profile, memory, conversation and message request examples with placeholder
  bearer tokens;
- the distinction between login sessions and Agent conversations;
- automatic versus explicit/sensitive memory behavior;
- conversation deletion and protected-memory survival;
- all context-budget variables;
- DeepSeek configuration without real credentials;
- local key-file behavior, deployment key injection and backup warning;
- non-streaming turn latency and safe retry behavior; and
- every stable error code.

Remove stale statements that the Agent has no route or conversation storage.

- [ ] **Step 2: Update Trellis executable contracts**

Record the final signatures, table shapes, endpoint matrix, session behavior,
compaction cursor, memory policy, encryption rule and required tests in the
owning backend spec files. Do not duplicate entire prompts or implementation
bodies.

- [ ] **Step 3: Scan for leaked secrets and stale claims**

Run:

```bash
rg -n --hidden \
  'sk-[A-Za-z0-9_-]{16,}|Bearer [A-Za-z0-9._~-]{20,}|BEGIN .*PRIVATE KEY' \
  README.md docs .env.example src tests migrations \
  --glob '!*.pyc'
rg -n 'no FastAPI route|stores no conversation state|不会保存对话历史|没有对应的 FastAPI 路由' \
  README.md docs .trellis/spec src tests
```

Expected: no real credential-like values and no stale stateless-only claim.
Test fixtures that intentionally exercise redaction must use visibly synthetic
short fragments that do not match the delivery scan.

- [ ] **Step 4: Verify migrations from both starting points**

Run the automated migration test, then use disposable files to verify:

```bash
uv run pytest tests/data/test_migrations.py -q
```

Expected: fresh upgrade/downgrade and previous-revision profile backfill pass.

- [ ] **Step 5: Run the complete quality gate**

Run exactly:

```bash
uv lock --check
uv sync --locked --dev
uv run ruff check .
uv run ruff format --check .
uv run pytest -W error
```

Expected: every command exits zero and pytest emits no warnings.

- [ ] **Step 6: Run a local HTTP smoke test without exposing credentials**

Start Uvicorn, register and log in with temporary values, create a
conversation, send one message through the configured model, list the encrypted
conversation through the API, log out, log in again and continue the same
conversation. Verify the bearer token and model key never appear in command
output, logs or SQLite plaintext.

If model credentials are unavailable, record the deterministic fake-runtime
API test as the completed smoke boundary and report the live-model check as
not run; do not weaken automated tests.

- [ ] **Step 7: Review rollback points**

Confirm:

- downgrading `20260724_0002` is documented as destructive;
- raw messages are never deleted by compaction;
- summary writes require the prior cursor and active run ID;
- failed extraction never rolls back a successful reply;
- missing encryption fails closed; and
- `.inspireflow-context.key`, `.env` and SQLite sidecars remain ignored.

- [ ] **Step 8: Commit documentation and spec updates**

```bash
git add README.md docs .env.example .gitignore
git commit -m "docs(agent): hand off context and memory system"
```

## Final review checklist

- [ ] Every PRD acceptance criterion maps to at least one named automated test
      or the bounded live smoke check.
- [ ] All user/resource lookups are scoped by authenticated `user_id`.
- [ ] Routes import schemas and services, never repositories or ORM models.
- [ ] Repositories never commit.
- [ ] Only services and the SDK session service adapter own transactions.
- [ ] SDK item parsing exists only in `session_items.py`.
- [ ] No model, DNS or public-network call exists in pytest.
- [ ] No real secret, bearer token, context key or decrypted database payload
      appears in tracked files or test failure output.
- [ ] The worktree contains only intended task changes before final commit.
