"""Claude 와 GPT 항목 테스트 (1.4.V).

**실제로 부르지 않는다.** 1.3 과 같은 모양이다 — 토큰 수가 `Usage` 로 옮겨지는가, 오류가
`LlmCallError` 로 바뀌는가, 키가 비었을 때 `no_api_key` 인가.

Claude 에는 둘이 더 있다. 합계 토큰 칸이 없어 더해야 하고, `temperature` 인자가 아예 없다.
둘 다 SDK 시그니처에서 확인한 것이라 여기서 잠가 둔다 — SDK 가 바뀌면 이 테스트가 먼저 깨진다.

마지막 묶음은 **스키마를 강제하지 못하는 조합이 분류에서 거절되는지**다. 넷 중 셋은 어느
모델이든 강제하고 Qwen 만 모델을 가린다. 그 경계가 `resolve()` 한 자리에 있는지를 본다.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic
import openai
import pytest

from app.classify.schema import Classification
from app.config import Settings
from app.llm.base import LlmCallError
from app.llm.claude import CLAUDE, MAX_TOKENS
from app.llm.log import CLASSIFY, SELECTOR_GENERATE
from app.llm.openai_compat import GPT, GPT_PROVIDER, QWEN
from app.llm.providers import PROVIDERS, resolve
from tests.test_llm_qwen import FakeClient as FakeOpenAiClient

ANSWER = json.dumps({"job_category": "개발·IT"}, ensure_ascii=False)


class FakeBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeUsage:
    input_tokens = 4321
    output_tokens = 120


class FakeMessage:
    def __init__(self, texts: list[str]) -> None:
        self.content = [FakeBlock(text) for text in texts]
        self.usage = FakeUsage()
        self.stop_reason = "end_turn"


class FakeMessages:
    def __init__(self, texts: list[str], error: Exception | None) -> None:
        self._texts = texts
        self._error = error
        self.calls: list[dict[str, Any]] = []

    async def parse(self, **kwargs: Any) -> FakeMessage:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return FakeMessage(self._texts)


class FakeAnthropic:
    def __init__(self, *texts: str, error: Exception | None = None) -> None:
        self.messages = FakeMessages(list(texts), error)

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.messages.calls


async def call_claude(client: Any, model: str = "claude-haiku-4-5-20251001") -> tuple[str, Any]:
    return await CLAUDE.call_model(
        client,
        model,
        "본문",
        1,
        "본문 분류",
        response_schema=Classification,
        system_instruction="지시",
        temperature=0.0,
    )


async def test_claude_token_counts_land_in_usage_and_the_total_is_added_up() -> None:
    """넷 중 Claude 만 합계 칸이 없다. 그대로 두면 총 토큰이 0 으로 남는다."""
    text, usage = await call_claude(FakeAnthropic(ANSWER))

    assert text == ANSWER
    assert usage.input_tokens == 4321
    assert usage.output_tokens == 120
    assert usage.total_tokens == 4441
    assert usage.latency_ms >= 0


async def test_claude_never_sends_a_temperature_it_has_no_parameter_for() -> None:
    """Messages API 에 `temperature` 가 없다. 보내면 호출이 통째로 거절된다."""
    client = FakeAnthropic(ANSWER)

    await call_claude(client)

    assert "temperature" not in client.calls[0]


async def test_claude_sends_the_required_max_tokens_and_the_schema() -> None:
    client = FakeAnthropic(ANSWER)

    await call_claude(client)

    sent = client.calls[0]
    assert sent["max_tokens"] == MAX_TOKENS
    assert sent["output_format"] is Classification
    assert sent["system"] == "지시"
    assert sent["messages"] == [{"role": "user", "content": "본문"}]


async def test_claude_joins_the_text_blocks() -> None:
    text, _ = await call_claude(FakeAnthropic("앞", "뒤"))

    assert text == "앞뒤"


async def test_claude_with_no_text_block_reads_as_empty() -> None:
    """막히거나 잘린 응답이다. 예외로 터지지 않고 파싱 실패가 된다."""
    text, usage = await call_claude(FakeAnthropic())

    assert text == ""
    assert usage.total_tokens == 4441


async def test_a_claude_api_failure_becomes_our_error() -> None:
    failure = anthropic.RateLimitError(
        "enforced_spend_limit_reached",
        response=_response(429),
        body=None,
    )

    with pytest.raises(LlmCallError) as caught:
        await call_claude(FakeAnthropic(error=failure))

    assert caught.value.reason == "api_error"
    assert "429" in str(caught.value)
    # 크레딧 소진에 전용 예외가 없다. 메시지가 남아야 한도인지 잔액인지 가를 수 있다
    assert "spend_limit" in str(caught.value)


def test_an_empty_claude_key_stops_here() -> None:
    with pytest.raises(LlmCallError) as caught:
        CLAUDE.build_client(Settings(claude_api_key=""))

    assert caught.value.reason == "no_api_key"


async def test_gpt_token_counts_land_in_usage() -> None:
    text, usage = await GPT_PROVIDER.call_model(
        FakeOpenAiClient(),
        "gpt-5.6-luna",
        "본문",
        1,
        "본문 분류",
        response_schema=Classification,
        system_instruction="지시",
    )

    assert text
    assert usage.model == "gpt-5.6-luna"
    assert usage.input_tokens == 4321
    assert usage.output_tokens == 120
    assert usage.total_tokens == 4441


async def test_a_gpt_api_failure_becomes_our_error() -> None:
    failure = openai.AuthenticationError("Incorrect API key", response=_response(401), body=None)

    with pytest.raises(LlmCallError) as caught:
        await GPT_PROVIDER.call_model(
            FakeOpenAiClient(error=failure),
            "gpt-5.6-luna",
            "본문",
            1,
            "본문 분류",
            response_schema=Classification,
            system_instruction="지시",
        )

    assert caught.value.reason == "api_error"
    assert "401" in str(caught.value)


def test_an_empty_gpt_key_stops_here() -> None:
    with pytest.raises(LlmCallError) as caught:
        GPT_PROVIDER.build_client(Settings(gpt_api_key=""))

    assert caught.value.reason == "no_api_key"


def test_gpt_uses_the_sdk_default_address_not_a_swapped_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """주소를 갈아 끼우는 것은 호환 엔드포인트를 쓰는 제공자뿐이다."""
    monkeypatch.setenv("OPENAI_API_KEY", "환경에_있던_남의_키")

    client = GPT_PROVIDER.build_client(Settings(gpt_api_key="테스트키"))

    assert client.api_key == "테스트키"
    assert "openai.com" in str(client.base_url)


def test_all_providers_are_registered_under_the_names_the_prd_uses() -> None:
    """`llm_calls.provider` 에 그대로 들어가는 이름이다. 여기서 갈리면 비용 집계가 갈린다.

    2026-08-27 에 `ollama` 가 다섯 번째로 들어왔다 (`../.claude/rules/llm.md`).
    """
    assert sorted(PROVIDERS) == ["claude", "gemini", "gpt", "ollama", "qwen"]


@pytest.mark.parametrize(
    ("name", "model"),
    [
        ("gemini", "gemini-3.5-flash"),
        ("claude", "claude-haiku-4-5-20251001"),
        (GPT, "gpt-5.6-luna"),
        (QWEN, "qwen3.8-flash"),
    ],
)
def test_the_providers_that_force_a_schema_may_classify(name: str, model: str) -> None:
    assert resolve(CLASSIFY, name, model).name == name


def test_the_one_combination_that_cannot_force_a_schema_is_refused_for_classification() -> None:
    """Qwen 의 별칭만 걸린다. 나머지 셋은 어느 모델이든 강제한다."""
    with pytest.raises(LlmCallError) as caught:
        resolve(CLASSIFY, QWEN, "qwen-plus")

    assert caught.value.reason == "no_schema_support"
    assert "qwen-plus" in str(caught.value)


def test_generating_selectors_does_not_demand_a_forced_schema() -> None:
    assert resolve(SELECTOR_GENERATE, QWEN, "qwen-plus").name == QWEN


def _request() -> Any:
    import httpx

    return httpx.Request("POST", "https://example.invalid/v1/messages")


def _response(status: int) -> Any:
    import httpx

    return httpx.Response(status_code=status, request=_request())
