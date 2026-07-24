# Generalize Chat Completions Model Environment

## Goal

Remove DeepSeek-specific naming from the model configuration so InspireFlow can
use any provider that exposes an OpenAI-compatible Chat Completions endpoint.

## Background

The runtime already uses the OpenAI-compatible client and accepts either an API
root URL or a full `/chat/completions` endpoint. The remaining provider coupling
is naming: configuration types, accessors, environment variables, tests, and
documentation still use `DeepSeek` / `DEEPSEEK_*`.

## Requirements

1. Replace the model environment contract with:
   - `MODEL_API_KEY`
   - `MODEL_NAME`
   - `MODEL_BASE_URL`
2. Rename the provider-specific settings type and accessor to generic model
   configuration names.
3. Keep API keys represented as `SecretStr`, blank optional values normalized
   to `None`, and the existing configuration cache behavior.
4. Keep support for both an OpenAI-compatible API root and a complete
   `/chat/completions` endpoint.
5. Update the local ignored `.env` without exposing or committing its secret.
6. Update `.env.example`, README, Agent handoff documentation, prompt
   documentation, and automated tests to use the generic names.
7. Remove active references to `DeepSeek` / `DEEPSEEK_*` from tracked product
   code and current documentation.

## Acceptance Criteria

- [x] Setting `MODEL_API_KEY`, `MODEL_NAME`, and `MODEL_BASE_URL` produces a
      complete generic model settings object.
- [x] Blank `MODEL_*` values are treated as unconfigured.
- [x] Agent runtime construction consumes the generic settings object.
- [x] Both API-root and full Chat Completions URLs remain supported.
- [x] The ignored local `.env` contains only the new `MODEL_*` model keys and
      retains the user's current values.
- [x] Current examples and handoff documents describe a provider-neutral
      OpenAI-compatible Chat Completions configuration.
- [x] No tracked current product file contains the old provider-specific
      identifiers.
- [x] Ruff checks, formatting checks, and the complete pytest suite pass
      without warnings.

## Key Decisions

- This is a clean contract replacement, not a compatibility alias: legacy
  `DEEPSEEK_*` variables will no longer configure the runtime.
- The model identifier is named `MODEL_NAME` to avoid the ambiguous
  `MODEL_MODEL`.
- This is a lightweight configuration refactor; no `design.md` or
  `implement.md` is required.

## Out of Scope

- Supporting provider-specific APIs that are not OpenAI Chat Completions
  compatible.
- Adding a provider registry, multiple simultaneous model configurations, or
  runtime model selection through HTTP endpoints.
- Changing the configured provider, model name, endpoint, or secret value.
