"""실행 기록과 실패 목록이 한 트랜잭션으로 남는지 본다.

실사이트에 나가지 않는다. DB 는 임시 파일에 마이그레이션을 올려 쓰고, `RunResult` 는 손으로
만든다 — 여기서 보는 것은 크롤링 결과가 아니라 그 결과를 적는 방식이다.
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import pytest

from app import db
from app.crawler.runner import ItemFailure, RunResult, _finish_run


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "runs.db")
    db.migrate_up(connection)
    connection.execute(
        "INSERT INTO crawlers (name, list_url) VALUES (?, ?)", ("테스트", "https://example.test")
    )
    yield connection
    connection.close()


def started(connection: sqlite3.Connection) -> int:
    cursor = connection.execute("INSERT INTO crawl_runs (crawler_id, trigger) VALUES (1, 'test')")
    return int(cursor.lastrowid or 0)


MISSED = [
    ItemFailure(
        source_url="https://example.test/list",
        error_class="detail_unreachable",
        message="링크·속성·클릭 어느 것으로도 상세에 못 갔다",
        title="2026 상반기 신입 채용",
    ),
    ItemFailure(
        source_url="https://example.test/list",
        error_class="detail_empty",
        message="상세에 갔는데 본문이 비었다",
        title="경력 개발자 채용",
    ),
    ItemFailure(
        source_url="https://example.test/list",
        error_class=None,
        message="분류되지 않은 실패(RuntimeError): 무엇인가 잘못됐다",
        title="디자이너 채용",
    ),
]


def test_실패_세_건이_건수와_목록에_같이_남는다(conn: sqlite3.Connection) -> None:
    run_id = started(conn)
    result = RunResult(run_id=run_id, status="", success_count=2, fail_count=3, failures=MISSED)

    _finish_run(conn, result, None)

    row = conn.execute("SELECT fail_count FROM crawl_runs WHERE id = ?", (run_id,)).fetchone()
    assert row["fail_count"] == 3
    rows = conn.execute(
        "SELECT reason, title, source_url, message FROM crawl_run_failures WHERE run_id = ?"
        " ORDER BY id",
        (run_id,),
    ).fetchall()
    assert len(rows) == 3


def test_어느_공고를_놓쳤는지가_같이_남는다(conn: sqlite3.Connection) -> None:
    """건수만으로는 고칠 수 없다. 제목과 목록에서 읽은 주소가 있어야 한다."""
    run_id = started(conn)

    _finish_run(conn, RunResult(run_id=run_id, status="", success_count=2, failures=MISSED), None)

    rows = conn.execute(
        "SELECT reason, title, source_url FROM crawl_run_failures WHERE run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()
    assert [(row["reason"], row["title"]) for row in rows] == [
        ("detail_unreachable", "2026 상반기 신입 채용"),
        ("detail_empty", "경력 개발자 채용"),
        (None, "디자이너 채용"),
    ]
    assert {row["source_url"] for row in rows} == {"https://example.test/list"}


def test_건너뛴_수는_실패와_따로_남는다(conn: sqlite3.Connection) -> None:
    """합치면 마감 형식이 바뀌어 전부 걸러진 사이트가 "새 공고 0건" 인 정상 실행으로 보인다."""
    run_id = started(conn)
    result = RunResult(run_id=run_id, status="", success_count=4, fail_count=1, skipped_count=83)

    _finish_run(conn, result, None)

    row = conn.execute(
        "SELECT status, success_count, fail_count, skipped_count FROM crawl_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    assert (row["fail_count"], row["skipped_count"]) == (1, 83)
    assert (row["status"], row["success_count"]) == ("success", 4)


def test_실패가_없으면_목록에_아무것도_남지_않는다(conn: sqlite3.Connection) -> None:
    run_id = started(conn)

    _finish_run(conn, RunResult(run_id=run_id, status="", success_count=5), None)

    assert conn.execute("SELECT count(*) AS n FROM crawl_run_failures").fetchone()["n"] == 0


def test_실패_목록이_거절되면_실행_기록도_남지_않는다(conn: sqlite3.Connection) -> None:
    """한 트랜잭션이다. 건수만 3으로 적히고 어느 공고인지 없는 상태가 남으면 안 된다."""
    run_id = started(conn)
    result = RunResult(
        run_id=run_id,
        status="",
        success_count=2,
        fail_count=1,
        failures=[
            ItemFailure(source_url="https://example.test/1", error_class="detail_gone", message="")
        ],
    )

    with pytest.raises(sqlite3.IntegrityError):
        _finish_run(conn, result, None)

    row = conn.execute(
        "SELECT status, fail_count, finished_at FROM crawl_runs WHERE id = ?", (run_id,)
    ).fetchone()
    assert (row["status"], row["fail_count"], row["finished_at"]) == (None, 0, None)
    assert conn.execute("SELECT count(*) AS n FROM crawl_run_failures").fetchone()["n"] == 0
