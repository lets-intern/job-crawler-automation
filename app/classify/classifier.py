"""본문 하나를 열한 칸으로 나눈다.

수집은 어느 사이트나 확실히 주는 여섯 칸만 한다. 나머지를 나누는 것은 본문을 읽는 이쪽 일이다
(`.claude/tasks/todo/prd-llm-classify.md`).

## 지키는 것

**본문에 없는 것은 빈 칸이다.** 모델이 그럴듯하게 채우면 소비 측이 그것을 사실로 노출한다.
그래서 프롬프트가 "본문에 있는 글자를 그대로 옮겨라" 라고 말하고, 받은 뒤에는
`app/classify/grounding.py` 가 본문에서 그 글자를 찾는다. 못 찾은 칸은 버리고 `dropped` 에
이름을 남긴다 (`.claude/rules/llm.md` 의 "낸 것은 그 자리에서 돌려 본다").

**보내는 것은 본문뿐이고 상한이 있다.** 원본 HTML 도 페이지도 보내지 않는다. 본문이 상한을
넘으면 잘라 보내고 그 사실을 `notes` 에 남긴다. 자른 것으로 무엇을 놓쳤는지는 응답을 보는
사람이 알아야 한다.

**깨진 응답만 1회 다시 묻는다.** 스키마에 없는 칸을 지어낸 응답은 다시 물어도 같은 답이 온다.

호출 자체와 비용 기록은 `app/llm/gemini.py` 가 한다. 셀렉터 생성과 같은 경로다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.classify.grounding import ground
from app.classify.schema import (
    CLASSIFY_FIELDS,
    Classification,
    ClassifySchemaError,
    parse_classification,
)
from app.config import Settings, get_settings
from app.llm.gemini import LlmCallError, Usage
from app.llm.gemini import build_client as build_gemini_client
from app.llm.gemini import call_model as call_gemini

logger = logging.getLogger(__name__)

# `llm_calls.feature` 와 로그에 같이 쓰는 이름
FEATURE = "classify"

# 깨진 응답에 한해 한 번 더. 2회를 넘기지 않는다 (`.claude/rules/llm.md`).
MAX_ATTEMPTS = 2

# 한 번에 보내는 본문의 상한. 2026-08-26 기준 저장된 640건의 최대 본문이 11,584자라 지금은
# 아무것도 잘리지 않는다. 그래도 상한을 두는 것은, 상한이 없으면 사이트 하나가 본문에 페이지
# 전체를 담기 시작한 날 그것이 그대로 나가기 때문이다
MAX_BODY_CHARS = 12000

_SYSTEM_INSTRUCTION = (
    "너는 채용공고 본문을 정해진 칸으로 나눈다. "
    "본문에 있는 글자만 옮긴다. 요약하지 않고, 다듬지 않고, 없는 것을 지어내지 않는다."
)

_PROMPT = """아래는 채용공고 본문이다. 이것을 정해진 칸으로 나눈다.

칸:
- job_category: 직군·직무 분야
- work_location: 근무지
- career_level: 경력 구분 (신입/경력 등)
- employment_type: 고용형태 (정규직/계약직/인턴 등)
- headcount: 모집 인원
- duties: 주요 업무·담당 업무
- preferred: 우대사항
- hiring_process: 전형 절차
- requirements: 자격요건·지원자격
- department: 조직·부서
- etc_info: 위 어디에도 맞지 않는 나머지

규칙:
- **본문에 있는 글자를 그대로 옮긴다.** 말을 바꾸거나 요약하거나 정리하지 않는다. 옮긴 값은
  본문에서 그대로 찾을 수 있어야 한다.
- **본문에 없는 칸은 빈 문자열로 둔다.** 짐작해서 채우지 않는다. 회사가 그럴 것 같다거나
  보통 그렇다는 이유로 채우면 그것이 사실로 나간다.
- 여러 줄이면 본문의 줄 그대로 줄바꿈으로 잇는다.
- 한 칸에 들어갈 내용이 본문 여러 곳에 흩어져 있으면 그 조각들을 줄바꿈으로 잇는다.
  없는 연결 문장을 지어내 붙이지 않는다.
- 어느 칸에도 맞지 않는 내용만 etc_info 에 모은다. 본문 전체를 etc_info 에 넣지 않는다.
- 회사명·공고 제목·모집 시작일·마감일은 이 칸들에 넣지 않는다. 그 넷은 따로 수집한다.

[본문]
{body}
"""


class ClassifyError(RuntimeError):
    """분류 실패. `reason` 으로 무엇을 해야 할지가 갈린다.

    | reason | 다음 행동 |
    |---|---|
    | `no_api_key` | 환경변수를 채운다. 서버 문제가 아니다 |
    | `api_error` | Gemini 응답 자체가 실패했다. 잠시 뒤 다시 |
    | `unparsable` | 1회 재요청까지 하고도 JSON 이 아니었다 |
    | `unknown_field` | 모델이 스키마에 없는 칸을 냈다 |
    | `empty_body` | 나눌 본문이 없다. 모델을 부르지 않는다 |

    어느 것도 수집을 실패로 만들지 않는다. 본문은 `raw_jobs` 에 그대로 있고 나중에 다시
    돌릴 수 있다 (`.claude/tasks/todo/prd-llm-classify.md`).
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class ClassificationResult:
    """분류 한 건의 결과.

    `fields` 는 열한 칸 전부를 갖는다. 채우지 못한 칸은 빈 문자열이고, 본문에서 찾지 못해
    버린 칸도 빈 문자열이다 — 버린 칸의 이름은 `dropped` 에 있다.
    """

    fields: dict[str, str]
    usage: Usage
    attempts: int
    dropped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def filled(self) -> list[str]:
        """값이 들어간 칸 이름."""
        return [name for name in CLASSIFY_FIELDS if self.fields.get(name, "").strip()]


def build_client(settings: Settings | None = None) -> Any:
    """API 키는 환경변수에서만 온다. 소스에도 로그에도 남기지 않는다."""
    try:
        return build_gemini_client(settings)
    except LlmCallError as exc:
        raise ClassifyError(
            exc.reason, "GEMINI_API_KEY 가 비어 있다. 서버 문제가 아니라 분류만 막힌다"
        ) from exc


def build_prompt(body: str) -> tuple[str, list[str]]:
    """보낼 프롬프트와 남길 메모. 상한을 넘긴 본문은 자르고 그 사실을 적는다."""
    notes: list[str] = []
    text = body
    if len(text) > MAX_BODY_CHARS:
        notes.append(f"본문이 {len(text)}자라 앞 {MAX_BODY_CHARS}자만 보냈다")
        text = text[:MAX_BODY_CHARS]
    return _PROMPT.format(body=text), notes


async def classify_body(
    body: str,
    *,
    settings: Settings | None = None,
    client: Any | None = None,
) -> ClassificationResult:
    """본문 하나를 나눈다. 받은 값은 본문에 있는지 확인한 뒤에만 남는다."""
    if not body.strip():
        raise ClassifyError("empty_body", "본문이 비어 있어 나눌 것이 없다")

    resolved = settings or get_settings()
    resolved_client = client or build_client(resolved)
    model = resolved.gemini_model
    prompt, notes = build_prompt(body)

    last_error: ClassifySchemaError | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        text, usage = await _call(resolved_client, model, prompt, attempt)
        try:
            fields = parse_classification(text)
        except ClassifySchemaError as exc:
            logger.warning(
                "분류 응답 거절 model=%s attempt=%d reason=%s message=%s",
                model,
                attempt,
                exc.reason,
                exc,
            )
            if exc.reason != "unparsable":
                # 모양이 아니라 내용의 문제다. 다시 물어도 같은 답이 온다
                raise ClassifyError(exc.reason, str(exc)) from exc
            last_error = exc
            continue

        # 받은 값을 그 자리에서 본문에 돌려 본다. 못 찾은 칸은 버린다
        grounded = ground(fields, body)
        if grounded.dropped:
            logger.warning(
                "분류가 본문에 없는 값을 냈다 model=%s 버린 칸=%s",
                model,
                ", ".join(grounded.dropped),
            )
        return ClassificationResult(
            fields=grounded.fields,
            usage=usage,
            attempts=attempt,
            dropped=grounded.dropped,
            notes=[
                *notes,
                *(
                    [f"본문에서 찾지 못해 버린 칸: {', '.join(grounded.dropped)}"]
                    if grounded.dropped
                    else []
                ),
            ],
        )

    assert last_error is not None  # 루프는 최소 한 번 돈다
    raise ClassifyError(
        "unparsable", f"{MAX_ATTEMPTS}회 모두 스키마에 맞지 않았다: {last_error}"
    ) from last_error


async def _call(client: Any, model: str, prompt: str, attempt: int) -> tuple[str, Usage]:
    try:
        return await call_gemini(
            client,
            model,
            prompt,
            attempt,
            "본문 분류",
            response_schema=Classification,
            system_instruction=_SYSTEM_INSTRUCTION,
        )
    except LlmCallError as exc:
        raise ClassifyError(exc.reason, str(exc)) from exc
