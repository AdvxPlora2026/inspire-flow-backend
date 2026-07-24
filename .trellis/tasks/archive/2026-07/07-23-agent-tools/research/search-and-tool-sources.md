# Search and Tool Source Research

Research date: 2026-07-23

## General web search options

### Brave Search API

- Official general-web search API with title, URL, snippets, and other result
  types.
- Current search pricing is USD 5 per 1,000 requests and the account receives
  USD 5 in credits each month, which currently covers about 1,000 searches.
- Requires sign-up and an API credential. It is free within the monthly credit,
  not anonymous or permanently guaranteed free.
- Source:
  https://api-dashboard.search.brave.com/documentation/pricing

### SearXNG

- Officially exposes `GET` or `POST` on `/` and `/search`; JSON output is
  requested with `format=json`.
- Appropriate as a configurable self-hosted provider.
- The documentation explicitly warns that many public instances disable JSON
  output. Hard-coding a community instance would therefore create an unstable
  dependency and consume someone else's capacity without an agreement.
- Source:
  https://docs.searxng.org/dev/search_api.html

### Wikimedia / MediaWiki Action API

- Supported public JSON API with `action=query&list=search`.
- Requires no application key for ordinary public reads.
- Searches pages inside one wiki rather than the general web, so it is useful
  as a reliable no-key knowledge-search fallback but must not be described as
  full web coverage.
- Sources:
  https://www.mediawiki.org/wiki/API:Search
  https://www.mediawiki.org/wiki/API:Tutorial

### DuckDuckGo

- Official material reviewed documents the consumer search page, URL
  parameters, result sources, and Instant Answers.
- DuckDuckGo's parameter documentation says non-individual integrations should
  preserve branding/advertising and contact DuckDuckGo for partnership
  guidance.
- No supported general-results JSON API was found in the reviewed official
  documentation. Instant Answers are not equivalent to a list of general web
  results.
- Do not make HTML result-page scraping the default supported provider.
- Sources:
  https://duckduckgo.com/duckduckgo-help-pages/settings/params
  https://duckduckgo.com/duckduckgo-help-pages/results/sources
  https://duckduckgo.com/duckduckgo-help-pages/features/instant-answers-and-other-features

## Agent SDK and HTTP client

- OpenAI Agents SDK function tools derive names, descriptions, and JSON schemas
  from typed Python callables and their docstrings.
- `Runner.run()` is asynchronous and returns `RunResult`; SDK failures should
  remain observable rather than being printed and converted to `None`.
- The hosted `WebSearchTool` is available but uses the OpenAI platform and does
  not satisfy the preference for a free public data source.
- Sources:
  https://openai.github.io/openai-agents-python/tools/
  https://openai.github.io/openai-agents-python/running_agents/

- HTTPX recommends `AsyncClient` for async applications and supports bounded
  response processing through asynchronous streaming.
- Keep a scoped client instead of constructing one repeatedly in a hot loop.
- Sources:
  https://www.python-httpx.org/async/
  https://www.python-httpx.org/advanced/timeouts/

## Recommended provider policy

The user approved no-key general-web coverage as the priority. Use this
provider policy:

1. DuckDuckGo HTML search is the default and is explicitly labeled unofficial
   and best-effort.
2. Wikimedia remains available as a supported no-key knowledge-search
   fallback.
3. Brave can become a future general-web provider when a key is configured.
4. SearXNG can be selected in the future with an explicitly configured base URL for a
   self-hosted or operator-approved instance.
5. Do not hard-code a public SearXNG instance.

This keeps general search runnable without secrets. The provider boundary,
bounded parser, tests, and documentation contain the operational risk of an
unofficial HTML dependency.
