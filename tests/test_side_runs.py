"""부가 워크플로우 실행 기록. 기록이 없는 실행이 없는지 본다.

닫는 경로가 셋이라 셋 다 확인한다. 정상 종료, 예외, 그리고 프로세스가 사라진 뒤의 뒷정리다.
가운데가 이 파일의 요점이다 — **시작만 하고 실패한 실행에도 행이 남고 상태가 찍혀야 한다.**
그렇지 않으면 실패한 실행은 아무 데도 없고, 운영자가 보는 것은 "실행한 적 없음" 이다
(`.claude/rules/crawling.md`).

임시 DB 에 실제 마이그레이션을 적용하고 돈다. 모델에도 실사이트에도 나가지 않는다.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from app import db
from app.side import runs, store


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "side.db")
    db.migrate_up(connection)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def workflow(conn: sqlite3.Connection) -> store.SideWorkflow:
    return store.create(conn, kind="classify", name="분류")


def rows(conn: sqlite3.Connection) -> list[runs.SideRun]:
    ids = conn.execute("SELECT id FROM side_runs ORDER BY id").fetchall()
    return [run for row in ids if (run := runs.read(conn, int(row["id"]))) is not None]


def test_a_run_that_finishes_normally_is_closed_as_success(
    conn: sqlite3.Connection, workflow: store.SideWorkflow
) -> None:
    with runs.recording(conn, workflow.id, "manual") as counts:
        counts.target_count = 10
        counts.processed_count = 9
        counts.failed_count = 1

    stored = rows(conn)
    assert len(stored) == 1
    assert stored[0].status == "success"
    assert (stored[0].target_count, stored[0].processed_count, stored[0].failed_count) == (10, 9, 1)
    assert stored[0].finished_at
    assert stored[0].error_message is None
    assert not stored[0].running


def test_a_run_that_raises_still_leaves_a_row_with_its_status(
    conn: sqlite3.Connection, workflow: store.SideWorkflow
) -> None:
    """시작만 하고 실패한 실행이 이 파일의 요점이다. 예외는 삼키지 않고 올려 보낸다."""
    with pytest.raises(RuntimeError):
        with runs.recording(conn, workflow.id, "schedule") as counts:
            counts.target_count = 5
            counts.processed_count = 2
            raise RuntimeError("모델 키가 없다")

    stored = rows(conn)
    assert len(stored) == 1
    assert stored[0].status == "failed"
    assert stored[0].finished_at
    # 예외로 끝나기 전까지 센 것은 남는다. 어디까지 갔는지가 다음 실행을 정한다
    assert (stored[0].target_count, stored[0].processed_count) == (5, 2)
    assert stored[0].error_message is not None
    assert "모델 키가 없다" in stored[0].error_message


def test_a_cancelled_run_is_recorded_too(
    conn: sqlite3.Connection, workflow: store.SideWorkflow
) -> None:
    """`BaseException` 도 종료 경로다. 그렇게 끝난 실행이야말로 기록이 남아야 한다."""
    with pytest.raises(KeyboardInterrupt):
        with runs.recording(conn, workflow.id, "manual"):
            raise KeyboardInterrupt

    assert [run.status for run in rows(conn)] == ["failed"]


def test_a_run_is_open_while_it_is_going(
    conn: sqlite3.Connection, workflow: store.SideWorkflow
) -> None:
    """도는 동안에도 행이 있다. 끝나고 나서 한 번에 적으면 사라진 실행이 남지 않는다."""
    seen: list[runs.SideRun] = []
    with runs.recording(conn, workflow.id, "manual"):
        found = rows(conn)[0]
        seen.append(found)

    assert seen[0].running
    assert (seen[0].status, seen[0].finished_at) == (None, None)
    assert seen[0].started_at
    assert seen[0].trigger == "manual"


def test_the_body_can_close_a_normal_run_as_failed(
    conn: sqlite3.Connection, workflow: store.SideWorkflow
) -> None:
    """예외 없이 끝났어도 실행기가 실패라고 말할 수 있다. 비워 두면 성공이다."""
    with runs.recording(conn, workflow.id, "schedule") as counts:
        counts.failed_count = 3
        counts.status = "failed"
        counts.note = "모든 건이 실패했다"

    stored = rows(conn)[0]
    assert (stored.status, stored.note) == ("failed", "모든 건이 실패했다")


def test_starting_a_run_stamps_the_workflow_last_run_at(
    conn: sqlite3.Connection, workflow: store.SideWorkflow
) -> None:
    """시작할 때 적는다. 사라진 실행도 목록에서 "실행한 적 없음" 으로 보이지 않는다."""
    assert workflow.last_run_at is None

    with pytest.raises(RuntimeError):
        with runs.recording(conn, workflow.id, "schedule"):
            raise RuntimeError("바로 죽었다")

    stamped = store.read(conn, workflow.id)
    assert stamped is not None
    assert stamped.last_run_at


def test_a_skipped_turn_leaves_a_closed_row_with_its_reason(
    conn: sqlite3.Connection, workflow: store.SideWorkflow
) -> None:
    """남기지 않으면 주기가 도는데 못 도는 상태와 주기가 죽은 상태가 같아 보인다."""
    runs.skipped(conn, workflow.id, "schedule", "앞 실행이 아직 돌고 있다")

    stored = rows(conn)[0]
    assert (stored.status, stored.note) == ("skipped", "앞 실행이 아직 돌고 있다")
    assert stored.finished_at
    assert (stored.processed_count, stored.failed_count) == (0, 0)


def test_close_orphans_closes_only_the_runs_left_open(
    conn: sqlite3.Connection, workflow: store.SideWorkflow
) -> None:
    """기동할 때의 뒷정리다. 프로세스가 사라져 아무도 종료를 적지 못한 행을 닫는다."""
    with runs.recording(conn, workflow.id, "manual"):
        pass
    killed = runs.start(conn, workflow.id, "schedule")

    assert runs.close_orphans(conn) == 1

    orphan = runs.read(conn, killed)
    assert orphan is not None
    assert orphan.status == "timeout"
    assert orphan.finished_at
    assert orphan.error_message == "프로세스가 끝나기 전에 사라져 결과를 남기지 못했다"
    assert [run.status for run in rows(conn)] == ["success", "timeout"]

    # 두 번 불러도 닫을 것이 없다
    assert runs.close_orphans(conn) == 0


def test_close_orphans_on_a_database_without_the_table_is_quiet(tmp_path: Path) -> None:
    """기동 시 뒷정리이지 기동 조건이 아니다. 스키마가 없다고 앱이 뜨지 않으면 안 된다."""
    empty = db.connect(tmp_path / "empty.db")
    try:
        assert runs.close_orphans(empty) == 0
    finally:
        empty.close()


def test_every_run_belongs_to_a_workflow(conn: sqlite3.Connection) -> None:
    """어디에도 안 걸린 실행 기록은 누구의 것인지 알 수 없다."""
    with pytest.raises(sqlite3.IntegrityError):
        runs.start(conn, 999, "manual")


def test_reading_a_missing_run_returns_none(conn: sqlite3.Connection) -> None:
    assert runs.read(conn, 999) is None


def test_a_long_error_message_is_shortened(
    conn: sqlite3.Connection, workflow: store.SideWorkflow
) -> None:
    """키 하나가 틀리면 같은 문장이 실행마다 쌓인다."""
    with pytest.raises(RuntimeError):
        with runs.recording(conn, workflow.id, "manual"):
            raise RuntimeError("가" * 2000)

    stored = rows(conn)[0]
    assert stored.error_message is not None
    assert len(stored.error_message) == runs.MAX_ERROR_CHARS
