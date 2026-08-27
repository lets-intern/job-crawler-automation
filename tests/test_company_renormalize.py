"""운영자값을 고친 뒤 재정규화하는 경로 테스트.

이 분리의 값이 여기서 확인된다. 운영자가 회사명을 잘못 넣었으면 `crawlers.default_company` 를
고치고 재정규화하면 끝이고, `raw_jobs` 는 건드릴 일이 없다.

확인하는 것은 넷이다.

- 운영자값으로 확정했던 행만 새 값을 받는다
- 파싱값으로 확정한 행은 운영자값을 고쳐도 그대로다
- `raw_jobs` 는 바이트 단위로 그대로다
- `delivered_at` 은 그대로다. 지우면 소비 측에 같은 데이터가 다시 간다

픽스처로 돈다. 실사이트에 나가지 않는다.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
from collections.abc import Iterator

import pytest

from app import db
from app.crawler.runner import run_workflow
from app.normalize.backfill import BackfillProgress, renormalize
from app.normalize.engine import OPERATOR, PARSED
from tests.test_company_selector import (
    LIST_URL,
    WITH_COMPANY,
    WITHOUT_COMPANY,
    stub_fetcher,
)
from tests.test_normalize_engine import raw_snapshot

DELIVERED_AT = "2026-08-20T09:00:00+00:00"

# 파싱값이 나오는 크롤러와 나오지 않는 크롤러. 같은 목록 URL 을 봐도 워크플로우가 다르면
# 적재는 각각 따로 쌓인다
PARSED_WORKFLOW = 1
OPERATOR_WORKFLOW = 2


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    for name, selectors, default_company in (
        ("회사명 있는 사이트", WITH_COMPANY, "삼성전자"),
        ("회사명 없는 사이트", WITHOUT_COMPANY, "현대오토에버"),
    ):
        connection.execute(
            """
            INSERT INTO crawlers (name, list_url, selectors_json, status, default_company)
            VALUES (?, ?, ?, 'promoted', ?)
            """,
            (name, LIST_URL, json.dumps(selectors), default_company),
        )
    connection.execute("INSERT INTO workflows (crawler_id, name) VALUES (1, '파싱')")
    connection.execute("INSERT INTO workflows (crawler_id, name) VALUES (2, '운영자')")
    try:
        yield connection
    finally:
        connection.close()


async def collect(conn: sqlite3.Connection) -> None:
    """두 워크플로우를 각각 1회 돌리고 전달 표시를 붙인다."""
    await run_workflow(conn, PARSED_WORKFLOW, fetcher=stub_fetcher(), limit=2)
    await run_workflow(conn, OPERATOR_WORKFLOW, fetcher=stub_fetcher(), limit=2)
    conn.execute("UPDATE normalized_jobs SET delivered_at = ?", (DELIVERED_AT,))


def rows_by_workflow(conn: sqlite3.Connection, workflow_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT n.id AS id, n.company AS company, n.company_source AS company_source,
                   n.delivered_at AS delivered_at
              FROM normalized_jobs n
              JOIN raw_jobs r ON r.id = n.raw_job_id
             WHERE r.workflow_id = ?
             ORDER BY n.raw_job_id
            """,
            (workflow_id,),
        ).fetchall()
    )


def set_default_company(conn: sqlite3.Connection, crawler_id: int, value: str) -> None:
    conn.execute("UPDATE crawlers SET default_company = ? WHERE id = ?", (value, crawler_id))


async def test_only_operator_rows_follow_the_new_value(conn: sqlite3.Connection) -> None:
    await collect(conn)
    assert [row["company"] for row in rows_by_workflow(conn, OPERATOR_WORKFLOW)] == [
        "현대오토에버",
        "현대오토에버",
    ]
    before = [row["id"] for row in rows_by_workflow(conn, OPERATOR_WORKFLOW)]

    set_default_company(conn, 2, "현대모비스")
    renormalize(conn, BackfillProgress())

    after = rows_by_workflow(conn, OPERATOR_WORKFLOW)
    assert [row["company"] for row in after] == ["현대모비스", "현대모비스"]
    assert [row["company_source"] for row in after] == [OPERATOR, OPERATOR]
    # 새 행이 생기는 것이 아니라 있던 행이 갱신된다
    assert [row["id"] for row in after] == before


async def test_parsed_rows_do_not_move_when_the_operator_value_changes(
    conn: sqlite3.Connection,
) -> None:
    await collect(conn)

    set_default_company(conn, 1, "엉뚱한 회사")
    renormalize(conn, BackfillProgress())

    after = rows_by_workflow(conn, PARSED_WORKFLOW)
    assert [row["company"] for row in after] == ["삼성SDS", "삼성전기(주)"]
    assert [row["company_source"] for row in after] == [PARSED, PARSED]


async def test_renormalizing_leaves_raw_jobs_byte_identical(conn: sqlite3.Connection) -> None:
    await collect(conn)
    before = raw_snapshot(conn)

    set_default_company(conn, 2, "현대모비스")
    renormalize(conn, BackfillProgress())

    assert raw_snapshot(conn) == before


async def test_renormalizing_keeps_the_delivery_mark(conn: sqlite3.Connection) -> None:
    """가져간 표시를 지우면 소비 측에 같은 데이터가 다시 간다."""
    await collect(conn)

    set_default_company(conn, 2, "현대모비스")
    renormalize(conn, BackfillProgress())

    delivered = conn.execute("SELECT delivered_at FROM normalized_jobs").fetchall()
    assert [row["delivered_at"] for row in delivered] == [DELIVERED_AT] * 4


async def test_clearing_the_operator_value_falls_back_to_the_crawler_name(
    conn: sqlite3.Connection,
) -> None:
    """운영자가 지우면 크롤러 이름으로 내려간다. 빈 문자열로 채우지는 않는다 (1.3).

    2026-08-26 이전에는 여기서 NULL 로 돌아갔다. 목록이 회사명을 주지 않는 사이트가 있어서,
    비워 두는 것보다 상위 기업 이름이라도 있는 편이 낫다고 정했다.
    """
    await collect(conn)
    name = conn.execute("SELECT name FROM crawlers WHERE id = 2").fetchone()["name"]

    conn.execute("UPDATE crawlers SET default_company = NULL WHERE id = 2")
    renormalize(conn, BackfillProgress())

    after = rows_by_workflow(conn, OPERATOR_WORKFLOW)
    assert [row["company"] for row in after] == [name, name]
    assert [row["company_source"] for row in after] == [OPERATOR, OPERATOR]
