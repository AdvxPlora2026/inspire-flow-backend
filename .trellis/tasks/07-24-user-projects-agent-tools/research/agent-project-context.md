# Agent project context research

## Repository evidence

- `services/agent/func/registry.py` is the single ordered tool registry.
- `services/agent/agent.py` creates one Agent per request and delegates runs
  through `AgentService` and `AgentRunner`.
- `services/agent/conversation.py` already owns the trusted `User`, request
  database `Session`, conversation run lock, and Agent invocation.
- Existing resources scope every lookup by `(user_id, resource_id)` and map a
  foreign UUID to the same not-found error as an unknown UUID.
- Repositories query and mutate without committing; services own commits.

## Agents SDK evidence

The installed `openai-agents` version supports:

```python
Agent(..., output_type=ProjectDraft)
Runner.run(..., context=AgentRunContext(...))

@function_tool
async def tool(ctx: RunContextWrapper[AgentRunContext], ...) -> str:
    ...
```

`RunContextWrapper.context` is explicitly not sent to the model. It is the
appropriate channel for a trusted request-owned database session and user ID.
The first context parameter is removed from the model-visible JSON schema, so
the model cannot provide or override `user_id`.

The SDK also supports `needs_approval`, but approval interrupts require a
persisted resumable run state. The current conversation API persists SDK
session items but does not expose a suspended-run approval endpoint.
For the MVP, project creation and deletion use explicit two-turn tool
contracts: `confirmed=false` performs no mutation and returns a structured
confirmation request; `confirmed=true` is allowed only after the latest user
message explicitly confirms the displayed operation. The system prompt and
tests lock this rule down.

Structured `Agent(..., output_type=ProjectDraft)` validates provider output
through Pydantic and is preferable to parsing free-form JSON manually.

## Proposed runtime boundary

```python
@dataclass(frozen=True, slots=True)
class AgentRunContext:
    db: Session
    user_id: UUID


await runtime.conversation_agent.run(
    [],
    context=AgentRunContext(db=db, user_id=user.id),
    session=session,
    run_config=run_config,
)
```

Direct stateless runs may omit context. Project tools detect the missing
context and return a safe unavailable error rather than accepting an owner ID
from model arguments.

## Description drafting

Use a dedicated `ProjectDraftGenerator` protocol and a model-backed
implementation built from the same per-request model client. The dedicated
Agent uses `output_type=ProjectDraft`, has no mutation tools, and returns only
normalized `title`, `type`, `audience`, and `summary`. Automated tests inject a
fake generator and never call a provider.

## Relevant specifications

- `.trellis/spec/backend/directory-structure.md`
- `.trellis/spec/backend/database-guidelines.md`
- `.trellis/spec/backend/error-handling.md`
- `.trellis/spec/backend/quality-guidelines.md`
- `.trellis/spec/backend/agent-tools.md`
- `.trellis/spec/guides/cross-layer-thinking-guide.md`
- `.trellis/spec/guides/code-reuse-thinking-guide.md`
