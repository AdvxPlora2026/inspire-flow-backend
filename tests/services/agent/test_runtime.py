from inspire_flow_backend.services.agent.runtime import (
    _normalize_openai_base_url,
)


def test_normalize_openai_base_url_strips_chat_completions_endpoint() -> None:
    assert (
        _normalize_openai_base_url(
            "https://model.example/v1/chat/completions",
        )
        == "https://model.example/v1"
    )


def test_normalize_openai_base_url_preserves_api_root() -> None:
    assert _normalize_openai_base_url("https://model.example/v1/") == "https://model.example/v1"
