"""분류 응답의 스키마와 검증.

모델이 돌려준 것은 가설이지 결과가 아니다 (`.claude/rules/llm.md`). 이 파일은 받은 것이
읽어도 되는 모양인지만 판정하고, 그 값이 본문에 근거가 있는지는 `app/classify/grounding.py`
가 본다.

칸은 `normalized_jobs` 에 이미 있는 열한 개다. 새로 만들지 않는다
(`migrations/0011_split_body_columns.sql`).

## 칸이 두 가지다

**뽑는 칸**은 본문에 있는 글자를 그대로 가져온다. 옮긴 값은 본문에서 그대로 찾을 수 있어야
하고, 없으면 빈 칸이다.

**판정하는 칸**은 본문을 읽고 정해진 값 중에서 고른다. `백엔드 개발자 채용` 이라는 제목에
"직군: 개발" 이라고 적혀 있지 않다 — 글자 일치를 요구하면 이 칸은 영원히 빈다. 매핑 방식의
채움률이 직군 53%, 고용형태 26%, 경력 45% 였던 이유가 그것이다.

판정 칸은 **반드시 닫힌 목록**이다. 목록을 정하지 않으면 같은 일이 사이트마다 다른 이름으로
쌓인다 — 운영 DB 640건에 `Permanent` 71건과 `정규직` 7건과 `정규` 3건이 따로 있고,
`Experienced` 77건과 `경력` 100건이 따로 있다. 그러면 소비 측이 그 칸으로 거를 수 없다.

목록은 프롬프트로 부탁하지 않고 **응답 스키마의 enum 으로 강제한다.** 부탁은 대개 지켜지고,
대개는 640건에서 스무 건쯤 어긋난다는 뜻이다.

판정 칸에는 근거 문장이 따라온다(`*_evidence`). 그 문장이 본문에 없으면 판정을 버린다 —
읽고 고른 것인지 지어낸 것인지 가를 방법이 그것뿐이다.

| reason | 뜻 |
|---|---|
| `unparsable` | JSON 이 아니거나, 객체·문자열이 아닌 자리에 다른 타입이 왔다 |
| `unknown_field` | 스키마에 없는 칸 이름이 왔다 |

`unparsable` 만 1회 재요청 대상이다. 스키마에 없는 칸을 지어낸 것은 모양이 아니라 내용의
문제라 다시 물어도 같은 답이 온다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal, get_args

from pydantic import BaseModel

# 아래 모델은 Gemini 의 response_schema 로 그대로 나간다. `extra="forbid"` 를 걸면
# `additionalProperties: false` 로 변환되는데 Gemini 가 그 필드를 모르고 400 을 낸다.
# 스키마에 없는 칸 이름을 거르는 일은 `validate_classification()` 이 받은 뒤에 한다.


class Classification(BaseModel):
    """본문을 나눈 열한 칸과, 판정 칸 셋의 근거 문장.

    뽑는 칸은 자유 문자열이고 본문에 없으면 빈 문자열이다. 판정 칸은 `Literal` 이라 목록에
    없는 값이 애초에 응답에 담기지 못한다. 빈 문자열이 목록에 들어 있는 것은 "본문만으로는
    고를 수 없다" 를 답할 자리가 있어야 하기 때문이다 — 자리가 없으면 모델은 아무거나 고른다.
    """

    # 판정하는 칸. 목록은 운영 DB 640건의 실제 값에서 뽑았다 (아래 주석)
    job_category: Literal[
        "",
        "개발·IT",
        "연구개발",
        "생산·제조",
        "품질·안전",
        "건설·플랜트",
        "영업",
        "마케팅",
        "기획·전략",
        "경영지원",
        "재무·회계",
        "법무",
        "구매·물류",
        "디자인",
        "고객서비스",
        "기타",
    ] = ""
    job_category_evidence: str = ""

    employment_type: Literal["", "정규직", "계약직", "인턴", "기타"] = ""
    employment_type_evidence: str = ""

    career_level: Literal["", "신입", "경력", "무관"] = ""
    career_level_evidence: str = ""

    # 뽑는 칸. 본문에 있는 글자를 그대로 옮긴다
    work_location: str = ""
    headcount: str = ""
    duties: str = ""
    preferred: str = ""
    hiring_process: str = ""
    requirements: str = ""
    department: str = ""
    etc_info: str = ""


# 본문을 읽고 정해진 값 중에서 고르는 칸
JUDGE_FIELDS: tuple[str, ...] = ("job_category", "employment_type", "career_level")

# 판정 칸마다 따라오는 근거 문장. 컬럼이 아니라 검증과 보고를 위한 값이다
EVIDENCE_FIELDS: tuple[str, ...] = tuple(f"{name}_evidence" for name in JUDGE_FIELDS)

# 본문에 있는 글자를 그대로 가져오는 칸
EXTRACT_FIELDS: tuple[str, ...] = (
    "work_location",
    "headcount",
    "duties",
    "preferred",
    "hiring_process",
    "requirements",
    "department",
    "etc_info",
)

# 분류가 채우는 칸. `normalized_jobs` 의 같은 이름 컬럼으로 간다
CLASSIFY_FIELDS: tuple[str, ...] = (*JUDGE_FIELDS, *EXTRACT_FIELDS)

# 응답에 올 수 있는 이름 전부
RESPONSE_FIELDS: tuple[str, ...] = tuple(Classification.model_fields)


def _choices(name: str) -> tuple[str, ...]:
    annotation = Classification.model_fields[name].annotation
    return tuple(value for value in get_args(annotation) if value)


# 판정 칸이 고를 수 있는 값. 모델에 보내는 목록과 받은 뒤 거르는 목록이 같아야 해서 스키마
# 하나에서 뽑는다 — 두 벌을 두면 목록을 넓힐 때 한쪽만 넓어진다
JUDGE_CHOICES: dict[str, tuple[str, ...]] = {name: _choices(name) for name in JUDGE_FIELDS}


class ClassifySchemaError(ValueError):
    """검증 실패. `reason` 은 위 표의 값 중 하나다."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def validate_classification(data: Any) -> dict[str, str]:
    """파싱된 응답을 검증해 이름별 문자열로 돌려준다. 없는 키는 빈 문자열이다.

    스키마에 없는 칸 이름이 오면 무엇을 말하려던 것인지 추측해서 고치지 않는다. 조용히 고친
    값은 나중에 왜 그 칸에 그 값이 들어갔는지 아무도 설명하지 못한다.

    판정 칸의 값이 목록 밖이면 여기서 버리지 않고 그대로 넘긴다. 무엇을 왜 버렸는지 한자리에서
    세려고 판정은 `app/classify/grounding.py` 가 한다.
    """
    if not isinstance(data, Mapping):
        raise ClassifySchemaError("unparsable", f"응답이 객체가 아니다: {type(data).__name__}")

    unknown = sorted(str(key) for key in data if key not in RESPONSE_FIELDS)
    if unknown:
        raise ClassifySchemaError("unknown_field", f"스키마에 없는 칸이 있다: {', '.join(unknown)}")

    result: dict[str, str] = {}
    for name in RESPONSE_FIELDS:
        raw = data.get(name, "")
        if raw is None:
            raw = ""
        if not isinstance(raw, str):
            raise ClassifySchemaError(
                "unparsable", f"`{name}` 이 문자열이 아니다: {type(raw).__name__}"
            )
        result[name] = raw.strip()
    return result


def parse_classification(text: str) -> dict[str, str]:
    """모델 응답 문자열을 파싱하고 검증한다."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ClassifySchemaError("unparsable", f"JSON 으로 읽을 수 없다: {exc}") from exc
    return validate_classification(data)
