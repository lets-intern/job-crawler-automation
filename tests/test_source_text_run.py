"""수집 실행이 원문을 `raw_jobs.raw_data_json.source_text` 에 넣는지 본다.

파서가 원문을 만드는지는 `tests/test_source_text.py` 가 본다. 여기는 그 값이 적재까지
그대로 가는지, 그리고 원문이 없는 건이 지금까지와 같은 모양으로 적재되는지를 본다.

실사이트에 나가지 않는다. 목록과 상세는 스텁이고 DB 는 임시 파일이다.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
from collections.abc import Iterator

import pytest

from app import db
from app.crawler.collect import Collectors
from app.crawler.parser import DetailParseResult, ListItem, ListParseResult
from app.crawler.runner import SCHEDULE, RunTarget, run_once
from app.selector.schema import DETAIL_FIELDS, validate_selectors

LIST_URL = "https://example.test/jobs"

SELECTORS = validate_selectors(
    {
        "list": {"item": "ul.jobs > li", "title": "h3", "link": "a", "date": "span.d"},
        "detail": {
            "title": "p.title",
            "body": "div.body",
            "requirements": "",
            "deadline": "",
            "department": "",
        },
    }
)

ITEMS = [ListItem(index=0, title="백엔드 개발자", link=f"{LIST_URL}/1", date="")]


class StubList:
    async def collect(self) -> ListParseResult:
        return ListParseResult(matched=len(ITEMS), items=list(ITEMS), failures=[])


class StubDetail:
    """상세 필드와 원문을 손으로 준다. 원문을 주지 않는 사이트가 기본값이다."""

    def __init__(self, body: str = "본문이다", source: str = "") -> None:
        self._body = body
        self._source = source

    async def collect(self, item: ListItem) -> DetailParseResult:
        fields = dict.fromkeys(DETAIL_FIELDS, "")
        fields["title"] = item.title
        fields["body"] = self._body
        return DetailParseResult(fields=fields, missing=[], source_text=self._source)


def collectors(detail: StubDetail) -> Collectors:
    return Collectors(list_mode="static", detail_mode="static", list=StubList(), detail=detail)


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    connection.execute(
        "INSERT INTO crawlers (name, list_url, status) VALUES (?, ?, 'draft')",
        ("예시", LIST_URL),
    )
    connection.execute("INSERT INTO workflows (crawler_id, name) VALUES (1, '예시 채용')")
    try:
        yield connection
    finally:
        connection.close()


def target() -> RunTarget:
    return RunTarget(list_url=LIST_URL, selectors=SELECTORS, trigger=SCHEDULE, workflow_id=1)


def stored(conn: sqlite3.Connection) -> dict[str, str]:
    row = conn.execute("SELECT raw_data_json FROM raw_jobs").fetchone()
    assert row is not None
    data: dict[str, str] = json.loads(row["raw_data_json"])
    return data


async def test_원문은_적재된_공고의_source_text_로_들어간다(conn: sqlite3.Connection) -> None:
    detail = StubDetail(body="본문이다", source="제목\n회사 예시\n본문이다\n근무지 판교")

    await run_once(conn, target(), collectors=collectors(detail), limit=1)

    data = stored(conn)
    assert data["source_text"] == "제목\n회사 예시\n본문이다\n근무지 판교"
    assert data["body"] == "본문이다"


async def test_원문은_저장할_때_손대지_않는다(conn: sqlite3.Connection) -> None:
    """줄바꿈과 공백까지 뽑은 그대로다. 정제는 정규화의 몫이다."""
    raw = "\n\n제목\n\n  회사 예시  \n\n본문이다\n\n"
    await run_once(conn, target(), collectors=collectors(StubDetail(source=raw)), limit=1)

    assert stored(conn)["source_text"] == raw
