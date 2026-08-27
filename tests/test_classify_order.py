"""분류는 최근 수집한 것부터 돈다.

2026-08-27 에 뒤집었다. 크레딧이 끊겨 313건이 밀려 있는데 오래된 것부터 돌면 **오늘 들어온
공고가 맨 뒤에 선다.** 소비 측이 지금 필요한 것은 오늘 올라온 공고이고, 밀린 것은 급하지 않다.

신규가 하루 0~1건이라 이 순서로도 밀린 것은 결국 다 돈다. 최근 것이 계속 밀려 들어와 옛것이
영영 안 도는 상황은 이 수집량에서는 생기지 않는다.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
from collections.abc import Iterator

import pytest

from app import db
from app.classify.store import pending_count, pending_ids


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    connection.execute(
        "INSERT INTO crawlers (id, name, list_url, selectors_json) VALUES (1, '테스트', 'x', '{}')"
    )
    connection.execute("INSERT INTO workflows (id, crawler_id, name) VALUES (1, 1, '테스트')")
    for number in (1, 2, 3, 4):
        connection.execute(
            """
            INSERT INTO raw_jobs (id, workflow_id, source_url, raw_data_json, content_hash)
            VALUES (?, 1, ?, ?, ?)
            """,
            (
                number,
                f"https://example.com/{number}",
                json.dumps({"body": f"본문 {number}"}, ensure_ascii=False),
                f"hash{number}",
            ),
        )
    try:
        yield connection
    finally:
        connection.close()


def test_최근_것부터_준다(conn: sqlite3.Connection) -> None:
    assert pending_ids(conn) == [4, 3, 2, 1]


def test_상한이_걸리면_최근_것만_고른다(conn: sqlite3.Connection) -> None:
    """상한이 있을 때 무엇이 잘려 나가는지가 이 순서의 요점이다."""
    assert pending_ids(conn, limit=2) == [4, 3]


def test_분류된_것은_빠진다(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO job_classifications (raw_job_id, model) VALUES (4, '테스트')")

    assert pending_ids(conn) == [3, 2, 1]
    assert pending_count(conn) == 3


def test_본문이_없으면_애초에_안_센다(conn: sqlite3.Connection) -> None:
    """본문이 없으면 읽을 것이 없다. 부를 이유가 없는 호출을 만들지 않는다."""
    conn.execute(
        "UPDATE raw_jobs SET raw_data_json = ? WHERE id = 4",
        (json.dumps({"body": ""}, ensure_ascii=False),),
    )

    assert pending_ids(conn) == [3, 2, 1]
