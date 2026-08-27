"""Gemini 호출 한 자리. 클라이언트를 만들고, 한 번 부르고, 비용을 남긴다.

이 파일이 생긴 이유는 부르는 기능이 둘이 됐기 때문이다. 셀렉터 생성·고치기가 쓰던 경로를
본문 분류(`app/classify/`)가 그대로 쓴다. 두 번째 API 경로를 만들면 로그도 재시도 규칙도
두 벌이 되고, 한쪽만 고쳐진 채로 남는다 (`.claude/rules/llm.md`).

기능마다 다른 것은 셋뿐이다 — 시스템 지시, 응답 스키마, 로그에 적히는 이름(`kind`).
나머지(키를 어디서 읽는지, 어떤 예외를 어떻게 옮기는지, 무엇을 로그로 남기는지)는 같다.

API 키는 환경변수에서만 온다. 소스에도 로그에도 예외 메시지에도 남기지 않는다.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import errors as genai_errors

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

# `llm_calls.provider` 에 그대로 들어간다. 두 번째 제공자를 위한 어댑터 층은 두지 않는다
# (`.claude/rules/llm.md`).
PROVIDER = "gemini"


class LlmCallError(RuntimeError):
    """호출을 시작하지 못했거나 응답 자체가 실패했다.

    | reason | 다음 행동 |
    |---|---|
    | `no_api_key` | 환경변수를 채운다. 서버 문제가 아니다 |
    | `api_error` | 응답 자체가 실패했다. 잠시 뒤 다시 |

    부르는 기능마다 이 예외를 자기 예외로 옮겨 담는다. 화면에 나가는 문구가 기능마다 다르기
    때문이고, `reason` 은 그대로 넘긴다.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Usage:
    """호출 1회의 비용. 이 숫자가 없으면 나중에 비용 질문에 답할 수 없다."""

    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: int


def build_client(settings: Settings | None = None) -> genai.Client:
    """API 키는 환경변수에서만 온다. 소스에도 로그에도 남기지 않는다."""
    resolved = settings or get_settings()
    if not resolved.gemini_api_key:
        raise LlmCallError("no_api_key", "GEMINI_API_KEY 가 비어 있다")
    return genai.Client(api_key=resolved.gemini_api_key)


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
    """호출 1회. 모델 ID·토큰·지연을 남긴다.

    `kind` 는 로그에서 기능을 가르는 이름이다. 같은 값이 `llm_calls.feature` 로도 들어가서,
    나중에 "무엇이 토큰을 썼나" 를 기능별로 셀 수 있다 (`app/llm/log.py`).
    """
    started = time.monotonic()
    try:
        response = await client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config={
                "system_instruction": system_instruction,
                "response_mime_type": "application/json",
                "response_schema": response_schema,
                "temperature": temperature,
            },
        )
    except genai_errors.APIError as exc:
        # 운영자에게 보이는 문구에는 코드와 메시지만 옮긴다. 키는 헤더로만 나가므로 여기 없다.
        raise LlmCallError("api_error", f"Gemini 호출 실패({exc.code}): {exc.message}") from exc

    latency_ms = int((time.monotonic() - started) * 1000)
    usage = _usage(model, response, latency_ms)
    logger.info(
        "%s model=%s provider=%s attempt=%d input_tokens=%d output_tokens=%d "
        "total_tokens=%d latency_ms=%d finish_reason=%s",
        kind,
        usage.model,
        PROVIDER,
        attempt,
        usage.input_tokens,
        usage.output_tokens,
        usage.total_tokens,
        usage.latency_ms,
        _finish_reason(response),
    )
    return _text(response), usage


def _usage(model: str, response: Any, latency_ms: int) -> Usage:
    meta = getattr(response, "usage_metadata", None)
    return Usage(
        model=model,
        input_tokens=_count(meta, "prompt_token_count"),
        output_tokens=_count(meta, "candidates_token_count"),
        total_tokens=_count(meta, "total_token_count"),
        latency_ms=latency_ms,
    )


def _count(meta: Any, name: str) -> int:
    value = getattr(meta, name, None)
    return int(value) if value is not None else 0


def _finish_reason(response: Any) -> str:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return "없음"
    return str(getattr(candidates[0], "finish_reason", "없음"))


def _text(response: Any) -> str:
    """본문을 꺼낸다. 막히거나 잘린 응답은 빈 문자열로 와서 파싱 실패가 된다."""
    return getattr(response, "text", None) or ""
