"""JSON API 로 목록과 상세를 가져온다.

HTML 을 셀렉터로 읽는 자리(`app/crawler/parser.py`)와 하는 일이 같다. 다른 것은 입력이
문서가 아니라 JSON 이고, 어디를 읽을지 정하는 것이 CSS 셀렉터가 아니라 점 표기 경로라는
것뿐이다. 돌려주는 값은 같은 `ListParseResult` 와 `DetailParseResult` 라서, 러너와 그 뒤는
어느 경로로 왔는지 모른다.

요청은 공용 fetch 클라이언트의 `request()` 로 나간다. 이 모듈은 `httpx` 를 모른다
(`.claude/rules/crawling.md`).

## 실패는 셋으로 갈린다

| 무슨 일 | error_class | 고치는 법 |
|---|---|---|
| 타임아웃·5xx·연결 끊김 | `transport` | 재시도. 반복되면 사이트 상태 확인 |
| `items_path` 가 응답에 없거나 배열이 비었다 | `selector_miss` | 경로 재작성. 재시도 금지 |
| JSON 이 아니거나 배열이 아니거나 필드를 못 읽었다 | `parse` | 그 경로만 보정 |

**항목 0건은 실패다.** 200 이 오고 배열이 비어 있는 것은 "신규 공고 없음" 이 아니라 목록을
가져오지 못한 것이다. API 응답 모양이 바뀐 사이트와 공고가 없는 사이트를 같은 결과로 남기면
둘을 구분할 수 없다 (`CLAUDE.md`).

## 값은 손대지 않는다

LG 의 `detailContext` 처럼 HTML 조각이 그대로 들어 있는 필드가 있다. 여기서 텍스트로 펴지
않는다. 지저분한 값은 정규화 규칙이 다루는 문제이고, 수집 단계가 손대면 원본이 사라진다
(`CLAUDE.md`, `.claude/rules/data-safety.md`).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from app.crawler.fetcher import FetchPolicy
from app.crawler.parser import (
    REQUIRED_DETAIL_FIELDS,
    DetailParseResult,
    FieldFailure,
    FieldParseError,
    ListItem,
    ListParseResult,
    SelectorMissError,
)
from app.selector.api_schema import ID_PLACEHOLDER, ApiDetailConfig, ApiListConfig
from app.selector.schema import DETAIL_FIELDS

logger = logging.getLogger(__name__)

# 항목 하나가 남으려면 있어야 하는 것. 제목이 없으면 공고를 알아볼 수 없고, id 가 없으면
# 상세로 갈 수도 주소를 만들 수도 없다
REQUIRED_LIST_VALUES: tuple[str, ...] = ("title", "id")


class _Missing:
    """경로가 안 잡혔다는 표시. `None` 은 "값이 null 이었다" 라서 자리가 다르다."""


MISSING = _Missing()


async def fetch_list(client: FetchPolicy, config: ApiListConfig) -> ListParseResult:
    """목록 API 를 한 번 부르고 항목을 만든다."""
    payload = await _fetch_json(client, config.url, config.method, dict(config.body))
    return build_items(payload, config)


async def fetch_detail(
    client: FetchPolicy, config: ApiDetailConfig, item_id: str
) -> DetailParseResult:
    """공고 하나의 상세 API 를 부르고 필드를 만든다."""
    url = config.url.replace(ID_PLACEHOLDER, item_id)
    body = _with_id(dict(config.body), item_id)
    payload = await _fetch_json(client, url, config.method, body)
    return build_detail(payload, config)


def build_items(payload: Any, config: ApiListConfig) -> ListParseResult:
    """응답에서 항목을 뽑는다. 경로가 안 잡히거나 0건이면 `SelectorMissError` 다."""
    entries = _dig(payload, config.items_path)
    if isinstance(entries, _Missing):
        raise SelectorMissError(
            f"items_path `{config.items_path}` 가 응답에 없다. API 응답 모양이 바뀌었다"
        )
    if not isinstance(entries, list):
        # 경로는 잡혔는데 배열이 아니다. 경로 자체를 잘못 짚은 것이라 그 자리만 고치면 된다
        raise FieldParseError(
            f"items_path `{config.items_path}` 가 배열이 아니다: {type(entries).__name__}"
        )
    if not entries:
        raise SelectorMissError(
            f"items_path `{config.items_path}` 가 빈 배열이다. "
            "신규 0건인 정상 실행이 아니라 목록을 가져오지 못한 것이다"
        )

    items: list[ListItem] = []
    failures: list[FieldFailure] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            failures.append(
                FieldFailure(
                    index=index,
                    field="item",
                    message=f"항목이 객체가 아니다: {type(entry).__name__}",
                )
            )
            continue
        item, problems = _item(index, entry, config)
        if item is None:
            failures.extend(problems)
            continue
        items.append(item)

    if not items:
        unread = [name for name in REQUIRED_LIST_VALUES if any(f.field == name for f in failures)]
        raise FieldParseError(
            f"항목 {len(entries)}건을 잡았지만 어느 항목에서도 {', '.join(unread) or 'item'} 를 "
            f"읽지 못했다: {failures[0].message}"
        )
    return ListParseResult(matched=len(entries), items=items, failures=failures)


def build_detail(payload: Any, config: ApiDetailConfig) -> DetailParseResult:
    """응답에서 상세 필드를 뽑는다. 필수 필드를 못 읽으면 `FieldParseError` 다."""
    fields: dict[str, str] = {}
    missing: list[str] = []
    for name in DETAIL_FIELDS:
        path = config.fields.get(name)
        if not path:
            # 설정에 없는 필드다. 사이트에 그 항목이 없다는 뜻이지 실패가 아니다
            fields[name] = ""
            continue
        value = _dig(payload, path)
        fields[name] = _text(value)
        if not fields[name]:
            missing.append(name)

    unreadable = [name for name in REQUIRED_DETAIL_FIELDS if not fields[name]]
    if unreadable:
        raise FieldParseError(
            f"상세 응답에서 필수 필드를 읽지 못했다: {', '.join(unreadable)}. "
            f"경로를 확인한다: {', '.join(config.fields.get(name, '') for name in unreadable)}"
        )
    return DetailParseResult(fields=fields, missing=missing)


def _item(
    index: int, entry: Mapping[str, Any], config: ApiListConfig
) -> tuple[ListItem | None, list[FieldFailure]]:
    """항목 하나. 제목과 id 가 있어야 남는다."""
    values = {name: _text(_dig(entry, path)) for name, path in config.fields.items()}
    item_id = _text(_dig(entry, config.id_field))

    problems: list[FieldFailure] = []
    if not values.get("title"):
        problems.append(
            FieldFailure(
                index=index,
                field="title",
                message=f"`{config.fields.get('title', '')}` 가 항목 안에서 값을 찾지 못했다",
            )
        )
    if not item_id:
        problems.append(
            FieldFailure(
                index=index,
                field="id",
                message=f"id_field `{config.id_field}` 가 항목 안에서 값을 찾지 못했다",
            )
        )
    if problems:
        return None, problems

    return (
        ListItem(
            index=index,
            title=values.get("title", ""),
            link=config.link_template.replace(ID_PLACEHOLDER, item_id),
            date=values.get("date", ""),
            company=values.get("company", ""),
            detail_key=item_id,
        ),
        [],
    )


async def _fetch_json(client: FetchPolicy, url: str, method: str, body: dict[str, Any]) -> Any:
    """공용 클라이언트로 부르고 JSON 으로 읽는다. JSON 이 아니면 파싱 실패다."""
    result = await client.request(url, method=method, json_body=body if method == "POST" else None)
    try:
        payload = json.loads(result.text)
    except json.JSONDecodeError as exc:
        # 전송은 됐다. 200 인데 JSON 이 아니면 endpoint 를 잘못 짚었거나 사이트가 막은 것이고,
        # 어느 쪽이든 재시도로는 풀리지 않는다
        raise FieldParseError(
            f"응답이 JSON 이 아니다({exc}): {url} status={result.status_code}"
        ) from exc
    logger.info("api 응답 url=%s method=%s status=%s", url, method, result.status_code)
    return payload


def _with_id(value: Any, item_id: str) -> Any:
    """본문의 `{id}` 자리를 채운다. 값 전체가 자리표시자면 타입도 원래대로 돌린다.

    `{"jobNoticeId": "{id}"}` 는 `{"jobNoticeId": 1002029}` 로 나간다. LG 는 숫자를 받는데
    문자열로 보내면 응답이 비어 돌아온다. 문자열 안에 섞여 있는 경우는 문자열 그대로 채운다.
    """
    if isinstance(value, str):
        if value == ID_PLACEHOLDER:
            return int(item_id) if item_id.isdigit() else item_id
        return value.replace(ID_PLACEHOLDER, item_id)
    if isinstance(value, Mapping):
        return {key: _with_id(inner, item_id) for key, inner in value.items()}
    if isinstance(value, list):
        return [_with_id(inner, item_id) for inner in value]
    return value


def _dig(payload: Any, path: str) -> Any:
    """점 표기 경로로 값을 찾는다. 못 찾으면 `MISSING` 이다.

    숫자 조각은 배열의 자리다 — `recList.0.detailContext` 는 `recList` 의 첫 항목을 본다.
    키에 점이 들어간 응답은 아직 만난 적이 없어 다루지 않는다.
    """
    current = payload
    for part in path.split("."):
        if isinstance(current, Mapping):
            if part not in current:
                return MISSING
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return MISSING
            current = current[index]
        else:
            return MISSING
    return current


def _text(value: Any) -> str:
    """값을 문자열로 만든다. 정제는 하지 않는다 — HTML 조각도 그대로 남는다."""
    if isinstance(value, _Missing) or value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    # 객체나 배열이 온 자리다. 경로가 한 단계 얕은 것이므로 눈에 보이게 남긴다
    return json.dumps(value, ensure_ascii=False)
