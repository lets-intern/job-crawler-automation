"""프로세스가 죽으며 남긴 미완 실행을 기동 시 닫는다.

실행 중 컨테이너가 재시작되면 `crawl_runs` 행이 종료 상태 없이 남는다. 밖에서 온 취소는
코드가 받아 적지만 SIGKILL 은 받을 기회를 주지 않는다.

2026-08-22 에 실제로 겪었다. `--reload` 로 띄운 컨테이너가 파일 변경마다 다시 뜨면서
SK 실행 한 건이 20분 넘게 미완으로 남았다.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app import db
from app.crawler.runner import close_orphan_runs


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = db.connect(tmp_path / "orphan.db")
    db.migrate_up(connection)
    # crawl_runs 가 워크플로우를 가리키므로 그 앞의 행들이 먼저 있어야 한다
    connection.execute(
        "INSERT INTO crawlers (id, name, list_url, status)"
        " VALUES (1, '테스트', 'https://x', 'promoted')"
    )
    connection.execute(
        "INSERT INTO workflows (id, crawler_id, name, interval_minutes)"
        " VALUES (1, 1, '테스트', 360)"
    )
    return connection


def _rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT id, status, finished_at FROM crawl_runs ORDER BY id").fetchall()


def test_an_unfinished_run_is_closed_as_timeout(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO crawl_runs (workflow_id) VALUES (1)")

    closed = close_orphan_runs(conn)

    assert closed == 1
    row = _rows(conn)[0]
    assert row["status"] == "timeout"
    assert row["finished_at"] is not None


def test_finished_runs_are_left_alone(conn: sqlite3.Connection) -> None:
    """이미 끝난 행을 다시 쓰면 성공한 실행이 실패로 뒤집힌다."""
    conn.execute(
        "INSERT INTO crawl_runs (workflow_id, status, finished_at, success_count)"
        " VALUES (1, 'success', '2026-08-21 10:00:00', 7)"
    )

    assert close_orphan_runs(conn) == 0

    row = _rows(conn)[0]
    assert row["status"] == "success"
    assert row["finished_at"] == "2026-08-21 10:00:00"


def test_nothing_to_close_is_not_an_error(conn: sqlite3.Connection) -> None:
    assert close_orphan_runs(conn) == 0
