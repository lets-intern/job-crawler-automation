"""등록 시 백필 상한. 첫 실행만 막고 그 뒤로는 안 막는다.

2026-08-26 에 사이트 열두 곳을 등록하면서 670건이 한 번에 들어왔다. 그 뒤 실행은 신규 0~1건
이다. 저장량과 분류 토큰이 튀는 자리가 평소 수집이 아니라 **등록 직후 한 번**이라, 막을 곳도
거기 하나다.

**두 번째 실행부터는 걸지 않는다.** 상한이 계속 있으면 목록이 상한보다 길게 밀린 날에 뒤쪽
공고를 영영 못 본다 — 목록에서 밀려난 공고는 다시 올라오지 않는다.
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import pytest

from app import db, settings
from app.crawler.runner import first_run_limit


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


def _run(conn: sqlite3.Connection, *, new_count: int, status: str = "success") -> None:
    conn.execute(
        """
        INSERT INTO crawl_runs (workflow_id, trigger, status, new_count)
        VALUES (1, 'schedule', ?, ?)
        """,
        (status, new_count),
    )


def test_첫_실행은_상한을_받는다(conn: sqlite3.Connection) -> None:
    settings.write_int(conn, settings.FIRST_RUN_LIMIT, 20)

    assert first_run_limit(conn, 1) == 20


def test_담은_적이_있으면_상한이_없다(conn: sqlite3.Connection) -> None:
    settings.write_int(conn, settings.FIRST_RUN_LIMIT, 20)
    _run(conn, new_count=20)

    assert first_run_limit(conn, 1) is None


def test_0건으로_끝난_실행은_첫_실행을_소진하지_않는다(conn: sqlite3.Connection) -> None:
    """셀렉터가 틀려 0건으로 끝난 뒤 고쳐서 다시 도는 것이 흔하다.

    그때 상한이 풀려 있으면 백필을 막으려던 것이 그대로 새어 나간다.
    """
    settings.write_int(conn, settings.FIRST_RUN_LIMIT, 20)
    _run(conn, new_count=0, status="failed")
    _run(conn, new_count=0)

    assert first_run_limit(conn, 1) == 20


def test_0_은_상한_없음이다(conn: sqlite3.Connection) -> None:
    settings.write_int(conn, settings.FIRST_RUN_LIMIT, 0)

    assert first_run_limit(conn, 1) is None


def test_다른_워크플로우의_실행은_세지_않는다(conn: sqlite3.Connection) -> None:
    settings.write_int(conn, settings.FIRST_RUN_LIMIT, 20)
    conn.execute("INSERT INTO workflows (id, crawler_id, name) VALUES (2, 1, '다른 것')")
    conn.execute(
        """
        INSERT INTO crawl_runs (workflow_id, trigger, status, new_count)
        VALUES (2, 'schedule', 'success', 50)
        """
    )

    assert first_run_limit(conn, 1) == 20


def test_음수는_저장되지_않는다(conn: sqlite3.Connection) -> None:
    with pytest.raises(settings.SettingValueError):
        settings.write_int(conn, settings.FIRST_RUN_LIMIT, -1)
