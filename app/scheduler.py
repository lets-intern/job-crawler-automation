"""APScheduler 등록과 갱신.

`workflows` 테이블이 진실이다. 스케줄러가 들고 있는 잡 목록은 테이블의 사본일 뿐이고, 둘이
어긋나면 테이블 쪽으로 맞춘다 (`.claude/rules/crawling.md`).

그래서 등록도 갱신도 `sync()` 하나로 한다. 기동 시에도, 주기나 상태가 바뀐 뒤에도 같은 함수를
부른다 — "이 워크플로우만 다시 등록" 같은 부분 갱신 경로를 따로 두면 그 경로가 빠뜨린 변경이
스케줄러 메모리에만 남는다.

무엇을 실행할지도 잡이 아니라 테이블이 정한다. 잡에 실려 있는 것은 워크플로우 id 뿐이고,
URL 과 셀렉터는 실행 시점에 `app/crawler/runner.py` 가 다시 읽는다.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from apscheduler.events import EVENT_JOB_MAX_INSTANCES, JobExecutionEvent
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app import db
from app.crawler.runner import run_workflow

logger = logging.getLogger(__name__)

JOB_PREFIX = "workflow:"

RunFn = Callable[[int], Awaitable[None]]


def job_id(workflow_id: int) -> str:
    return f"{JOB_PREFIX}{workflow_id}"


def workflow_id_of(job_identifier: str) -> int | None:
    """잡 id 에서 워크플로우 id 를 되읽는다. 우리 잡이 아니면 None."""
    if not job_identifier.startswith(JOB_PREFIX):
        return None
    tail = job_identifier[len(JOB_PREFIX) :]
    return int(tail) if tail.isdigit() else None


@dataclass
class SyncReport:
    """`sync()` 가 테이블에 맞춘 결과. 로그와 테스트가 읽는다."""

    added: list[int] = field(default_factory=list)
    updated: list[int] = field(default_factory=list)
    removed: list[int] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.added or self.updated or self.removed)


async def _run(workflow_id: int) -> None:
    """잡 하나의 기본 실행 경로. 연결은 실행마다 열고 닫는다."""
    conn = db.connect()
    try:
        await run_workflow(conn, workflow_id)
    finally:
        conn.close()


class WorkflowScheduler:
    """`workflows` 를 APScheduler 잡으로 옮기는 얇은 층.

    `runner` 는 테스트가 갈아끼운다. 운영에서는 `_run` 이다.
    """

    def __init__(
        self,
        *,
        scheduler: AsyncIOScheduler | None = None,
        runner: RunFn | None = None,
    ) -> None:
        self._scheduler = scheduler or AsyncIOScheduler(timezone="UTC")
        self._runner = runner or _run
        self._scheduler.add_listener(_log_skipped_tick, EVENT_JOB_MAX_INSTANCES)

    @property
    def scheduler(self) -> AsyncIOScheduler:
        return self._scheduler

    def start(self, conn: sqlite3.Connection) -> SyncReport:
        """기동. `workflows` 에서 `active` 인 것을 전부 등록한다."""
        if not self._scheduler.running:
            self._scheduler.start()
        return self.sync(conn)

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def sync(self, conn: sqlite3.Connection) -> SyncReport:
        """등록된 잡을 테이블에 맞춘다. 추가·주기 갱신·제거를 한 번에 한다."""
        rows = conn.execute("SELECT id, interval_minutes, status FROM workflows").fetchall()
        wanted = {
            int(row["id"]): int(row["interval_minutes"])
            for row in rows
            if row["status"] == "active"
        }

        report = SyncReport()
        for job in list(self._scheduler.get_jobs()):
            workflow_id = workflow_id_of(job.id)
            if workflow_id is None:
                continue
            minutes = wanted.pop(workflow_id, None)
            if minutes is None:
                # paused 로 바뀌었거나 행이 사라졌다. 어느 쪽이든 더 이상 깨우지 않는다
                self._scheduler.remove_job(job.id)
                report.removed.append(workflow_id)
            elif _interval_minutes(job) != minutes:
                self._scheduler.reschedule_job(job.id, trigger=IntervalTrigger(minutes=minutes))
                report.updated.append(workflow_id)

        for workflow_id, minutes in sorted(wanted.items()):
            self._add(workflow_id, minutes)
            report.added.append(workflow_id)

        if report:
            logger.info(
                "scheduler sync: added=%s updated=%s removed=%s",
                report.added,
                report.updated,
                report.removed,
            )
        return report

    def scheduled(self) -> dict[int, int]:
        """등록된 (워크플로우 id -> 주기 분). 테스트와 진단이 읽는다."""
        found: dict[int, int] = {}
        for job in self._scheduler.get_jobs():
            workflow_id = workflow_id_of(job.id)
            if workflow_id is not None:
                found[workflow_id] = _interval_minutes(job)
        return found

    def _add(self, workflow_id: int, minutes: int) -> None:
        self._scheduler.add_job(
            self._runner,
            trigger=IntervalTrigger(minutes=minutes),
            args=[workflow_id],
            id=job_id(workflow_id),
            # 앞 실행이 끝나지 않았으면 이번 tick 은 건너뛴다. 한 워크플로우의 실행이
            # 둘 동시에 뜨지 않는다
            max_instances=1,
            # 프로세스가 멈춰 tick 을 여러 번 놓쳤어도 밀린 만큼 몰아서 돌지 않는다
            coalesce=True,
            replace_existing=True,
        )


def _interval_minutes(job: object) -> int:
    """`IntervalTrigger` 의 주기를 분으로 읽는다."""
    trigger = getattr(job, "trigger", None)
    interval = getattr(trigger, "interval", None)
    if interval is None:
        return 0
    return int(interval.total_seconds() // 60)


def _log_skipped_tick(event: JobExecutionEvent) -> None:
    """앞 실행이 아직 돌고 있어 건너뛴 tick. 건너뛴 사실은 반드시 남는다."""
    workflow_id = workflow_id_of(event.job_id)
    if workflow_id is None:
        return
    logger.warning(
        "workflow %s: 앞 실행이 끝나지 않아 이번 tick 을 건너뛴다 (scheduled_at=%s)",
        workflow_id,
        event.scheduled_run_time,
    )


_scheduler: WorkflowScheduler | None = None


def get_scheduler() -> WorkflowScheduler:
    """앱이 쓰는 인스턴스 하나."""
    global _scheduler
    if _scheduler is None:
        _scheduler = WorkflowScheduler()
    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown()
        _scheduler = None
