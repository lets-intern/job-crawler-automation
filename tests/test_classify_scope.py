"""분류가 무엇을 대상으로 도는가. 범위 넷을 본다.

2.1.V ~ 2.5.V 다.

범위는 `side_workflows.target_scope` 에 저장된 낱말 하나이고, 그것이 실제로 어느 공고를
고르는지가 여기서 갈린다. 대상이 틀리면 화면이 적은 건수와 실제로 나가는 토큰이 다르다.

**네 범위가 "보낼 글이 있다" 를 같은 조건으로 본다.** 그 조건은 `app/classify/store.py` 의
`_CLASSIFY_TEXT` 하나이고, 원문이 있으면 원문, 없으면 본문이다. 범위마다 다시 쓰면 같은
공고가 어느 범위에서는 대상이고 어느 범위에서는 아니게 된다.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
from collections.abc import Iterator

import pytest

from app import db
from app.classify.store import (
    CLASSIFY_SCOPES,
    UNCLASSIFIED,
    ClassifyScopeError,
    pending_ids,
    scope_ids,
)


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    connection.execute(
        "INSERT INTO crawlers (id, name, list_url, selectors_json) VALUES (1, '테스트', 'x', '{}')"
    )
    connection.execute("INSERT INTO workflows (id, crawler_id, name) VALUES (1, 1, '테스트')")
    try:
        yield connection
    finally:
        connection.close()


def add_job(
    conn: sqlite3.Connection,
    job_id: int,
    *,
    body: str | None = "본문",
    source_text: str | None = None,
    crawled_at: str | None = None,
) -> None:
    """수집된 공고 하나. `body` 가 None 이면 키가 아예 없다 — 옛 건의 모양이다."""
    raw: dict[str, str] = {"title": f"공고 {job_id}"}
    if body is not None:
        raw["body"] = body
    if source_text is not None:
        raw["source_text"] = source_text
    conn.execute(
        """
        INSERT INTO raw_jobs (id, workflow_id, source_url, raw_data_json, content_hash, crawled_at)
        VALUES (?, 1, ?, ?, ?, coalesce(?, datetime('now')))
        """,
        (
            job_id,
            f"https://example.com/{job_id}",
            json.dumps(raw, ensure_ascii=False),
            f"hash{job_id}",
            crawled_at,
        ),
    )


def classify(conn: sqlite3.Connection, job_id: int, **fields: str) -> None:
    """분류 행 하나. 칸을 주지 않으면 전부 빈 분류다."""
    columns = ", ".join(fields)
    values = ", ".join("?" for _ in fields)
    conn.execute(
        f"INSERT INTO job_classifications (raw_job_id, model{', ' + columns if fields else ''})"
        f" VALUES (?, '테스트'{', ' + values if fields else ''})",
        (job_id, *fields.values()),
    )


def test_범위_이름이_저장되는_값과_같다() -> None:
    """이름을 두 벌 두면 저장은 되는데 아무것도 고르지 못하는 워크플로우가 생긴다."""
    from app.side.store import CLASSIFY, SCOPES

    assert SCOPES[CLASSIFY] == CLASSIFY_SCOPES


def test_분류되지_않은_건만_고른다(conn: sqlite3.Connection) -> None:
    add_job(conn, 1)
    add_job(conn, 2)
    add_job(conn, 3)
    classify(conn, 2)

    assert scope_ids(conn, UNCLASSIFIED) == [3, 1]


def test_분류가_전부_빈_행이어도_분류된_것이다(conn: sqlite3.Connection) -> None:
    """행이 있으면 돈 것이다. 아무것도 안 나온 것과 아직 안 돈 것은 다르다."""
    add_job(conn, 1)
    classify(conn, 1)

    assert scope_ids(conn, UNCLASSIFIED) == []


def test_지금_도는_조회에_연결돼_있다(conn: sqlite3.Connection) -> None:
    """`unclassified` 는 새 조회가 아니라 `pending_ids` 그대로다.

    갈리면 화면에서 고른 범위와 지금 도는 분류가 서로 다른 공고를 집는다.
    """
    add_job(conn, 1)
    add_job(conn, 2, body="", source_text="원문만 있는 건")
    add_job(conn, 3, body=None)
    classify(conn, 1)

    assert scope_ids(conn, UNCLASSIFIED) == pending_ids(conn)
    assert scope_ids(conn, UNCLASSIFIED, limit=1) == pending_ids(conn, limit=1)


def test_상한이_걸리면_최근_것부터_자른다(conn: sqlite3.Connection) -> None:
    for job_id in (1, 2, 3):
        add_job(conn, job_id)

    assert scope_ids(conn, UNCLASSIFIED, limit=2) == [3, 2]


def test_모르는_범위는_사유와_함께_거절된다(conn: sqlite3.Connection) -> None:
    with pytest.raises(ClassifyScopeError) as caught:
        scope_ids(conn, "everything")

    assert "everything" in str(caught.value)
    assert UNCLASSIFIED in str(caught.value)
