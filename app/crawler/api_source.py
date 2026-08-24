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
import re
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag

from app.crawler.fetcher import FetchPolicy, FetchResult
from app.crawler.parser import (
    REQUIRED_DETAIL_FIELDS,
    DetailParseResult,
    FieldFailure,
    FieldParseError,
    ListItem,
    ListParseResult,
    SelectorMissError,
    field_text,
    select_nodes,
)
from app.selector.api_schema import (
    DIGITS_FILTER,
    FORM_BODY,
    ID_ATTRIBUTE_MARK,
    ID_PLACEHOLDER,
    ApiDetailConfig,
    ApiListConfig,
)
from app.selector.schema import DETAIL_FIELDS

logger = logging.getLogger(__name__)

# `id_field` 에 쓰는 `{키}` 자리. 항목 안의 경로 이름만 받는다
ENTRY_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_.]*)\}")

# 항목 하나가 남으려면 있어야 하는 것. 제목이 없으면 공고를 알아볼 수 없고, id 가 없으면
# 상세로 갈 수도 주소를 만들 수도 없다
REQUIRED_LIST_VALUES: tuple[str, ...] = ("title", "id")


class _Missing:
    """경로가 안 잡혔다는 표시. `None` 은 "값이 null 이었다" 라서 자리가 다르다."""


MISSING = _Missing()


async def fetch_list(client: FetchPolicy, config: ApiListConfig) -> ListParseResult:
    """목록 API 를 부르고 항목을 만든다. 쪽 넘김 설정이 있으면 끝까지 넘긴다."""
    if config.pagination is None:
        result = await _send(client, config.url, config.method, dict(config.body), config)
        return _read_page(result, config)
    return await _fetch_pages(client, config)


async def _fetch_pages(client: FetchPolicy, config: ApiListConfig) -> ListParseResult:
    """쪽을 넘겨 가며 전부 모은다. 한화 68건(20씩 4쪽)과 삼성 16건(2쪽)이 이 경로다.

    쪽 사이에도 호스트 딜레이가 그대로 걸린다. 요청이 전부 공용 fetch 클라이언트를 지나기
    때문이고, 그래서 여기서 따로 기다리지 않는다 (`.claude/rules/crawling.md`).

    멈추는 조건은 셋이다 — 사이트가 다음 쪽이 없다고 말했거나, 항목이 0건인 쪽이 나왔거나,
    `max_pages` 에 닿았거나. 마지막 것이 없으면 끝나지 않는 `hasNext` 하나로 사이트를 영원히
    때리게 된다.

    첫 쪽이 0건인 것은 끝이 아니라 실패다. 목록을 못 읽은 실행과 공고가 없는 사이트를 같은
    결과로 남기지 않는다.
    """
    pages = config.pagination
    assert pages is not None  # 부르는 쪽이 확인했다

    matched = 0
    items: list[ListItem] = []
    failures: list[FieldFailure] = []
    number = pages.start

    for turn in range(pages.max_pages):
        body = dict(config.body)
        body[pages.param] = number
        result = await _send(client, config.url, config.method, body, config)
        try:
            page = _read_page(result, config)
        except SelectorMissError:
            if turn == 0:
                # 첫 쪽부터 0건이다. 쪽 넘김의 끝이 아니라 목록을 가져오지 못한 것이다
                raise
            logger.info("목록 %s쪽이 0건이라 여기서 멈춘다 url=%s", number, config.url)
            break

        for miss in page.failures:
            failures.append(replace(miss, index=miss.index + matched))
        for item in page.items:
            items.append(replace(item, index=len(items)))
        matched += page.matched

        if not _has_more(result, config, page_count=turn + 1):
            break
        number += 1
    else:
        logger.warning(
            "목록 쪽 넘김이 상한 %s에 닿아 멈춘다 url=%s. 그 뒤 공고는 이 실행에 없다",
            pages.max_pages,
            config.url,
        )

    return ListParseResult(matched=matched, items=items, failures=failures)


def _read_page(result: FetchResult, config: ApiListConfig) -> ListParseResult:
    """응답 하나를 항목으로 읽는다. JSON 인지 HTML 조각인지는 설정이 정한다."""
    if config.is_html:
        return build_html_items(result.text, config)
    return build_items(_as_json(result), config)


def _has_more(result: FetchResult, config: ApiListConfig, *, page_count: int) -> bool:
    """다음 쪽이 있는가. 판정하는 법은 사이트마다 다르다."""
    pages = config.pagination
    assert pages is not None

    if pages.has_next:
        # 한화는 `data.hasNext` 가 마지막 쪽에서 false 가 된다
        return _dig(_as_json(result), pages.has_next) is True
    if pages.total_pages_selector:
        # 삼성은 총 쪽 수를 응답 안에 넣어 준다
        total = _total_pages(result.text, pages.total_pages_selector, pages.total_pages_attribute)
        return total is not None and page_count < total
    # 판정할 것이 없으면 다음 쪽을 열어 보고 0건이면 멈춘다
    return True


def _total_pages(html: str, selector: str, attribute: str) -> int | None:
    """총 쪽 수. 못 읽으면 None 이고, 그때는 0건인 쪽이 나올 때까지 넘긴다."""
    soup = BeautifulSoup(html, "html.parser")
    nodes = select_nodes(soup, selector, "list.pagination.total_pages_selector")
    if not nodes:
        return None
    raw = nodes[0].get(attribute)
    value = " ".join(raw) if isinstance(raw, list) else str(raw or "")
    value = value.strip()
    return int(value) if value.isdigit() else None


async def fetch_detail(
    client: FetchPolicy, config: ApiDetailConfig, item_id: str
) -> DetailParseResult:
    """공고 하나의 상세 API 를 부르고 필드를 만든다."""
    url = config.url.replace(ID_PLACEHOLDER, item_id)
    body = _with_id(dict(config.body), item_id)
    result = await _send(client, url, config.method, body, config)
    return build_detail(_as_json(result), config)


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


def build_html_items(html: str, config: ApiListConfig) -> ListParseResult:
    """HTML 조각으로 오는 목록에서 항목을 뽑는다.

    삼성 목록이 이 경로다. 요청은 API 처럼 POST 로 물어보는데 응답이 JSON 이 아니라 HTML 조각
    이라, 어디를 읽을지는 점 표기 경로가 아니라 CSS 셀렉터가 정한다.

    | 설정 | HTML 모드에서의 뜻 |
    |---|---|
    | `items_path` | 항목 하나를 잡는 셀렉터 |
    | `fields` | 항목 안에서 값을 잡는 셀렉터 |
    | `id_field` | `<셀렉터>@<속성>`. 셀렉터를 비우면 항목 노드 자신의 속성이다 |

    판정은 JSON 쪽과 같다. 항목 0건은 실패이고, 제목과 id 가 없는 항목은 남기지 않는다.
    """
    soup = BeautifulSoup(html, "html.parser")
    nodes = select_nodes(soup, config.items_path, "list.items_path")
    if not nodes:
        raise SelectorMissError(
            f"items_path `{config.items_path}` 가 0개 매칭됐다. 목록 조각의 구조가 바뀌었다"
        )

    items: list[ListItem] = []
    failures: list[FieldFailure] = []
    for index, node in enumerate(nodes):
        values = {
            name: field_text(node, selector, f"list.{name}[{index}]")
            for name, selector in config.fields.items()
        }
        item_id = _html_id(node, config.id_field, index)

        problems: list[FieldFailure] = []
        if not values.get("title"):
            problems.append(
                FieldFailure(
                    index=index,
                    field="title",
                    message=f"`{config.fields.get('title', '')}` 이 항목 안에서 값을 찾지 못했다",
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
            failures.extend(problems)
            continue

        items.append(
            ListItem(
                index=index,
                title=values.get("title", ""),
                link=config.link_template.replace(ID_PLACEHOLDER, item_id),
                date=values.get("date", ""),
                company=values.get("company", ""),
                detail_key=item_id,
            )
        )

    if not items:
        unread = [name for name in REQUIRED_LIST_VALUES if any(f.field == name for f in failures)]
        raise FieldParseError(
            f"항목 {len(nodes)}건을 잡았지만 어느 항목에서도 {', '.join(unread) or 'item'} 를 "
            f"읽지 못했다: {failures[0].message}"
        )
    return ListParseResult(matched=len(nodes), items=items, failures=failures)


def _html_id(node: Tag, spec: str, index: int) -> str:
    """`<셀렉터>@<속성>` 표기로 항목 id 를 읽는다.

    `|digits` 를 붙이면 숫자만 남긴다. 삼성 공고 번호가 `data-value="22,878"` 처럼 천 단위
    쉼표가 찍힌 채로 오는데, 그대로 상세 주소에 넣으면 `%2C` 로 인코딩돼 열리지 않는다.
    **숫자 표기에 기대는 자리다** — 사이트가 표기를 바꾸면 여기가 먼저 깨진다
    (`.claude/site-recipes/www-samsungcareers-com.md`).
    """
    wanted, _, _ = spec.partition(DIGITS_FILTER)
    selector, mark, attribute = wanted.partition(ID_ATTRIBUTE_MARK)
    if not mark or not attribute.strip():
        raise FieldParseError(f"HTML 목록의 id_field 는 `<셀렉터>@<속성>` 이어야 한다: {spec}")

    target = node
    if selector.strip():
        found = select_nodes(node, selector.strip(), f"list.id_field[{index}]")
        if not found:
            return ""
        target = found[0]

    raw = target.get(attribute.strip())
    value = " ".join(raw) if isinstance(raw, list) else str(raw or "")
    value = value.strip()
    if spec.endswith(DIGITS_FILTER):
        value = "".join(char for char in value if char.isdigit())
    return value


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
    item_id = _entry_id(entry, config.id_field)

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


def _entry_id(entry: Mapping[str, Any], spec: str) -> str:
    """항목의 id. 키 하나이거나, `{키}` 자리를 항목 값으로 채운 템플릿이다.

    현대 상세는 `recuYy`·`recuType`·`recuCls` 세 값이 다 있어야 열린다. 한 값으로는 공고를
    지목할 수 없는 사이트라, id 자체가 여러 값을 이어 붙인 것이 된다.

        "id_field": "recuYy={recuYy}&recuType={recuType}&recuCls={recuCls}"

    한 자리라도 비면 빈 값이다. **반쯤 채워진 주소를 만들지 않는다** — 그것으로 요청하면 엉뚱한
    공고를 가져오거나 조용히 400 이 된다.
    """
    names = ENTRY_PLACEHOLDER.findall(spec)
    if not names:
        return _text(_dig(entry, spec))

    values: dict[str, str] = {}
    for name in names:
        value = _text(_dig(entry, name)).strip()
        if not value:
            return ""
        values[name] = value
    return ENTRY_PLACEHOLDER.sub(lambda match: values[match.group(1)], spec)


async def _send(
    client: FetchPolicy,
    url: str,
    method: str,
    body: dict[str, Any],
    config: ApiListConfig | ApiDetailConfig,
) -> FetchResult:
    """공용 클라이언트로 한 번 부른다. 본문 형식과 헤더는 설정이 정한다.

    GET 에 본문을 싣는 API 는 아직 만난 적이 없어 POST 일 때만 본문을 보낸다. 폼으로 보낼지는
    `body_format` 이 정한다 — 삼성은 폼이 아니면 500 을, 파라미터가 하나라도 빠지면
    `{"code":500}` 을 준다.
    """
    payload = body if method == "POST" else None
    as_form = getattr(config, "body_format", "") == FORM_BODY
    result = await client.request(
        url,
        method=method,
        json_body=None if as_form else payload,
        form_body=payload if as_form else None,
        headers=config.headers or None,
    )
    logger.info("api 응답 url=%s method=%s status=%s", url, method, result.status_code)
    return result


def _as_json(result: FetchResult) -> Any:
    """응답을 JSON 으로 읽는다. JSON 이 아니면 파싱 실패다."""
    try:
        return json.loads(result.text)
    except json.JSONDecodeError as exc:
        # 전송은 됐다. 200 인데 JSON 이 아니면 endpoint 를 잘못 짚었거나 사이트가 막은 것이고,
        # 어느 쪽이든 재시도로는 풀리지 않는다
        raise FieldParseError(
            f"응답이 JSON 이 아니다({exc}): {result.url} status={result.status_code}"
        ) from exc


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
