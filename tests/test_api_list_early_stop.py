"""쪽을 넘기는 목록에서 아는 공고만 있는 쪽을 만나면 멈춘다.

목록이 새것부터 오므로, 한 쪽이 전부 아는 공고면 그 뒤는 더 옛것이다. 한화가 20씩 4쪽이고
평소 실행은 신규 0~1건이라, 멈추지 않으면 매번 넉 장을 다 받는다.

**한 건이 아니라 쪽 전체로 본다.** 상단 고정 공고 때문이다 — 공지가 위에 박혀 있으면 첫 건은
늘 아는 공고이고, 그것으로 멈추면 새 공고를 영영 못 본다.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.crawler.api_source import fetch_list
from app.selector.api_schema import parse_api_config


class _Client:
    """부른 쪽 번호를 세는 대역. 실제 요청은 나가지 않는다."""

    def __init__(self, pages: dict[int, list[dict[str, str]]]) -> None:
        self._pages = pages
        self.calls: list[int] = []

    async def request(self, url: str, **kwargs: Any) -> Any:
        body = kwargs.get("json_body") or kwargs.get("form_body") or {}
        number = int(body.get("page", 1))
        self.calls.append(number)
        entries = self._pages.get(number, [])
        return _Result(json.dumps({"items": entries, "hasNext": number < max(self._pages)}))


class _Result:
    def __init__(self, text: str) -> None:
        self.text = text
        self.url = "https://example.com/api"
        self.status_code = 200


def _config() -> Any:
    return parse_api_config(
        json.dumps(
            {
                "list": {
                    "url": "https://example.com/api",
                    "method": "POST",
                    "items_path": "items",
                    "fields": {"title": "title"},
                    "id_field": "id",
                    "link_template": "https://example.com/o/{id}",
                    "pagination": {
                        "param": "page",
                        "start": 1,
                        "max_pages": 10,
                        "has_next": "hasNext",
                    },
                }
            }
        )
    ).list_config()


def _page(start: int, count: int = 3) -> list[dict[str, str]]:
    return [{"title": f"공고 {start + n}", "id": str(start + n)} for n in range(count)]


def _link(entry: dict[str, str]) -> str:
    return f"https://example.com/o/{entry['id']}"


@pytest.fixture
def pages() -> dict[int, list[dict[str, str]]]:
    return {1: _page(1), 2: _page(10), 3: _page(20)}


async def test_아무것도_모르면_끝까지_넘긴다(pages: dict[int, list[dict[str, str]]]) -> None:
    client = _Client(pages)

    result = await fetch_list(client, _config(), known=lambda link: False)

    assert client.calls == [1, 2, 3]
    assert len(result.items) == 9


async def test_판정을_주지_않으면_지금까지처럼_끝까지_넘긴다(
    pages: dict[int, list[dict[str, str]]],
) -> None:
    """기존 호출은 `known` 을 주지 않는다. 동작이 바뀌면 안 된다."""
    client = _Client(pages)

    await fetch_list(client, _config())

    assert client.calls == [1, 2, 3]


async def test_첫_쪽이_전부_아는_공고면_한_쪽만_받는다(
    pages: dict[int, list[dict[str, str]]],
) -> None:
    client = _Client(pages)
    first = {_link(item) for item in pages[1]}

    result = await fetch_list(client, _config(), known=lambda link: link in first)

    assert client.calls == [1]
    # 받은 것은 그대로 돌려준다. 담을지 말지는 부르는 쪽이 다시 본다
    assert len(result.items) == 3


async def test_한_건만_아는_공고면_멈추지_않는다(
    pages: dict[int, list[dict[str, str]]],
) -> None:
    """상단 고정 공고. 이것으로 멈추면 새 공고를 영영 못 본다."""
    client = _Client(pages)
    pinned = _link(pages[1][0])

    await fetch_list(client, _config(), known=lambda link: link == pinned)

    assert client.calls == [1, 2, 3]


async def test_중간_쪽에서도_멈춘다(pages: dict[int, list[dict[str, str]]]) -> None:
    client = _Client(pages)
    second = {_link(item) for item in pages[2]}

    await fetch_list(client, _config(), known=lambda link: link in second)

    assert client.calls == [1, 2]
