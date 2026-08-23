"""스케줄러 등록·갱신 테스트.

실제 시각을 기다리지 않는다. 확인하는 것은 "테이블이 이러면 잡이 이렇게 된다" 하나다 —
주기가 되면 도는지는 `app/scheduler.py` 가 아니라 APScheduler 의 책임이다.

실사이트에 나가지 않는다. 잡이 부르는 실행 함수는 워크플로우 id 만 받아 적는 스텁이다.
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app import db
from app.scheduler import WorkflowScheduler, job_id, workflow_id_of


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    connection.execute(
        "INSERT INTO crawlers (name, list_url, status) VALUES (?, ?, 'promoted')",
        ("python.org", "https://www.python.org/jobs/"),
    )
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def calls() -> list[int]:
    return []


@pytest.fixture
def scheduler(calls: list[int]) -> Iterator[WorkflowScheduler]:
    async def record(workflow_id: int) -> None:
        calls.append(workflow_id)

    # 시작하지 않는다. 잡은 pending 으로 쌓이고 조회·갱신·제거는 그대로 동작한다
    instance = WorkflowScheduler(scheduler=AsyncIOScheduler(timezone="UTC"), runner=record)
    try:
        yield instance
    finally:
        instance.shutdown()


def add_workflow(conn: sqlite3.Connection, name: str, minutes: int, status: str = "active") -> int:
    cursor = conn.execute(
        """
        INSERT INTO workflows (crawler_id, name, interval_minutes, status)
        VALUES (1, ?, ?, ?)
        """,
        (name, minutes, status),
    )
    return int(cursor.lastrowid or 0)


def test_기동_시_active_인_워크플로우만_등록한다(
    scheduler: WorkflowScheduler, conn: sqlite3.Connection
) -> None:
    running = add_workflow(conn, "도는 것", 60)
    stopped = add_workflow(conn, "멈춘 것", 60, status="paused")

    report = scheduler.sync(conn)

    assert report.added == [running]
    assert scheduler.scheduled() == {running: 60}
    assert stopped not in scheduler.scheduled()


def test_주기가_바뀌면_잡을_갱신한다(
    scheduler: WorkflowScheduler, conn: sqlite3.Connection
) -> None:
    workflow_id = add_workflow(conn, "주기 변경", 60)
    scheduler.sync(conn)

    conn.execute("UPDATE workflows SET interval_minutes = 15 WHERE id = ?", (workflow_id,))
    report = scheduler.sync(conn)

    assert report.updated == [workflow_id]
    assert report.added == []
    assert scheduler.scheduled() == {workflow_id: 15}


def test_paused_로_바뀌면_잡이_사라진다(
    scheduler: WorkflowScheduler, conn: sqlite3.Connection
) -> None:
    workflow_id = add_workflow(conn, "중지 대상", 30)
    scheduler.sync(conn)

    conn.execute("UPDATE workflows SET status = 'paused' WHERE id = ?", (workflow_id,))
    report = scheduler.sync(conn)

    assert report.removed == [workflow_id]
    assert scheduler.scheduled() == {}


def test_paused_에서_active_로_돌아오면_다시_등록한다(
    scheduler: WorkflowScheduler, conn: sqlite3.Connection
) -> None:
    workflow_id = add_workflow(conn, "재개 대상", 30, status="paused")
    scheduler.sync(conn)
    assert scheduler.scheduled() == {}

    conn.execute("UPDATE workflows SET status = 'active' WHERE id = ?", (workflow_id,))
    report = scheduler.sync(conn)

    assert report.added == [workflow_id]
    assert scheduler.scheduled() == {workflow_id: 30}


def test_바뀐_것이_없으면_아무것도_하지_않는다(
    scheduler: WorkflowScheduler, conn: sqlite3.Connection
) -> None:
    add_workflow(conn, "그대로", 45)
    scheduler.sync(conn)

    report = scheduler.sync(conn)

    assert not report


def test_스케줄러_메모리가_아니라_테이블이_진실이다(
    scheduler: WorkflowScheduler, conn: sqlite3.Connection
) -> None:
    """잡을 직접 지워도, 테이블에 active 로 남아 있으면 sync 가 되살린다."""
    workflow_id = add_workflow(conn, "되살아나는 것", 20)
    scheduler.sync(conn)
    scheduler.scheduler.remove_job(job_id(workflow_id))

    report = scheduler.sync(conn)

    assert report.added == [workflow_id]
    assert scheduler.scheduled() == {workflow_id: 20}


async def test_잡은_워크플로우_id_만_들고_있다(
    scheduler: WorkflowScheduler, conn: sqlite3.Connection, calls: list[int]
) -> None:
    """URL 과 셀렉터는 잡에 실리지 않는다. 실행 시점에 테이블에서 다시 읽는다."""
    workflow_id = add_workflow(conn, "실행", 60)
    scheduler.sync(conn)

    job = scheduler.scheduler.get_job(job_id(workflow_id))
    assert job.args == (workflow_id,)
    assert job.max_instances == 1

    await job.func(*job.args)
    assert calls == [workflow_id]


def test_우리_잡이_아닌_id_는_건드리지_않는다(
    scheduler: WorkflowScheduler, conn: sqlite3.Connection
) -> None:
    async def unrelated() -> None:
        return None

    scheduler.scheduler.add_job(unrelated, "interval", minutes=5, id="cleanup:snapshots")
    add_workflow(conn, "워크플로우", 10)

    scheduler.sync(conn)

    assert scheduler.scheduler.get_job("cleanup:snapshots") is not None
    assert workflow_id_of("cleanup:snapshots") is None
