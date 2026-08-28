"""부가 워크플로우 실행기. 실행 하나가 행 하나를 남기는지 본다.

모델에도 실사이트에도 나가지 않는다. 임시 DB 에 실제 마이그레이션을 적용하고, 분류는 가짜
제공자로 돈다.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from app import db
from app.side import runner, runs, store


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


def test_a_run_that_finishes_is_closed_as_success(
    conn: sqlite3.Connection, workflow: store.SideWorkflow
) -> None:
    def body(
        _: sqlite3.Connection, __: store.SideWorkflow, counts: runs.SideRunCounts
    ) -> str | None:
        counts.target_count = 5
        counts.processed_count = 5
        return None

    run = runner.run_once(conn, workflow.id, body)

    assert run.status == runs.SUCCESS
    assert run.finished_at is not None
    assert (run.target_count, run.processed_count) == (5, 5)
    assert run.error_message is None


def test_a_body_that_raises_still_closes_the_row(
    conn: sqlite3.Connection, workflow: store.SideWorkflow
) -> None:
    """예외로 끝난 실행이 열린 채로 남으면 화면은 그것을 영원히 진행 중으로 읽는다."""

    def body(
        _: sqlite3.Connection, __: store.SideWorkflow, counts: runs.SideRunCounts
    ) -> str | None:
        counts.target_count = 3
        raise RuntimeError("본문이 터졌다")

    run = runner.run_once(conn, workflow.id, body)

    assert run.status == runs.FAILED
    assert run.finished_at is not None
    # 터지기 전까지 채운 카운트는 남는다
    assert run.target_count == 3
    assert run.error_message == "RuntimeError: 본문이 터졌다"


def test_an_exception_does_not_reach_the_caller(
    conn: sqlite3.Connection, workflow: store.SideWorkflow
) -> None:
    """스케줄러까지 올라간 예외는 아무도 보지 못한 채 잡을 죽인다 (3.4)."""

    def body(_: sqlite3.Connection, __: store.SideWorkflow, ___: runs.SideRunCounts) -> str | None:
        raise ValueError("사유")

    # 예외가 올라오면 이 줄에서 테스트가 깨진다
    assert runner.run_once(conn, workflow.id, body).status == runs.FAILED


def test_a_body_that_reports_a_reason_closes_as_failed(
    conn: sqlite3.Connection, workflow: store.SideWorkflow
) -> None:
    """예외 없이 실패하는 실행이 있다. 키가 없는 분류가 그것이다 (3.4)."""

    def body(
        _: sqlite3.Connection, __: store.SideWorkflow, counts: runs.SideRunCounts
    ) -> str | None:
        counts.target_count = 2
        counts.failed_count = 2
        return "GEMINI_API_KEY 가 없다"

    run = runner.run_once(conn, workflow.id, body)

    assert run.status == runs.FAILED
    assert run.error_message == "GEMINI_API_KEY 가 없다"
    assert run.failed_count == 2


def test_the_settings_come_from_the_table_not_the_caller(
    conn: sqlite3.Connection, workflow: store.SideWorkflow
) -> None:
    """화면에서 범위를 좁혀 저장했는데 옛 범위로 도는 일이 없어야 한다."""
    store.update(
        conn,
        workflow.id,
        name="분류",
        status="active",
        trigger_kind="interval",
        interval_minutes=60,
        target_scope="recent",
        target_days=3,
        batch_limit=7,
    )
    seen: list[tuple[str, int | None, int]] = []

    def body(
        _: sqlite3.Connection, given: store.SideWorkflow, __: runs.SideRunCounts
    ) -> str | None:
        seen.append((given.target_scope, given.target_days, given.batch_limit))
        return None

    runner.run_once(conn, workflow.id, body)

    assert seen == [("recent", 3, 7)]


def test_running_a_workflow_that_is_gone_is_refused(conn: sqlite3.Connection) -> None:
    with pytest.raises(store.SideWorkflowNotFoundError):
        runner.run_once(conn, 404, lambda *_: None)


def test_the_run_is_recorded_before_the_body_runs(
    conn: sqlite3.Connection, workflow: store.SideWorkflow
) -> None:
    """도는 동안 행이 열려 있어야 화면이 진행 중을 읽는다."""
    open_rows: list[int] = []

    def body(
        inner: sqlite3.Connection, __: store.SideWorkflow, ___: runs.SideRunCounts
    ) -> str | None:
        row = inner.execute("SELECT count(*) AS n FROM side_runs WHERE status IS NULL").fetchone()
        open_rows.append(int(row["n"]))
        return None

    runner.run_once(conn, workflow.id, body)

    assert open_rows == [1]
    # 마지막 실행 시각은 시작에 적힌다 (Push 1 결정)
    updated = store.read(conn, workflow.id)
    assert updated is not None and updated.last_run_at is not None
