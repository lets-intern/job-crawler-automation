"""Qwen 항목 테스트 (1.3.V).

**실제로 부르지 않는다.** 응답은 가짜 클라이언트가 돌려주고, 확인하는 것은 넷이다 —
토큰 수가 `Usage` 로 옮겨지는가, 오류가 `LlmCallError` 로 바뀌는가, 키가 비었을 때
`no_api_key` 인가, 그리고 **스키마를 강제하지 못하는 모델이 분류에서 거절되는가.**

마지막이 이 항목을 붙이는 이유의 절반이다. Qwen 은 일부 모델에서만 응답을 스키마로 강제하고,
`qwen-plus` 같은 별칭은 그 목록에 없다. 별칭으로 분류를 돌리면 판정 칸의 닫힌 목록이 부탁으로
내려앉는데, 그 사실이 조용하면 아무도 모른다 (`.claude/rules/llm.md`).
"""

from __future__ import annotations

import json
from typing import Any

import openai
import pytest

from app.config import Settings
from app.llm.base import LlmCallError
from app.llm.log import CLASSIFY, SELECTOR_GENERATE
from app.llm.openai_compat import QWEN, QWEN_PROVIDER
from app.llm.providers import resolve

ANSWER = json.dumps({"job_category": "개발·IT"}, ensure_ascii=False)


class FakeUsage:
    prompt_tokens = 4321
    completion_tokens = 120
    total_tokens = 4441


class FakeMessage:
    def __init__(self, content: str | None) -> None:
        self.content = content


class FakeChoice:
    def __init__(self, content: str | None) -> None:
        self.message = FakeMessage(content)
        self.finish_reason = "stop"


class FakeResponse:
    def __init__(self, content: str | None) -> None:
        self.choices = [FakeChoice(content)]
        self.usage = FakeUsage()


class FakeCompletions:
    """`client.chat.completions.parse` 만 흉내낸다."""

    def __init__(self, content: str | None, error: Exception | None) -> None:
        self._content = content
        self._error = error
        self.calls: list[dict[str, Any]] = []

    async def parse(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return FakeResponse(self._content)


class FakeClient:
    def __init__(self, content: str | None = ANSWER, error: Exception | None = None) -> None:
        self.completions = FakeCompletions(content, error)
        self.chat = self

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.completions.calls


def settings_with_key() -> Settings:
    return Settings(qwen_api_key="테스트키", qwen_model="qwen3.8-flash")


async def call(client: FakeClient, model: str = "qwen3.8-flash") -> tuple[str, Any]:
    return await QWEN_PROVIDER.call_model(
        client,
        model,
        "본문",
        1,
        "본문 분류",
        response_schema=dict,
        system_instruction="지시",
    )


async def test_token_counts_land_in_usage() -> None:
    """이 숫자가 없으면 나중에 비용 질문에 답할 수 없다."""
    text, usage = await call(FakeClient())

    assert text == ANSWER
    assert usage.model == "qwen3.8-flash"
    assert usage.input_tokens == 4321
    assert usage.output_tokens == 120
    assert usage.total_tokens == 4441
    assert usage.latency_ms >= 0


async def test_the_prompt_and_the_system_instruction_are_sent_apart() -> None:
    client = FakeClient()

    await call(client)

    messages = client.calls[0]["messages"]
    assert messages[0] == {"role": "system", "content": "지시"}
    assert messages[1] == {"role": "user", "content": "본문"}


async def test_the_response_schema_is_forced() -> None:
    """스키마를 넘기지 않으면 닫힌 목록이 부탁이 된다."""
    client = FakeClient()

    await call(client)

    assert client.calls[0]["response_format"] is dict


async def test_an_api_failure_becomes_our_error() -> None:
    """SDK 예외가 그대로 위로 새면 부르는 쪽이 제공자를 알아야 한다."""
    failure = openai.RateLimitError(
        "Allocated quota exceeded",
        response=_response(429),
        body=None,
    )

    with pytest.raises(LlmCallError) as caught:
        await call(FakeClient(error=failure))

    assert caught.value.reason == "api_error"
    assert "429" in str(caught.value)
    # 크레딧 소진에 전용 예외가 없다. 메시지가 남아야 한도인지 잔액인지 가를 수 있다
    assert "quota" in str(caught.value)


async def test_a_connection_failure_is_our_error_too() -> None:
    """상태 코드가 없는 실패도 같은 예외로 나가야 한다."""
    with pytest.raises(LlmCallError) as caught:
        await call(FakeClient(error=openai.APIConnectionError(request=_request())))

    assert caught.value.reason == "api_error"


async def test_a_blocked_response_reads_as_empty_text() -> None:
    """빈 응답은 파싱 실패가 된다. 예외로 터지지 않는다."""
    text, usage = await call(FakeClient(content=None))

    assert text == ""
    assert usage.input_tokens == 4321


def test_an_empty_key_stops_here_and_does_not_move_to_another_provider() -> None:
    with pytest.raises(LlmCallError) as caught:
        QWEN_PROVIDER.build_client(Settings(qwen_api_key=""))

    assert caught.value.reason == "no_api_key"


def test_the_key_is_passed_explicitly_so_the_sdk_never_reads_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SDK 는 키를 안 주면 환경의 `OPENAI_API_KEY` 를 스스로 읽는다.

    그 길이 열려 있으면 이 서비스가 설정한 적 없는 남의 키로 호출이 나가고, 비용 기록이
    거짓말이 된다.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "환경에_있던_남의_키")

    client = QWEN_PROVIDER.build_client(settings_with_key())

    assert client.api_key == "테스트키"
    assert "dashscope" in str(client.base_url)


@pytest.mark.parametrize("model", ["qwen3.8-flash", "qwen3.7-plus", "qwen3.7-max-2026-06-08"])
def test_the_models_that_force_a_schema_are_allowed_to_classify(model: str) -> None:
    assert QWEN_PROVIDER.forces_schema(model)
    assert resolve(CLASSIFY, QWEN, model) is QWEN_PROVIDER


@pytest.mark.parametrize("model", ["qwen-plus", "qwen-turbo", "qwen-flash", "qwen3.6-flash"])
def test_an_alias_cannot_be_used_for_classification(model: str) -> None:
    """별칭에서 되는 것은 `json_object` 뿐이다. 칸 이름도 값도 보장하지 않는다."""
    assert not QWEN_PROVIDER.forces_schema(model)

    with pytest.raises(LlmCallError) as caught:
        resolve(CLASSIFY, QWEN, model)

    assert caught.value.reason == "no_schema_support"


def test_an_alias_is_still_fine_for_generating_selectors() -> None:
    """생성은 응답을 다시 검증하고 한 번 더 물어보는 길이 있다. 분류에는 그 길이 없다."""
    assert resolve(SELECTOR_GENERATE, QWEN, "qwen-plus") is QWEN_PROVIDER


def test_a_provider_name_nobody_defined_is_refused() -> None:
    with pytest.raises(LlmCallError) as caught:
        resolve(CLASSIFY, "없는제공자", "아무모델")

    assert caught.value.reason == "unknown_provider"


def _request() -> Any:
    import httpx

    return httpx.Request("POST", "https://example.invalid/v1/chat/completions")


def _response(status: int) -> Any:
    import httpx

    return httpx.Response(status_code=status, request=_request())
