# Move Agent tools into func package

## Goal

Move the Agent-visible function tools from the flat `tools.py` module into
`src/inspire_flow_backend/services/agent/func/`. The new package should make
each tool easy to find and extend without changing any model-visible behavior.

## Background

- `services/agent/tools.py` currently owns the `current_datetime`,
  `search_website`, and `fetch_webpage` FunctionTool definitions, shared tool
  error formatting, and the registry builder.
- `services/agent/web_search.py` and `web_fetch.py` own the underlying search,
  parsing, URL validation, and HTTP behavior. They are support services rather
  than Agent-visible function definitions.
- The only repository imports of `services.agent.tools` are `agent.py` and the
  Agent tool tests.
- The Agent tool names, order, schemas, timeout behavior, JSON envelopes, and
  dependency injection contracts are already covered by tests and backend
  specs.

## Requirements

- Create the exact package
  `src/inspire_flow_backend/services/agent/func/`.
- Give each Agent-visible function its own module:
  `current_datetime.py`, `search_website.py`, and `fetch_webpage.py`.
- Keep shared JSON error and timeout formatting in one private module rather
  than copying it between functions.
- Compose the three tools in a registry module and preserve the order
  `current_datetime`, `search_website`, `fetch_webpage`.
- Expose `build_agent_tools` and `get_current_datetime` through
  `services.agent.func` for the existing factory and focused unit tests.
- Update production and test imports to use the new package.
- Remove the old `services/agent/tools.py` after all definitions have moved.
  No compatibility shim is needed because the Agent service is internal and
  repository evidence shows no other consumers.
- Leave `web_search.py`, `web_fetch.py`, and `contracts.py` at the Agent package
  root. Their responsibilities do not change.
- Preserve all tool names, descriptions, parameter schemas, return payloads,
  validation errors, timeouts, dependency injection, and exception behavior.

## Technical Notes

- Add a failing structural test that requires the `func` package and verifies
  the defining modules before moving production code.
- Use re-export-only `func/__init__.py`; it must not create clients, tools, or
  other runtime state during import.
- This is a structural refactor with no API, database, dependency, or model
  prompt changes.
- The task is lightweight and needs only this PRD.

## Acceptance Criteria

- [x] `services/agent/func/` exists with separate function modules, a shared
      helper module, and a registry.
- [x] `agent.py` and tests import the tool builder from
      `services.agent.func`.
- [x] The old `services/agent/tools.py` no longer exists.
- [x] A regression test confirms the builder and date helper are defined under
      `services.agent.func`.
- [x] Existing tool order, schemas, outputs, safe errors, timeouts, and
      unexpected-exception behavior remain unchanged.
- [x] Ruff checks and the complete pytest suite pass without warnings.

## Out of Scope

- Moving the underlying search or webpage-fetch implementation.
- Adding, removing, or renaming Agent tools.
- Adding backwards-compatibility aliases for the old internal module path.
- Changing the Agent prompt, HTTP client lifecycle, or model configuration.

## Risks and Deferred Items

- Downstream code outside this repository that imported the internal
  `services.agent.tools` path will need to update. The project currently has no
  published compatibility contract for that module.
- Splitting a small module can create unnecessary indirection. The package is
  limited to one file per Agent-visible function, one private shared helper,
  and one registry so ownership remains clear.
