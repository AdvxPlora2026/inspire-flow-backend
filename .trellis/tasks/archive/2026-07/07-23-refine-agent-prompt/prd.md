# Refine InspireFlow agent prompt

## Goal

Make the default Agent prompt describe InspireFlow as a practical creation
assistant for Bilibili creators. It should catch a rough idea quickly and help
move it toward a publishable video or a clearly defined commercial delivery.

## Background

- `DEFAULT_AGENT_INSTRUCTIONS` currently describes only a concise,
  source-aware assistant and the rules for the three existing tools.
- The Agent currently exposes date, web search, and webpage fetch tools. It
  does not expose project persistence or project-selection tools.
- Existing security rules require all search and webpage content to remain
  untrusted and forbid following instructions found in tool output.
- The intended audience is Chinese-speaking Bilibili creators, so the default
  product instructions will be written in natural Chinese.

## Requirements

- Keep the product name `InspireFlow` and identify it as an assistant for
  Bilibili UP creators.
- When a user shares even a one-sentence idea, preserve the original intent,
  capture the useful core, and avoid blocking momentum with a long
  questionnaire. Ask only the question that most affects the next step when
  information is missing.
- Guide work incrementally from an idea to the appropriate current-stage
  deliverable, including a Bilibili outline, script or storyboard, and shooting
  or asset checklist.
- When project-write capability is available, place the idea into the suitable
  project. When it is not available, provide a project-ready record and never
  claim that the idea was saved.
- For commercial projects, cover budget, delivery scope, schedule, revision
  count, rights or licensing, credits, and collaborator revenue sharing.
  Unconfirmed figures or terms must be presented as options or pending
  decisions, not invented facts.
- Clearly distinguish confirmed information, suggestions, assumptions, and
  pending decisions. Never fabricate project state or completed actions.
- Preserve the existing date, search, fetch, source-link, tool-error, prompt
  injection, and secret-protection rules.
- Keep the prompt direct and natural. Avoid promotional slogans, repetitive
  summaries, decorative headings, and em or en dashes.

## Technical Notes

- Change the existing `DEFAULT_AGENT_INSTRUCTIONS` constant rather than
  introducing a second source of truth.
- Add a focused unit test before changing the prompt. The test should assert
  stable behavioral concepts instead of the entire prompt text.
- This is a lightweight prompt-and-test change; no design or implementation
  artifact is required.

## Acceptance Criteria

- [x] The default prompt names InspireFlow and its Bilibili creator role.
- [x] The prompt covers idea capture, project routing without false save
      claims, incremental outline/storyboard/shooting-list work, and the
      commercial-project fields listed above.
- [x] Existing tool-use and untrusted-web-content safety requirements remain
      present.
- [x] Prompt-focused tests fail against the old prompt and pass after the
      rewrite.
- [x] Ruff formatting and lint checks pass.
- [x] The complete pytest suite passes with warnings treated as errors.

## Out of Scope

- Adding project storage, project-selection tools, APIs, database fields, or
  conversation memory.
- Automatically calculating budgets, drafting binding legal terms, or moving
  money between collaborators.
- Adding or changing the existing Agent tools or model configuration.

## Risks and Deferred Items

- The prompt can prepare a project-ready record today, but true automatic
  project assignment remains deferred until a project-management tool exists.
- Prompt behavior still depends on the selected model. This change provides
  explicit instructions and executable string-level regression coverage; it
  does not add network-dependent LLM assertions to the automated test suite.
