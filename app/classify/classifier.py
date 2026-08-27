"""본문 하나를 열한 칸으로 나눈다.

수집은 어느 사이트나 확실히 주는 여섯 칸만 한다. 나머지를 나누는 것은 본문을 읽는 이쪽 일이다
(`.claude/tasks/memos/보류/llm-classify/prd-llm-classify.md`).

## 칸이 두 가지다

**뽑는 칸** 여덟은 본문 글자를 그대로 옮긴다. 옮긴 값은 본문에서 그대로 찾을 수 있어야 한다.

**판정하는 칸** 셋(직군·고용형태·경력 구분)은 본문을 읽고 닫힌 목록에서 고른다. 목록은
응답 스키마의 enum 으로 강제하고, 고른 값에는 근거 문장이 따라온다. 그 문장이 본문에 없으면
판정을 버린다 — 읽고 고른 것인지 지어낸 것인지 가를 방법이 그것뿐이다.

어느 칸이 어느 쪽인지와 목록이 왜 그 목록인지는 `app/classify/schema.py` 에 있다.

## 지키는 것

**근거가 없는 것은 빈 칸이다.** 모델이 그럴듯하게 채우면 소비 측이 그것을 사실로 노출한다.
받은 값은 `app/classify/grounding.py` 가 그 자리에서 본문에 돌려 보고, 근거를 못 찾은 칸은
버리고 `dropped` 에 이름을 남긴다 (`.claude/rules/llm.md`).

**보내는 것은 본문뿐이고 상한이 있다.** 원본 HTML 도 페이지도 보내지 않는다. 본문이 상한을
넘으면 잘라 보내고 그 사실을 `notes` 에 남긴다. 자른 것으로 무엇을 놓쳤는지는 응답을 보는
사람이 알아야 한다.

**깨진 응답만 1회 다시 묻는다.** 스키마에 없는 칸을 지어낸 응답은 다시 물어도 같은 답이 온다.

호출 자체와 비용 기록은 `app/llm/gemini.py` 가 한다. 셀렉터 생성과 같은 경로다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.classify.grounding import ground
from app.classify.schema import (
    CLASSIFY_FIELDS,
    JUDGE_CHOICES,
    UNDECIDED,
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
    "뽑는 칸에는 본문에 있는 글자만 그대로 옮기고, 판정하는 칸은 본문을 읽고 주어진 목록에서 "
    "고른 뒤 그렇게 고른 근거 문장을 본문에서 그대로 옮겨 적는다. "
    "요약하지 않고, 다듬지 않고, 없는 것을 지어내지 않는다."
)

_PROMPT = """아래는 채용공고 본문이다. 이것을 정해진 칸으로 나눈다.

# 뽑는 칸 — 본문에 있는 글자를 그대로 옮긴다

- duties: 주요 업무·담당 업무
- requirements: 자격요건·지원자격
- preferred: 우대사항
- hiring_process: 전형 절차
- work_location: 근무지
- headcount: 모집 인원
- department: 조직·부서
- etc_info: 위 어디에도 맞지 않는 나머지

규칙:
- **본문에 있는 글자를 그대로 옮긴다.** 말을 바꾸거나 요약하거나 정리하지 않는다. 옮긴 값은
  본문에서 그대로 찾을 수 있어야 한다.
- **본문에 없는 칸은 빈 문자열로 둔다.** 짐작해서 채우지 않는다.
- 여러 줄이면 본문의 줄 그대로 줄바꿈으로 잇는다. 한 칸에 들어갈 내용이 본문 여러 곳에
  흩어져 있으면 그 조각들을 줄바꿈으로 잇되, 없는 연결 문장을 지어내 붙이지 않는다.
- 어느 칸에도 맞지 않는 내용만 etc_info 에 모은다. 본문 전체를 etc_info 에 넣지 않는다.

# 판정하는 칸 — 본문을 읽고 목록에서 고른다

- job_category: 직군. {job_category}
- employment_type: 고용형태. {employment_type}
- career_level: 경력 구분. {career_level}

규칙:
- **이 셋은 글자가 본문에 그대로 없어도 된다.** 본문을 읽고 판단해서 고른다. `백엔드 개발자를
  찾습니다` 이면 job_category 는 개발·IT 다. `5년 이상 경험` 이면 career_level 은 경력이다.
- **반드시 위 목록에 있는 값만 쓴다.** 목록에 없는 값을 새로 만들지 않는다. 어디에도 맞지
  않으면 목록의 기타를, 본문만으로는 판단할 수 없으면 판단불가 를 쓴다.
- 고른 칸마다 `job_category_evidence` 처럼 `_evidence` 가 붙은 자리에 **그렇게 판단한
  근거가 되는 본문 문장을 그대로 옮겨 적는다.** 한 문장이면 된다. 본문에 없는 문장을 적지
  않는다. 근거를 적을 수 없으면 그 칸을 판단불가 로 둔다.
- 회사명·공고 제목·모집 시작일·마감일은 어느 칸에도 넣지 않는다. 그 넷은 따로 수집한다.

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
    돌릴 수 있다 (`.claude/tasks/memos/보류/llm-classify/prd-llm-classify.md`).
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class ClassificationResult:
    """분류 한 건의 결과.

    `fields` 는 열한 칸 전부를 갖는다. 채우지 못한 칸은 빈 문자열이고, 근거를 찾지 못해 버린
    칸도 빈 문자열이다 — 버린 칸의 이름은 `dropped` 에, 이유는 `reasons` 에 있다.
    """

    fields: dict[str, str]
    usage: Usage
    attempts: int
    # 살아남은 판정 칸의 근거 문장. 사람이 그 판정을 읽고 검사할 수 있는 유일한 자리다
    evidence: dict[str, str] = field(default_factory=dict)
    dropped: list[str] = field(default_factory=list)
    # 버린 칸마다 왜 버렸는지. 고칠 자리가 이유마다 다르다
    reasons: dict[str, str] = field(default_factory=dict)
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
    """보낼 프롬프트와 남길 메모. 상한을 넘긴 본문은 자르고 그 사실을 적는다.

    판정 칸의 목록을 프롬프트에도 적는다. 스키마의 enum 이 이미 강제하지만, 무엇 중에서
    고르는지 모르는 채로 고르면 목록에서 가장 가까운 값이 아니라 첫 값이 나온다. 목록의
    출처는 스키마 하나다 — 여기에 손으로 적으면 두 목록이 갈린다.
    """
    notes: list[str] = []
    text = body
    if len(text) > MAX_BODY_CHARS:
        notes.append(f"본문이 {len(text)}자라 앞 {MAX_BODY_CHARS}자만 보냈다")
        text = text[:MAX_BODY_CHARS]
    choices = {name: " / ".join((*values, UNDECIDED)) for name, values in JUDGE_CHOICES.items()}
    return _PROMPT.format(body=text, **choices), notes


async def classify_body(
    body: str,
    *,
    settings: Settings | None = None,
    client: Any | None = None,
    on_call: Callable[[Usage], None] | None = None,
) -> ClassificationResult:
    """본문 하나를 나눈다. 받은 값은 본문에 있는지 확인한 뒤에만 남는다.

    `on_call` 은 모델을 부를 때마다 그 호출의 비용으로 불린다. 깨진 응답으로 한 번 더 물으면
    두 번 불린다 — 부르는 쪽이 그것을 `llm_calls` 에 그대로 남겨야 토큰 합이 실제와 맞는다
    (`app/llm/log.py`).
    """
    if not body.strip():
        raise ClassifyError("empty_body", "본문이 비어 있어 나눌 것이 없다")

    resolved = settings or get_settings()
    resolved_client = client or build_client(resolved)
    model = resolved.gemini_model
    prompt, notes = build_prompt(body)

    last_error: ClassifySchemaError | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        text, usage = await _call(resolved_client, model, prompt, attempt)
        if on_call is not None:
            on_call(usage)
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
                "분류가 근거 없는 값을 냈다 model=%s 버린 칸=%s",
                model,
                ", ".join(f"{name}({grounded.reasons[name]})" for name in grounded.dropped),
            )
        return ClassificationResult(
            fields=grounded.fields,
            usage=usage,
            attempts=attempt,
            evidence=grounded.evidence,
            dropped=grounded.dropped,
            reasons=grounded.reasons,
            notes=[
                *notes,
                *(
                    [
                        "근거가 없어 버린 칸: "
                        + ", ".join(
                            f"{name}({grounded.reasons[name]})" for name in grounded.dropped
                        )
                    ]
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
