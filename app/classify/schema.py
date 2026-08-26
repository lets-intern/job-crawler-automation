"""분류 응답의 스키마와 검증.

모델이 돌려준 것은 가설이지 결과가 아니다 (`.claude/rules/llm.md`). 이 파일은 받은 것이
읽어도 되는 모양인지만 판정하고, 그 값이 본문에 실제로 있는지는 `app/classify/grounding.py`
가 본다. 둘을 갈라 둔 이유는 실패의 뜻이 다르기 때문이다 — 모양이 깨진 것은 다시 물어볼
일이고, 없는 값을 지어낸 것은 그 항목을 버릴 일이다.

칸은 `normalized_jobs` 에 이미 있는 열한 개다. 새로 만들지 않는다
(`migrations/0011_split_body_columns.sql`). 어디에도 안 맞는 것은 `etc_info` 로 모은다.

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
from typing import Any

from pydantic import BaseModel

# 아래 모델은 Gemini 의 response_schema 로 그대로 나간다. `extra="forbid"` 를 걸면
# `additionalProperties: false` 로 변환되는데 Gemini 가 그 필드를 모르고 400 을 낸다.
# 스키마에 없는 칸 이름을 거르는 일은 `validate_classification()` 이 받은 뒤에 한다.


class Classification(BaseModel):
    """본문을 나눈 열한 칸. 본문에 없는 것은 빈 문자열이다.

    전부 기본값이 빈 문자열인 것은 "모델이 그 칸을 채우지 않는 것" 이 정상이기 때문이다.
    없는 값을 지어내는 것보다 빈 칸이 낫다 — 소비 측은 빈 칸을 그리지 않으면 되지만, 틀린
    값은 사실로 노출한다 (`.claude/docs/api-contract.md`).
    """

    job_category: str = ""
    work_location: str = ""
    career_level: str = ""
    employment_type: str = ""
    headcount: str = ""
    duties: str = ""
    preferred: str = ""
    hiring_process: str = ""
    requirements: str = ""
    department: str = ""
    etc_info: str = ""


# 분류가 채우는 칸. `normalized_jobs` 의 같은 이름 컬럼으로 간다
CLASSIFY_FIELDS: tuple[str, ...] = tuple(Classification.model_fields)


class ClassifySchemaError(ValueError):
    """검증 실패. `reason` 은 위 표의 값 중 하나다."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def validate_classification(data: Any) -> dict[str, str]:
    """파싱된 응답을 검증해 칸별 문자열로 돌려준다. 없는 키는 빈 문자열이다.

    스키마에 없는 칸 이름이 오면 무엇을 말하려던 것인지 추측해서 고치지 않는다. 조용히 고친
    값은 나중에 왜 그 칸에 그 값이 들어갔는지 아무도 설명하지 못한다.
    """
    if not isinstance(data, Mapping):
        raise ClassifySchemaError("unparsable", f"응답이 객체가 아니다: {type(data).__name__}")

    unknown = sorted(str(key) for key in data if key not in CLASSIFY_FIELDS)
    if unknown:
        raise ClassifySchemaError("unknown_field", f"스키마에 없는 칸이 있다: {', '.join(unknown)}")

    result: dict[str, str] = {}
    for name in CLASSIFY_FIELDS:
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
