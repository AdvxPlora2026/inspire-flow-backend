import asyncio

from inspire_flow_backend.schemas.memories import MemoryCategory
from inspire_flow_backend.services.agent.memory_extraction import (
    ModelMemoryExtractor,
    parse_memory_candidates,
)


class FakeTextGenerator:
    def __init__(self, output: str) -> None:
        self.output = output
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.output


def candidate_json(
    *,
    category: str,
    content: str,
    evidence: str,
    sensitive: bool = False,
) -> str:
    return (
        '{"candidates":[{'
        f'"category":"{category}",'
        f'"content":"{content}",'
        f'"evidence":"{evidence}",'
        f'"sensitive":{str(sensitive).lower()}'
        "}]}"
    )


def test_low_sensitivity_candidate_with_literal_evidence_is_accepted() -> None:
    message = "我主要制作科技区视频"

    result = parse_memory_candidates(
        message,
        candidate_json(
            category="creative_focus",
            content="用户主要制作科技区视频",
            evidence=message,
        ),
    )

    assert result.status == "completed"
    assert len(result.candidates) == 1
    assert result.candidates[0].category is MemoryCategory.creative_focus
    assert result.candidates[0].origin == "automatic"


def test_candidate_without_literal_user_evidence_is_rejected() -> None:
    result = parse_memory_candidates(
        "我在想下一期选题",
        candidate_json(
            category="creative_focus",
            content="用户主要制作科技视频",
            evidence="我主要制作科技视频",
        ),
    )

    assert result.status == "completed"
    assert result.candidates == ()


def test_assistant_claim_is_not_saved_as_user_memory() -> None:
    message = "你说我主要制作美食视频，但我没确认"

    result = parse_memory_candidates(
        message,
        candidate_json(
            category="creative_focus",
            content="用户主要制作美食视频",
            evidence="你说我主要制作美食视频",
        ),
    )

    assert result.candidates == ()


def test_sensitive_candidate_requires_explicit_remember_phrase() -> None:
    raw = candidate_json(
        category="personal_detail",
        content="用户生日是 7 月 24 日",
        evidence="我的生日是 7 月 24 日",
        sensitive=True,
    )

    implicit = parse_memory_candidates("我的生日是 7 月 24 日", raw)
    explicit = parse_memory_candidates("请记住我的生日是 7 月 24 日", raw)

    assert implicit.candidates == ()
    assert explicit.candidates[0].is_sensitive is True
    assert explicit.candidates[0].origin == "explicit"


def test_local_classifier_can_upgrade_sensitivity() -> None:
    message = "以后要记得我的邮箱是 aria@example.com"

    result = parse_memory_candidates(
        message,
        candidate_json(
            category="other",
            content="用户邮箱是 aria@example.com",
            evidence="我的邮箱是 aria@example.com",
            sensitive=False,
        ),
    )

    assert result.candidates[0].is_sensitive is True


def test_credential_candidate_is_always_rejected() -> None:
    message = "请记住 api_key=test-secret-placeholder"

    result = parse_memory_candidates(
        message,
        candidate_json(
            category="other",
            content="api_key=test-secret-placeholder",
            evidence=message,
            sensitive=True,
        ),
    )

    assert result.candidates == ()


def test_invalid_json_reports_failed_without_raising_into_turn() -> None:
    extractor = ModelMemoryExtractor(FakeTextGenerator("not-json"))

    result = asyncio.run(extractor.extract("我喜欢科技视频"))

    assert result.status == "failed"
    assert result.candidates == ()


def test_extraction_is_limited_to_five_candidates() -> None:
    message = "我喜欢科技、数码、AI、相机、剪辑、旅行"
    candidates = [
        {
            "category": "creative_preference",
            "content": f"偏好 {value}",
            "evidence": value,
            "sensitive": False,
        }
        for value in ("科技", "数码", "AI", "相机", "剪辑", "旅行")
    ]
    import json

    result = parse_memory_candidates(
        message,
        json.dumps({"candidates": candidates}, ensure_ascii=False),
    )

    assert len(result.candidates) == 5
