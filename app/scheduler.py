"""APScheduler 등록과 갱신.

`workflows` 테이블이 진실이다. 스케줄러가 들고 있는 잡 목록은 테이블의 사본일 뿐이고, 둘이
어긋나면 테이블 쪽으로 맞춘다 (`.claude/rules/crawling.md`).

그래서 등록도 갱신도 `sync()` 하나로 한다. 기동 시에도, 주기나 상태가 바뀐 뒤에도 같은 함수를
부른다 — "이 워크플로우만 다시 등록" 같은 부분 갱신 경로를 따로 두면 그 경로가 빠뜨린 변경이
스케줄러 메모리에만 남는다.

무엇을 실행할지도 잡이 아니라 테이블이 정한다. 잡에 실려 있는 것은 워크플로우 id 뿐이고,
URL 과 셀렉터는 실행 시점에 `app/crawler/runner.py` 가 다시 읽는다.

동시 실행 상한도 여기 있다. 상한은 `app_settings` 에 저장되고 어드민에서 바뀌므로 고정 크기
세마포어를 쓸 수 없다 — `RunGate` 가 획득할 때마다 현재 값을 다시 읽는다
(`.claude/docs/architecture.md` 의 "동시 실행 상한").
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime

from apscheduler.events import EVENT_JOB_MAX_INSTANCES, JobSubmissionEvent
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app import db, settings
from app.crawler.runner import SCHEDULE, run_workflow

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


class RunGate:
    """동시에 도는 실행 수를 상한 이하로 유지하는 문 하나.

    `asyncio.Semaphore` 가 아닌 이유는 상한이 운영 중에 바뀌기 때문이다. 세마포어는 만들 때
    크기가 정해지므로 값이 바뀔 때마다 다시 만들어야 하고, 그 순간 이미 획득한 실행의 수를
    잃는다.

    상한은 획득하는 시점에 읽는다. 그래서 바뀐 값이 다음 획득부터 적용되고, 이미 돌고 있는
    실행은 상한이 내려가도 끊기지 않는다 — 상한을 줄이는 것은 새 실행을 늦추는 결정이지
    도중에 있는 실행을 버리는 결정이 아니다.
    """

    def __init__(self, limit: Callable[[], int]) -> None:
        self._limit = limit
        self._active = 0
        self._condition = asyncio.Condition()

    @property
    def active(self) -> int:
        return self._active

    def limit(self) -> int:
        return self._limit()

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        async with self._condition:
            # 상한이 올라갔을 수 있다. 기다리던 쪽에 다시 확인할 기회를 준다
            self._condition.notify_all()
            if not self._has_room():
                logger.info(
                    "동시 실행 상한(%s)에 걸려 대기한다. 진행 중=%s", self._limit(), self._active
                )
            await self._condition.wait_for(self._has_room)
            self._active += 1
        try:
            yield
        finally:
            async with self._condition:
                self._active -= 1
                self._condition.notify_all()

    def _has_room(self) -> bool:
        return self._active < self._limit()


def _configured_limit() -> int:
    """현재 상한. `app_settings` 가 진실이고, 값이 없으면 환경변수에서 채워진다."""
    conn = db.connect()
    try:
        return settings.read_int(conn, settings.MAX_CONCURRENT_RUNS)
    finally:
        conn.close()


_gate: RunGate | None = None


def get_gate() -> RunGate:
    """전역 문 하나. 상한은 이것을 모두가 공유할 때만 사실이다."""
    global _gate
    if _gate is None:
        _gate = RunGate(_configured_limit)
    return _gate


class WorkflowScheduler:
    """`workflows` 를 APScheduler 잡으로 옮기는 얇은 층.

    `runner` 는 테스트가 갈아끼운다. 운영에서는 `_execute` 다.
    """

    def __init__(
        self,
        *,
        scheduler: AsyncIOScheduler | None = None,
        runner: RunFn | None = None,
    ) -> None:
        self._scheduler = scheduler or AsyncIOScheduler(timezone="UTC")
        self._runner = runner or self._execute
        self._scheduler.add_listener(_log_skipped_tick, EVENT_JOB_MAX_INSTANCES)

    async def _execute(self, workflow_id: int) -> None:
        """잡 하나의 기본 실행 경로. 상한을 얻은 뒤에 연결을 연다.

        끝나고 다시 `sync()` 한다. 연속 실패로 자동 중지된 워크플로우는 테이블에서 `paused` 가
        되는데, 그 사실이 잡 목록까지 오지 않으면 멈춘 워크플로우가 계속 깨어난다.
        """
        async with get_gate().slot():
            conn = db.connect()
            try:
                await run_workflow(conn, workflow_id, trigger=SCHEDULE)
            finally:
                self.sync(conn)
                conn.close()

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

    def next_run_times(self) -> dict[int, datetime]:
        """등록된 (워크플로우 id -> 다음 실행 예정 시각). 화면이 "언제 도는가" 에 답하는 값이다.

        잡이 없거나 예정 시각이 아직 정해지지 않은 워크플로우는 빠진다. 마지막 실행에 주기를
        더해 대신 계산하지 않는다 — 잡의 tick 은 잡이 등록된 시점부터 세므로 프로세스가 다시
        뜬 뒤에는 그 계산이 틀린다. 모르는 것은 모른다고 적는 편이 틀린 시각보다 낫다.

        기동 전 스케줄러의 잡에는 `next_run_time` 속성 자체가 없다. 그래서 getattr 로 읽는다.
        """
        found: dict[int, datetime] = {}
        for job in self._scheduler.get_jobs():
            workflow_id = workflow_id_of(job.id)
            when = getattr(job, "next_run_time", None)
            if workflow_id is not None and when is not None:
                found[workflow_id] = when
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


def _log_skipped_tick(event: JobSubmissionEvent) -> None:
    """앞 실행이 아직 돌고 있어 건너뛴 tick. 건너뛴 사실은 반드시 남는다.

    `EVENT_JOB_MAX_INSTANCES` 는 실행이 아니라 제출이 막힌 사건이라 `JobSubmissionEvent` 로
    온다. 넘어오는 시각도 하나가 아니라 목록(`scheduled_run_times`)이다.
    """
    workflow_id = workflow_id_of(event.job_id)
    if workflow_id is None:
        return
    logger.warning(
        "workflow %s: 앞 실행이 끝나지 않아 이번 tick 을 건너뛴다 (scheduled_at=%s)",
        workflow_id,
        ", ".join(str(when) for when in event.scheduled_run_times),
    )


_scheduler: WorkflowScheduler | None = None


def get_scheduler() -> WorkflowScheduler:
    """앱이 쓰는 인스턴스 하나."""
    global _scheduler
    if _scheduler is None:
        _scheduler = WorkflowScheduler()
    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler, _gate
    if _scheduler is not None:
        _scheduler.shutdown()
        _scheduler = None
    _gate = None
