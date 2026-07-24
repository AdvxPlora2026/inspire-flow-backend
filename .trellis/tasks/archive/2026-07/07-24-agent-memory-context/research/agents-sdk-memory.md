# Agents SDK session and compaction research

## Local environment

- Installed package: `openai-agents==0.18.3`.
- The current application uses an OpenAI-compatible DeepSeek Chat Completions
  model and synchronous SQLAlchemy with SQLite.
- `AgentService.run()` and `OpenAIAgentRunner.run()` are currently stateless.

## Relevant SDK capabilities

- `Runner.run(...)` accepts `context`, `previous_response_id`,
  `conversation_id`, `session` and `run_config`.
- The `Session` protocol exposes `get_items`, `add_items`, `pop_item` and
  `clear_session`.
- `SessionSettings(limit=...)` can bound how many stored items are loaded.
- `RunConfig.session_input_callback` can combine or filter stored history and
  the new input before a model call.
- `RunConfig.call_model_input_filter` receives `ModelInputData` immediately
  before every model call and can prepend or trim model-only context without
  changing which items the SDK persists.
- The SDK includes `SQLiteSession`, an async `SQLAlchemySession` extension and
  `OpenAIResponsesCompactionSession`.

## Constraints and conclusion

- `OpenAIResponsesCompactionSession` calls the OpenAI Responses compaction
  endpoint and is restricted to compatible OpenAI Responses models. It is not
  compatible with the project's current DeepSeek Chat Completions setup.
- The bundled generic session implementations do not model this application's
  required `user_id` ownership, conversation APIs, profile data or memory
  lifecycle. The SQLAlchemy extension is also async while the existing data
  layer is synchronous.
- Implement a project-owned SDK `Session` adapter backed by application tables.
  Use a provider-neutral rolling summary and a bounded recent-message window.
- Keep the custom `Session.get_items()` protocol-correct by returning only
  persisted items and honoring its `limit` exactly. Use
  `call_model_input_filter` to prepend profile, active memories and persisted
  summary, and to bound recent model-facing items without re-saving synthetic
  context.
- Preserve raw messages as the source of truth. Update the summary cursor and
  summary text transactionally only after successful compression.
