"""OpenAI SDK 로 부르는 제공자들. 지금은 Qwen 하나다.

Qwen(DashScope)이 OpenAI 호환 엔드포인트를 준다. `openai` SDK 에 `base_url` 만 바꿔 붙기
때문에 SDK 를 하나 더 들이지 않아도 된다 (`.claude/tasks/memos/llm-provider-조사.md`).

**호환은 같은 제공자라는 뜻이 아니다.** 항목은 따로다 — 키도 모델 ID 도 요금도 다르고,
`llm_calls.provider` 에 남아야 하는 이름도 다르다. 공유하는 것은 호출하는 코드뿐이다.

`.parse()` 에 Pydantic 클래스를 그대로 넘긴다. SDK 가 `strict` JSON 스키마로 바꿔 주므로
`app/classify/schema.py` 의 클래스를 제공자마다 고쳐 둘 필요가 없다. Gemini 가 싫어하는
`additionalProperties: false` 도 이 변환이 알아서 붙인다 — 그 차이가 이 파일 안에서 끝난다.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import openai
from openai import AsyncOpenAI

from app.config import Settings
from app.llm.base import LlmCallError, Provider, Usage, log_usage

logger = logging.getLogger(__name__)

QWEN = "qwen"

# 응답을 스키마로 강제하는 Qwen 모델. 문서가 지원을 시리즈 단위로 적어서 앞자리로 맞춘다.
# **별칭(`qwen-turbo`, `qwen-plus`, `qwen-flash`)은 여기 없다.** 별칭에서 되는 것은
# `json_object` 뿐이고, 그것은 칸 이름도 값도 보장하지 않는다 — 분류에 쓸 수 없다
QWEN_SCHEMA_MODELS = (
    "qwen3.7-plus",
    "qwen3.7-flash",
    "qwen3.7-max",
    "qwen3.8-flash",
    "qwen3.8-max",
)


def _build(key_setting: str, base_url_setting: str) -> Any:
    def build_client(settings: Settings) -> AsyncOpenAI:
        """API 키는 설정에서만 온다. 소스에도 로그에도 남기지 않는다.

        키를 반드시 넘긴다. 넘기지 않으면 SDK 가 환경의 `OPENAI_API_KEY` 를 스스로 읽어,
        이 서비스가 설정한 적 없는 키로 호출이 나간다.
        """
        api_key = getattr(settings, key_setting)
        if not api_key:
            raise LlmCallError("no_api_key", f"{key_setting.upper()} 가 비어 있다")
        return AsyncOpenAI(api_key=api_key, base_url=getattr(settings, base_url_setting))

    return build_client


def _caller(name: str, label: str) -> Any:
    async def call_model(
        client: Any,
        model: str,
        prompt: str,
        attempt: int,
        kind: str,
        *,
        response_schema: Any,
        system_instruction: str,
        temperature: float = 0.0,
    ) -> tuple[str, Usage]:
        """호출 1회. 모델 ID·토큰·지연을 남긴다."""
        started = time.monotonic()
        try:
            response = await client.chat.completions.parse(
                model=model,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt},
                ],
                response_format=response_schema,
                temperature=temperature,
            )
        except openai.APIError as exc:
            # 운영자에게 보이는 문구에는 상태 코드와 메시지만 옮긴다. 키는 헤더로만 나간다.
            # 크레딧 소진에 전용 예외가 없어 429 로 오므로, 메시지를 남겨야 "한도인가
            # 잔액인가" 를 나중에 가를 수 있다
            code = getattr(exc, "status_code", "없음")
            raise LlmCallError("api_error", f"{label} 호출 실패({code}): {exc}") from exc

        latency_ms = int((time.monotonic() - started) * 1000)
        usage = _usage(model, response, latency_ms)
        log_usage(logger, kind, name, attempt, usage, _finish_reason(response))
        return _text(response), usage

    return call_model


def entry(
    name: str,
    label: str,
    key_setting: str,
    model_setting: str,
    base_url_setting: str,
    schema_models: tuple[str, ...] | None,
) -> Provider:
    """OpenAI SDK 로 부르는 제공자 항목 하나."""
    return Provider(
        name=name,
        sdk="openai",
        key_setting=key_setting,
        model_setting=model_setting,
        build_client=_build(key_setting, base_url_setting),
        call_model=_caller(name, label),
        schema_models=schema_models,
    )


QWEN_PROVIDER = entry(
    name=QWEN,
    label="Qwen",
    key_setting="qwen_api_key",
    model_setting="qwen_model",
    base_url_setting="qwen_base_url",
    schema_models=QWEN_SCHEMA_MODELS,
)


def _usage(model: str, response: Any, latency_ms: int) -> Usage:
    meta = getattr(response, "usage", None)
    return Usage(
        model=model,
        input_tokens=_count(meta, "prompt_tokens"),
        output_tokens=_count(meta, "completion_tokens"),
        total_tokens=_count(meta, "total_tokens"),
        latency_ms=latency_ms,
    )


def _count(meta: Any, name: str) -> int:
    value = getattr(meta, name, None)
    return int(value) if value is not None else 0


def _choice(response: Any) -> Any:
    choices = getattr(response, "choices", None) or []
    return choices[0] if choices else None


def _finish_reason(response: Any) -> str:
    choice = _choice(response)
    if choice is None:
        return "없음"
    return str(getattr(choice, "finish_reason", "없음"))


def _text(response: Any) -> str:
    """본문을 꺼낸다. 막히거나 잘린 응답은 빈 문자열로 와서 파싱 실패가 된다."""
    choice = _choice(response)
    if choice is None:
        return ""
    return getattr(getattr(choice, "message", None), "content", None) or ""
