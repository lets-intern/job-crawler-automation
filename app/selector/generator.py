"""Gemini API 로 셀렉터를 생성한다.

`.claude/rules/llm.md` 가 정한 것을 그대로 담는다.

- 보내는 것은 정제·샘플링된 HTML 뿐이다. 원본 페이지를 그대로 싣지 않는다
- 응답은 셀렉터 JSON 스키마로 강제하고, 받은 뒤에도 다시 검증한다
- 깨진 응답(`unparsable`)만 1회 재생성한다. 나머지 실패는 운영자에게 넘긴다
- 생성마다 모델 ID, 입출력 토큰 수, 지연을 로그로 남긴다
- API 키는 환경변수에서만 읽고 어디에도 남기지 않는다

페이지를 가져오는 것은 공용 fetch 클라이언트다 (`.claude/rules/crawling.md`).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.genai import errors as genai_errors

from app.config import Settings, get_settings
from app.crawler.fetcher import Fetcher, get_fetcher
from app.selector.cleaner import CleanedHtml, clean_html
from app.selector.schema import SelectorSchemaError, SelectorSet, parse_selectors

logger = logging.getLogger(__name__)

# 깨진 응답에 한해 한 번 더. 2회를 넘기지 않는다 (`.claude/rules/llm.md`).
MAX_ATTEMPTS = 2

_SYSTEM_INSTRUCTION = (
    "너는 채용공고 페이지에서 CSS 셀렉터를 뽑는다. "
    "셀렉터는 BeautifulSoup 의 select() 로 그대로 쓸 수 있어야 한다. "
    "본 적 없는 클래스명을 지어내지 말고, 주어진 HTML 에 실제로 있는 것만 쓴다."
)

_PROMPT = """아래는 한 채용 사이트의 목록 페이지와 상세 페이지 HTML 이다.
script, style, 주석은 이미 걷어냈고 반복되는 목록 항목은 앞의 몇 개만 남겨 두었다.

규칙:
- list.item 은 공고 하나에 해당하는 반복 요소다. 목록 전체를 감싸는 컨테이너가 아니다.
- list.title, list.link, list.date 는 list.item 안에서 찾을 수 있는 셀렉터로 쓴다.
- list.link 는 상세 페이지로 가는 a 태그를 가리켜야 한다.
- detail.title 과 detail.body 는 반드시 채운다.
- detail.requirements, detail.deadline, detail.department 는 페이지에 해당 항목이 없으면
  빈 문자열로 둔다. 아무 요소나 억지로 고르지 않는다.

[목록 페이지 {list_url}]
{list_html}

[상세 페이지 {detail_url}]
{detail_html}
"""


class SelectorGenerationError(RuntimeError):
    """생성 실패. `reason` 으로 무엇을 해야 할지가 갈린다.

    | reason | 다음 행동 |
    |---|---|
    | `no_api_key` | 환경변수를 채운다. 서버 문제가 아니다 |
    | `api_error` | Gemini 응답 자체가 실패했다. 잠시 뒤 다시 |
    | `unparsable` | 1회 재생성까지 하고도 JSON 이 아니었다. 손으로 쓴다 |
    | `unknown_field`, `missing_field` | 모델이 스키마를 벗어났다. 손으로 쓴다 |
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


@dataclass(frozen=True)
class GenerationResult:
    selectors: SelectorSet
    usage: Usage
    attempts: int
    notes: list[str] = field(default_factory=list)


async def generate_for_urls(
    list_url: str,
    detail_url: str,
    *,
    fetcher: Fetcher | None = None,
    settings: Settings | None = None,
    client: Any | None = None,
) -> GenerationResult:
    """두 URL 을 공용 클라이언트로 가져와 셀렉터를 생성한다."""
    resolved_fetcher = fetcher or get_fetcher()
    list_html = (await resolved_fetcher.fetch(list_url)).text
    detail_html = (await resolved_fetcher.fetch(detail_url)).text
    return await generate_from_html(
        list_html,
        detail_html,
        list_url=list_url,
        detail_url=detail_url,
        settings=settings,
        client=client,
    )


async def generate_from_html(
    list_html: str,
    detail_html: str,
    *,
    list_url: str = "",
    detail_url: str = "",
    settings: Settings | None = None,
    client: Any | None = None,
) -> GenerationResult:
    """이미 가져온 HTML 로 생성한다. 저장된 픽스처로 돌릴 수 있는 경로다."""
    resolved = settings or get_settings()
    resolved_client = client or build_client(resolved)
    model = resolved.gemini_model

    cleaned_list = clean_html(list_html)
    cleaned_detail = clean_html(detail_html)
    prompt = build_prompt(cleaned_list, cleaned_detail, list_url, detail_url)

    last_error: SelectorSchemaError | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        text, usage = await _call(resolved_client, model, prompt, attempt)
        try:
            selectors = parse_selectors(text)
        except SelectorSchemaError as exc:
            logger.warning(
                "셀렉터 생성 응답 거절 model=%s attempt=%d reason=%s message=%s",
                model,
                attempt,
                exc.reason,
                exc,
            )
            if exc.reason != "unparsable":
                # 모양이 아니라 내용의 문제다. 다시 물어도 같은 답이 온다.
                raise SelectorGenerationError(exc.reason, str(exc)) from exc
            last_error = exc
            continue

        return GenerationResult(
            selectors=selectors,
            usage=usage,
            attempts=attempt,
            notes=_notes(cleaned_list, cleaned_detail),
        )

    assert last_error is not None  # 루프는 최소 한 번 돈다
    raise SelectorGenerationError(
        "unparsable", f"{MAX_ATTEMPTS}회 모두 스키마에 맞지 않았다: {last_error}"
    ) from last_error


def build_client(settings: Settings | None = None) -> genai.Client:
    """API 키는 환경변수에서만 온다. 소스에도 로그에도 남기지 않는다."""
    resolved = settings or get_settings()
    if not resolved.gemini_api_key:
        raise SelectorGenerationError(
            "no_api_key", "GEMINI_API_KEY 가 비어 있다. 서버 문제가 아니라 셀렉터 생성만 막힌다"
        )
    return genai.Client(api_key=resolved.gemini_api_key)


def build_prompt(
    cleaned_list: CleanedHtml,
    cleaned_detail: CleanedHtml,
    list_url: str = "",
    detail_url: str = "",
) -> str:
    return _PROMPT.format(
        list_url=list_url,
        detail_url=detail_url,
        list_html=cleaned_list.html,
        detail_html=cleaned_detail.html,
    )


async def _call(client: Any, model: str, prompt: str, attempt: int) -> tuple[str, Usage]:
    """생성 1회. 모델 ID·토큰·지연을 남긴다."""
    started = time.monotonic()
    try:
        response = await client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config={
                "system_instruction": _SYSTEM_INSTRUCTION,
                "response_mime_type": "application/json",
                "response_schema": SelectorSet,
                "temperature": 0.0,
            },
        )
    except genai_errors.APIError as exc:
        # 운영자에게 보이는 문구에는 코드와 메시지만 옮긴다. 키는 헤더로만 나가므로 여기 없다.
        raise SelectorGenerationError(
            "api_error", f"Gemini 호출 실패({exc.code}): {exc.message}"
        ) from exc

    latency_ms = int((time.monotonic() - started) * 1000)
    usage = _usage(model, response, latency_ms)
    logger.info(
        "셀렉터 생성 model=%s attempt=%d input_tokens=%d output_tokens=%d "
        "total_tokens=%d latency_ms=%d finish_reason=%s",
        usage.model,
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
    """본문을 꺼낸다. 막히거나 잘린 응답은 빈 문자열로 와서 `unparsable` 이 된다."""
    return getattr(response, "text", None) or ""


def _notes(cleaned_list: CleanedHtml, cleaned_detail: CleanedHtml) -> list[str]:
    """입력을 좁혔거나 잘랐으면 응답에 남긴다 (`.claude/rules/llm.md`)."""
    return [f"목록: {note}" for note in cleaned_list.notes()] + [
        f"상세: {note}" for note in cleaned_detail.notes()
    ]
