"""Ollama Cloud 항목. 실제 호출은 하지 않는다.

이 파일이 잠그는 것은 셋이다. 하나, 분류에 쓰면 거절된다 — 클라우드가 구조화 출력을 주지
않아 판정 칸의 닫힌 목록을 보장하지 못한다. 둘, 셀렉터 생성과 AI 수정에는 쓸 수 있다.
셋, 키가 없으면 `no_api_key` 로 서고 다른 제공자로 넘어가지 않는다.

근거는 `.claude/tasks/memos/llm-provider-조사.md` 의 "Ollama Cloud" 절이다.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.llm.base import LlmCallError
from app.llm.log import CLASSIFY, SELECTOR_GENERATE, SELECTOR_REPAIR
from app.llm.openai_compat import OLLAMA, OLLAMA_PROVIDER
from app.llm.providers import PROVIDERS, resolve


def test_등록되어_있다() -> None:
    assert PROVIDERS[OLLAMA] is OLLAMA_PROVIDER
    assert OLLAMA_PROVIDER.sdk == "openai"


@pytest.mark.parametrize(
    "model",
    ["gpt-oss:120b", "kimi-k3", "glm-5.2", "deepseek-v4-pro:0813", ""],
)
def test_어느_모델도_스키마를_강제하지_못한다(model: str) -> None:
    """빈 튜플이 "하나도 없다" 로 읽히는지. 여기가 뒤집히면 분류가 조용히 열린다."""
    assert OLLAMA_PROVIDER.forces_schema(model) is False


def test_분류에_지정하면_거절한다() -> None:
    with pytest.raises(LlmCallError) as caught:
        resolve(CLASSIFY, OLLAMA, "gpt-oss:120b")
    assert caught.value.reason == "no_schema_support"


@pytest.mark.parametrize("feature", [SELECTOR_GENERATE, SELECTOR_REPAIR])
def test_셀렉터_기능에는_쓸_수_있다(feature: str) -> None:
    assert resolve(feature, OLLAMA, "gpt-oss:120b") is OLLAMA_PROVIDER


def test_키가_없으면_선다() -> None:
    settings = Settings(ollama_api_key="")
    with pytest.raises(LlmCallError) as caught:
        OLLAMA_PROVIDER.build_client(settings)
    assert caught.value.reason == "no_api_key"


def test_키가_있으면_호환_주소로_붙는다() -> None:
    settings = Settings(ollama_api_key="test-key")
    client = OLLAMA_PROVIDER.build_client(settings)
    assert str(client.base_url).startswith("https://ollama.com/v1")


def test_빈_문자열_모델은_기본값으로_떨어진다() -> None:
    """compose 가 넘기는 `""` 가 없는 모델을 부르게 두지 않는다."""
    assert Settings(ollama_model="").ollama_model == "gpt-oss:120b"
    assert Settings(ollama_base_url="").ollama_base_url == "https://ollama.com/v1"
