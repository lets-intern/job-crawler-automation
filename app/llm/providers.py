"""어느 제공자를 쓸지 고르는 자리. 고르는 일만 하고 부르지는 않는다.

이름 하나를 항목 하나로 바꾸는 것이 전부다. 여기가 얇아야 "제공자로 분기하는 코드는 항목
안에만 있다" 가 참이 된다 (`.claude/rules/llm.md`).

**기능에 따라 다른 제공자를 쓴다.** 셀렉터 생성은 등록할 때 한 번이고 분류는 공고마다 한 번이라
성격이 다르다. 싼 제공자를 분류에 두고 정확한 제공자를 생성에 두는 선택이 가능해야 한다.
"""

from __future__ import annotations

from app.llm.base import LlmCallError, Provider
from app.llm.claude import CLAUDE
from app.llm.gemini import GEMINI
from app.llm.log import CLASSIFY
from app.llm.openai_compat import GPT_PROVIDER, QWEN_PROVIDER

PROVIDERS: dict[str, Provider] = {
    provider.name: provider for provider in (GEMINI, CLAUDE, GPT_PROVIDER, QWEN_PROVIDER)
}

# 응답이 스키마를 지키는 것에 기능이 걸려 있는 자리. 분류의 판정 칸이 닫힌 목록인 것이
# 여기 걸려 있다 (`app/classify/schema.py`).
#
# 셀렉터 생성은 여기 없다. 스키마를 벗어난 응답이 와도 `parse_selectors()` 가 거절하고 한 번
# 더 물어보는 길이 있어서다. 분류에는 그 길이 없다 — 목록에 없는 값이 와도 그럴듯해 보이고,
# 그대로 `normalized_jobs` 에 앉는다
NEEDS_SCHEMA: tuple[str, ...] = (CLASSIFY,)


def resolve(feature: str, name: str, model: str) -> Provider:
    """기능·제공자 이름·모델로 항목을 고른다. 못 고르면 세운다.

    **다른 제공자로 넘어가지 않는다.** 조용히 넘어가면 비용 기록이 거짓말이 되고, 크레딧이
    떨어진 것을 아무도 모르는 채로 다른 계정에서 돈이 나간다 (`.claude/rules/llm.md`).
    """
    provider = PROVIDERS.get(name)
    if provider is None:
        raise LlmCallError(
            "unknown_provider",
            f"제공자 `{name}` 을 모른다. 쓸 수 있는 것: {', '.join(sorted(PROVIDERS))}",
        )
    if feature in NEEDS_SCHEMA and not provider.forces_schema(model):
        raise LlmCallError(
            "no_schema_support",
            f"`{name}` 의 `{model}` 은 응답을 스키마로 강제하지 못한다. "
            f"{feature} 는 정해진 목록만 와야 해서 이 조합을 쓸 수 없다",
        )
    return provider
