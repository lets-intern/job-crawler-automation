"""셀렉터 JSON 스키마와 검증.

모델이 돌려준 것은 가설이지 결과가 아니다 (`.claude/rules/llm.md`). 이 파일이 그 가설을
DB 에 넣어도 되는 모양인지 판정한다.

판정은 통과 아니면 실패다. 스키마에 없는 필드명이 오면 무엇을 말하려던 것인지 추측해서 고치지
않는다 — 조용히 고친 셀렉터는 나중에 왜 안 맞는지 아무도 설명하지 못한다.

실패 사유는 셋 중 하나로 분류해서 운영자에게 그대로 보여준다.

| reason | 뜻 |
|---|---|
| `unparsable` | JSON 이 아니거나, 객체·문자열이 아닌 자리에 다른 타입이 왔다 |
| `unknown_field` | 스키마에 없는 필드명이 왔다 |
| `missing_field` | 필수 필드가 없거나 값이 비어 있다 |

`unparsable` 만 1회 재생성 대상이다. 나머지는 모양이 아니라 내용의 문제라 다시 물어도 같은
답이 온다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

# 값이 비어 있어도 실패로 보지 않는 상세 필드. 사이트에 그 항목 자체가 없을 수 있다.
OPTIONAL_DETAIL_FIELDS: frozenset[str] = frozenset({"requirements", "deadline", "department"})

# 아래 모델은 Gemini 의 response_schema 로 그대로 나간다. `extra="forbid"` 를 걸면
# `additionalProperties: false` 로 변환되는데 Gemini 가 그 필드를 모르고 400 을 낸다.
# 스키마에 없는 필드명을 거르는 일은 `validate_selectors()` 가 받은 뒤에 한다.


class ListSelectors(BaseModel):
    """목록 페이지. `item` 이 반복 단위고 나머지는 그 안에서 찾는다."""

    item: str
    title: str
    link: str
    date: str


class DetailSelectors(BaseModel):
    """상세 페이지. 사이트에 없는 항목은 빈 문자열로 온다."""

    title: str
    body: str
    requirements: str
    deadline: str
    department: str


class SelectorSet(BaseModel):
    """`crawlers.selectors_json` 에 그대로 들어가는 모양."""

    list: ListSelectors
    detail: DetailSelectors

    def to_json(self) -> str:
        return self.model_dump_json()


LIST_FIELDS: tuple[str, ...] = tuple(ListSelectors.model_fields)
DETAIL_FIELDS: tuple[str, ...] = tuple(DetailSelectors.model_fields)
SECTIONS: tuple[str, ...] = tuple(SelectorSet.model_fields)


class SelectorSchemaError(ValueError):
    """검증 실패. `reason` 은 위 표의 값 중 하나다."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def validate_selectors(data: Any) -> SelectorSet:
    """파싱된 응답을 검증한다. 통과하면 `SelectorSet`, 아니면 `SelectorSchemaError`."""
    if not isinstance(data, Mapping):
        raise SelectorSchemaError("unparsable", f"응답이 객체가 아니다: {type(data).__name__}")

    _reject_unknown(data, SECTIONS, "최상위")
    _require(data, SECTIONS, "최상위")

    sections: dict[str, dict[str, str]] = {}
    for section, fields in (("list", LIST_FIELDS), ("detail", DETAIL_FIELDS)):
        sections[section] = _validate_section(data[section], section, fields)

    return SelectorSet(
        list=ListSelectors(**sections["list"]),
        detail=DetailSelectors(**sections["detail"]),
    )


def parse_selectors(text: str) -> SelectorSet:
    """모델 응답 문자열을 파싱하고 검증한다."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SelectorSchemaError("unparsable", f"JSON 으로 읽을 수 없다: {exc}") from exc
    return validate_selectors(data)


def _validate_section(value: Any, section: str, fields: tuple[str, ...]) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise SelectorSchemaError(
            "unparsable", f"`{section}` 이 객체가 아니다: {type(value).__name__}"
        )

    _reject_unknown(value, fields, section)
    _require(value, fields, section)

    result: dict[str, str] = {}
    for name in fields:
        raw = value[name]
        if not isinstance(raw, str):
            raise SelectorSchemaError(
                "unparsable", f"`{section}.{name}` 이 문자열이 아니다: {type(raw).__name__}"
            )
        selector = raw.strip()
        if not selector and not (section == "detail" and name in OPTIONAL_DETAIL_FIELDS):
            raise SelectorSchemaError("missing_field", f"`{section}.{name}` 이 비어 있다")
        result[name] = selector
    return result


def _reject_unknown(data: Mapping[str, Any], allowed: tuple[str, ...], where: str) -> None:
    unknown = sorted(str(key) for key in data if key not in allowed)
    if unknown:
        raise SelectorSchemaError(
            "unknown_field", f"{where} 에 스키마에 없는 필드가 있다: {', '.join(unknown)}"
        )


def _require(data: Mapping[str, Any], required: tuple[str, ...], where: str) -> None:
    missing = [name for name in required if name not in data]
    if missing:
        raise SelectorSchemaError(
            "missing_field", f"{where} 에 필수 필드가 없다: {', '.join(missing)}"
        )
