# Merge contextual creator prompt

## Goal

Merge the current InspireFlow default instructions with the supplied
context-aware collaboration prompt. The result should keep creators moving
without taking control away from them, repeating known information, or
overloading each turn.

## Background

- The current Chinese prompt already defines the Bilibili creator role,
  one-sentence idea capture, incremental deliverables, commercial-project
  fields, honest project-write boundaries, and safe date/search/fetch behavior.
- The supplied prompt adds dynamic project context, explicit project stages,
  conversation pacing, output schemas, privacy rules, and a pre-response
  quality check.
- `AgentService.run()` currently accepts a single prompt string. It has no
  separate project-context parameter and stores no conversation state.
- The user delegated wording and consolidation decisions to the implementer.

## Requirements

- Keep `InspireFlow` as a Simplified-Chinese creation partner for Bilibili UP
  creators. It should help the user develop the work, not silently replace the
  user's creative decisions.
- Preserve the user's real intent instead of merely restating their words.
  Use known project context and do not ask for information that is already
  present.
- Treat explicit, current user input as newer than conflicting dynamic context
  and state which understanding changed.
- On an underspecified idea, identify the intent briefly and ask at most one
  question that most affects the next step. Offer two to four concrete options
  when that reduces effort, while allowing a custom answer.
- If the user explicitly asks for content, produce it directly instead of
  asking avoidable questions. State material assumptions and pending decisions.
- Infer the current stage from inspiration clarification, direction
  confirmation, outline, detail development, storyboard or script, shooting
  preparation, and publishing preparation. Do not jump through several stages
  in one turn.
- When information is sufficient, produce the current stage's useful artifact
  and name the next action. Preserve the existing Bilibili outline, title,
  script, storyboard, shooting checklist, asset, assignment, and delivery
  coverage.
- Use natural conversation for ordinary replies. Use selective Markdown
  hierarchy for artifacts rather than forcing the same template on every
  response.
- A storyboard must include shot number, visual, dialogue or sound, suggested
  duration, and shooting note. A script must distinguish narration, dialogue,
  visual direction, and sound or ambience.
- Preserve commercial-project coverage for budget, scope, schedule, revisions,
  rights, credits, and collaborator revenue sharing. Mark unconfirmed business
  terms for user confirmation.
- Never claim a save, upload, publication, authorization, payment, deletion, or
  other external operation unless a tool result confirms success.
- Do not expose another user or project's content. If the user asks to stop
  using context, stop referencing it; do not claim an external deletion unless
  a tool confirms it.
- Avoid false certainty for medical, legal, and financial content.
- Preserve current date, web-search, webpage-fetch, source-link, tool-error,
  prompt-injection, and secret-protection rules.
- Keep the instructions natural and compact. Consolidate repeated rules, avoid
  customer-service language and automatic praise, and do not use em or en
  dashes.

## Technical Notes

- Update only the single `DEFAULT_AGENT_INSTRUCTIONS` source of truth and its
  focused regression tests.
- Dynamic context remains caller-provided content in the existing prompt
  argument. No service signature or storage behavior changes in this task.
- Write the failing prompt-contract test before production changes.
- Tests should assert stable concepts, not duplicate the entire prompt.
- This remains a lightweight prompt-and-test task; no design or implementation
  artifact is required.

## Acceptance Criteria

- [x] The default instructions cover context precedence, no repeated questions,
      one-step progression, optional two-to-four choices, and direct execution
      when the user asks for content.
- [x] All seven creation stages are represented, and the prompt forbids jumping
      across too many stages in one turn.
- [x] Storyboard and script output contracts contain every required field.
- [x] Existing Bilibili, commercial-project, honest external-operation, and
      web-tool safety contracts remain present.
- [x] Privacy, context stop/delete behavior, and high-risk uncertainty are
      covered without claiming unavailable capabilities.
- [x] A prompt-focused test fails against the current prompt and passes after
      the merge.
- [x] Ruff checks and the complete pytest suite pass without warnings.

## Out of Scope

- Adding a structured project-context parameter, conversation memory, project
  persistence, or deletion tools.
- Adding API routes, database models, project-management tools, or model
  configuration.
- Network-dependent LLM assertions in the automated test suite.

## Risks and Deferred Items

- A longer instruction set can make model behavior rigid or repetitive. The
  merged prompt will use a few functional sections and remove duplicate rules
  from the supplied text.
- True continuity depends on callers supplying accurate project context. A
  future context schema or storage feature can make that contract executable,
  but it is not implied by this prompt-only change.
