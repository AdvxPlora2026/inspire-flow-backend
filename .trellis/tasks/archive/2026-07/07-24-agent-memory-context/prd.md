# Add Agent memory and context retention

## Goal

Give InspireFlow durable, user-owned context without coupling it to one model
provider:

- keep each Agent conversation across process restarts and login sessions;
- keep model input bounded by compressing older conversation context;
- retain useful user-level knowledge across conversations;
- record collaboration-relevant user profile information; and
- prevent context, profile or memory leakage between users.

## Background

The current authentication session proves that a user is signed in, but it is
not an Agent conversation. The current `AgentService.run()` is stateless and
passes only the caller's prompt to the model. The application therefore needs
separate persistence and lifecycle rules for conversations, summaries,
long-term memories and user profiles.

For this feature:

- an **Agent conversation** owns ordered messages and one rolling compressed
  summary;
- a **long-term memory** is user-scoped knowledge that may be reused in other
  conversations; and
- a **user profile** contains explicit, editable basic information that helps
  the Agent collaborate.

## Requirements

### Conversation context

- Authenticated users can create, list, read, update, archive, resume and
  delete only their own Agent conversations.
- Every Agent turn is associated with both a user and a conversation.
- User and Agent messages remain in stable order and survive service restarts,
  logout and login through a different authentication session.
- Raw messages remain the source of truth. Compression may change what is sent
  to the model but must not delete raw history.
- Conversation-specific facts must not appear in another conversation unless
  they have separately become an active user-level memory.
- Concurrent turns for one conversation must not interleave or corrupt message
  ordering.

### Application-managed context compression

- The application owns the compression threshold, rolling summary and summary
  cursor. It must not depend on an OpenAI Responses-only compaction endpoint or
  provider-managed conversation.
- When a configurable threshold is reached, older complete turns are folded
  into the rolling summary while a configurable recent window remains
  verbatim.
- The summary records the highest message sequence it covers so the same
  messages are not summarized twice.
- Model context is bounded and assembled from the static Agent instructions,
  user profile, active memories, rolling conversation summary, recent complete
  turns and the current user input.
- Context injected from profile, memory and summaries is data, not a new source
  of instructions.
- A failed compression attempt leaves raw messages and the previous valid
  summary unchanged. The turn may continue with a bounded recent-history
  fallback.
- Thresholds, recent-window size and context budgets are configurable with safe
  defaults.

### Long-term user memory

- Long-term memories belong to one user and remain available after logout,
  login and use of a different Agent conversation.
- Each memory records a category, content, lifecycle state, sensitivity flag,
  origin, source provenance, pin/edit state and timestamps.
- Low-sensitivity facts explicitly stated by the user may become active
  memories automatically.
- The system must not promote its own inference, assistant-generated claim or
  unsupported speculation into an active memory.
- Sensitive personal information may be stored only when the user explicitly
  instructs InspireFlow to remember it.
- Passwords, authentication/session tokens, API keys, private keys and recovery
  codes must never be stored as memories, even when requested.
- Users can create, list, inspect, edit, activate/deactivate, pin/unpin and
  delete their own memories through authenticated REST endpoints.
- Only active memories are injected into model context. Selection is bounded
  and deterministic for the first version; semantic vector retrieval is not
  required.
- Memory extraction failure must not discard or replace a successful Agent
  response.

### Conversation deletion and memory provenance

- Deleting a conversation deletes its raw messages and compressed summary.
- A memory automatically extracted from that conversation is also deleted when
  it has never been edited or pinned.
- A memory survives source-conversation deletion when the user explicitly
  asked to save it, edited it or pinned it.
- A surviving memory records that its original source was deleted without
  retaining the deleted message content as provenance.

### Basic user information

- Preserve the existing `nickname`, `avatar_url`, creation time and update time.
- Add a one-to-one user profile with optional:
  - biography;
  - IANA time zone;
  - preferred language;
  - creator identity;
  - content focus areas; and
  - collaboration preferences.
- A profile exists for every user, including users created before this feature.
- Users can read and update their own profile. Changes are available to later
  Agent turns.
- Profile fields are explicit user data and must not be fabricated from
  conversational inference.
- Real name, birthday, contact details and other general personal data are not
  fixed profile fields; they may only be handled under the sensitive-memory
  rule.

### Privacy, storage and ownership

- Every conversation, message, summary, profile and memory lookup or mutation
  is scoped to the authenticated user.
- Looking up another user's resource returns the same not-found behavior as an
  unknown resource.
- Conversation payloads, summaries and memory content are encrypted at rest
  with an application-managed key. Local development may use a generated,
  Git-ignored key file; deployments may inject the key through configuration.
- Missing or invalid encryption configuration produces a controlled
  unavailable error and never falls back to plaintext storage.
- Credential-shaped content is redacted before conversation persistence and
  before model-generated memory extraction, then rejected again at the memory
  persistence boundary.
- Password hashes, authentication token hashes and configured model
  credentials are never included in Agent context, API responses or logs.
- Model tracing for context-bearing runs must not include sensitive input or
  output data.

### Compatibility and API shape

- Continue using SQLite, synchronous SQLAlchemy, service-owned transactions and
  reversible Alembic migrations.
- Continue supporting the configured OpenAI-compatible DeepSeek Chat
  Completions model.
- Expose REST resources under the existing `/api/v1` prefix for:
  - `/users/me/profile`;
  - `/users/me/memories`;
  - `/conversations`; and
  - `/conversations/{conversation_id}/messages`.
- Keep model runners, summarization, extraction and clocks injectable so tests
  never require an LLM, DNS or public network.

## Acceptance Criteria

- [ ] A user can start a conversation, complete multiple Agent turns, restart
      the application or log in with a new authentication session, and continue
      with the same conversation context.
- [ ] Two conversations owned by one user keep separate raw histories while
      sharing only that user's active profile and long-term memories.
- [ ] Two users cannot read, mutate or inject each other's conversations,
      messages, profiles, summaries or memories; foreign identifiers behave as
      not found.
- [ ] Crossing the configured threshold persists a rolling summary, retains
      the recent complete-turn window and excludes already summarized raw items
      from the next model input.
- [ ] Repeated compression advances one monotonic sequence cursor without
      duplicating summarized content or deleting raw messages.
- [ ] A compression failure leaves persisted history and the prior summary
      intact and uses a bounded fallback context.
- [ ] A simultaneous second turn for one conversation receives a stable
      conflict response instead of interleaving writes.
- [ ] Explicit low-sensitivity facts can become active memories automatically;
      unsupported inferences do not, and sensitive personal facts require an
      explicit remember instruction.
- [ ] Credential-shaped content is redacted from persisted conversation items
      and is rejected from manual or automatic memory storage.
- [ ] Automatic, unedited and unpinned memories are removed with their source
      conversation; explicit, edited or pinned memories survive with
      source-deleted provenance.
- [ ] Profile and memory REST operations validate field limits, preserve no-op
      timestamps and return only public fields.
- [ ] Agent context assembly includes profile, active memories, summary, recent
      history and current input in the documented order within configured
      bounds.
- [ ] Conversation payloads, summaries and memories are not readable as
      plaintext in SQLite.
- [ ] All new schema objects upgrade on a fresh SQLite database, backfill a
      profile for existing users and downgrade cleanly.
- [ ] Automated tests use fake model components and pass without model or
      public-network access.
- [ ] `uv lock --check`, locked dependency sync, Ruff lint/format and the full
      warning-free pytest suite pass.

## Out of Scope

- Vector embeddings, semantic search or an external vector database.
- Sharing conversations or memories between users.
- Provider-managed conversation storage or provider-specific server-side
  compaction.
- A fully offline/local language model for summary generation; this version
  stores and manages compaction locally but uses the configured model to write
  the summary.
- Streaming or background-job delivery of Agent responses.
- Encryption-key rotation or recovery when both the configured key and local
  key file are lost.
- Automatically publishing, authorizing, paying or performing external actions
  based on remembered information.
