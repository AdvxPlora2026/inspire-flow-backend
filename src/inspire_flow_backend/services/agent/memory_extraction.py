import json
import re
from dataclasses import dataclass
from typing import Protocol

from inspire_flow_backend.core.context_security import redact_credentials
from inspire_flow_backend.schemas.memories import MemoryCategory
from inspire_flow_backend.services.agent.contracts import TextGenerator

_EXPLICIT_MEMORY_PHRASES = (
    "请记住",
    "帮我记住",
    "帮我记一下",
    "以后要记得",
    "以后记得",
    "记下来",
    "保存这个",
)
_SENSITIVE_PATTERN = re.compile(
    r"(?:真实姓名|身份证|生日|住址|地址|手机号|电话号码|电话|邮箱|"
    r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b)",
    flags=re.IGNORECASE,
)
_REPORTED_ASSISTANT_PATTERN = re.compile(
    r"(?:你|助手|AI|模型)(?:刚才|之前)?说",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class AcceptedMemoryCandidate:
    category: MemoryCategory
    content: str
    evidence: str
    is_sensitive: bool
    origin: str


@dataclass(frozen=True, slots=True)
class MemoryExtractionResult:
    status: str
    candidates: tuple[AcceptedMemoryCandidate, ...]


class MemoryExtractor(Protocol):
    async def extract(self, user_message: str) -> MemoryExtractionResult: ...


class ModelMemoryExtractor:
    def __init__(self, generator: TextGenerator) -> None:
        self._generator = generator

    async def extract(self, user_message: str) -> MemoryExtractionResult:
        prompt = render_memory_extraction_prompt(user_message)
        try:
            output = await self._generator.generate(prompt)
        except Exception:
            return MemoryExtractionResult(status="failed", candidates=())
        return parse_memory_candidates(user_message, output)


def parse_memory_candidates(
    user_message: str,
    raw_output: str,
) -> MemoryExtractionResult:
    try:
        payload = json.loads(raw_output)
    except (TypeError, ValueError, json.JSONDecodeError):
        return MemoryExtractionResult(status="failed", candidates=())
    if not isinstance(payload, dict) or not isinstance(payload.get("candidates"), list):
        return MemoryExtractionResult(status="failed", candidates=())

    explicit_request = any(phrase in user_message for phrase in _EXPLICIT_MEMORY_PHRASES)
    accepted: list[AcceptedMemoryCandidate] = []
    for raw_candidate in payload["candidates"][:5]:
        if not isinstance(raw_candidate, dict):
            continue
        candidate = _validate_candidate(
            user_message,
            raw_candidate,
            explicit_request=explicit_request,
        )
        if candidate is not None:
            accepted.append(candidate)
    return MemoryExtractionResult(
        status="completed",
        candidates=tuple(accepted),
    )


def render_memory_extraction_prompt(user_message: str) -> str:
    return (
        "从下面这条用户消息中提取最多五条可跨对话复用的长期记忆。"
        "只能使用用户明确说出的内容，不得采用助手推测。"
        "输出严格 JSON："
        '{"candidates":[{"category":"creative_focus","content":"...",'
        '"evidence":"用户原文中的连续片段","sensitive":false}]}。'
        "没有合适内容时返回空数组。\n"
        f"用户消息：{json.dumps(user_message, ensure_ascii=False)}"
    )


def _validate_candidate(
    user_message: str,
    raw_candidate: dict[object, object],
    *,
    explicit_request: bool,
) -> AcceptedMemoryCandidate | None:
    try:
        category = MemoryCategory(raw_candidate.get("category"))
    except (TypeError, ValueError):
        return None
    content = raw_candidate.get("content")
    evidence = raw_candidate.get("evidence")
    sensitive_value = raw_candidate.get("sensitive", False)
    if not isinstance(content, str) or not isinstance(evidence, str):
        return None
    normalized_content = " ".join(content.split())
    normalized_evidence = evidence.strip()
    if (
        not normalized_content
        or len(normalized_content) > 2000
        or not normalized_evidence
        or normalized_evidence not in user_message
        or _REPORTED_ASSISTANT_PATTERN.search(normalized_evidence)
    ):
        return None
    if (
        redact_credentials(normalized_content).was_redacted
        or redact_credentials(normalized_evidence).was_redacted
    ):
        return None

    locally_sensitive = bool(
        category is MemoryCategory.personal_detail
        or _SENSITIVE_PATTERN.search(normalized_content)
        or _SENSITIVE_PATTERN.search(normalized_evidence)
    )
    is_sensitive = bool(sensitive_value) or locally_sensitive
    if is_sensitive and not explicit_request:
        return None
    return AcceptedMemoryCandidate(
        category=category,
        content=normalized_content,
        evidence=normalized_evidence,
        is_sensitive=is_sensitive,
        origin="explicit" if explicit_request else "automatic",
    )
