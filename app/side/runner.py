"""부가 워크플로우 실행 1회. `side_runs` 행 하나가 실행 하나다.

`app/crawler/runner.py` 와 같은 자리의 모듈이다 — 실행 하나를 열고, 어떤 종료 경로에서도
상태와 카운트로 닫는다. 다른 점은 대상이 사이트가 아니라 이미 수집한 공고라는 것뿐이다.

## 설정은 실행할 때 표에서 다시 읽는다

`side_workflow_id` 만 받고 나머지는 `app/side/store.py` 로 읽는다. 스케줄러 메모리에 들고
있던 값으로 돌면, 화면에서 대상 범위를 좁혀 저장한 뒤에도 다음 실행이 옛 범위로 돈다.
표가 진실이라는 규칙은 크롤 워크플로우와 같다 (`.claude/rules/crawling.md`).

## 종류마다 하는 일이 다르고 기록하는 방식은 하나다

`Body` 는 그 종류가 실제로 하는 일이다. 카운트를 채우고, 실패했으면 사유 한 줄을 돌려준다.
행을 열고 닫는 일은 종류와 무관하게 여기 한 곳에서 한다 — 종류가 늘 때마다 기록을 다시 쓰면
어느 종류는 실패한 실행을 안 남기는 일이 생긴다.

## `runs.recording` 을 쓰지 않는 이유

두 가지가 맞지 않는다.

예외 없이 실패하는 실행이 있다. 제공자 키가 없으면 `app/classify/batch.py` 는 예외를 올리지
않고 진행 상황에 사유를 적고 돌아온다. 그 실행은 `failed` 로 닫히면서 사유가
`error_message` 에 남아야 하는데, `recording` 의 정상 종료 경로는 `error_message` 를 적지
않는다.

그리고 예외를 다시 올린다. 이 함수를 부르는 것은 스케줄러와 API 스레드이고, 거기까지 올라간
예외는 아무도 보지 못한 채 잡을 죽인다. 실행 하나가 실패한 것은 행에 적혀야 할 사실이지
호출자가 처리할 예외가 아니다.

`start`·`finish`·`skipped` 는 그대로 쓴다. `side_runs` 에 쓰는 문장은 그 모듈에만 있다.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.classify.batch import ClassifyProgress, classify_ids
from app.classify.store import scope_ids
from app.config import Settings
from app.side import runs, store
from app.side.runs import FAILED, SUCCESS, SideRun, SideRunCounts

logger = logging.getLogger(__name__)

# 무엇이 이 실행을 깨웠는가. `side_runs.trigger` 의 CHECK 와 같은 셋이다
# (`migrations/0021_side_workflows.sql`). 크롤 실행과 낱말을 맞추되 `test` 는 없다
SCHEDULE = "schedule"
AFTER_CRAWL = "after_crawl"
MANUAL = "manual"

# 그 종류가 실제로 하는 일. 카운트를 채우고, 실패했으면 사유 한 줄을 돌려준다.
#
# 돌려준 사유는 `error_message` 로 들어가고 실행은 `failed` 로 닫힌다. 예외를 던져도 되지만,
# 던지지 않고 실패를 말할 길이 있어야 한다 — 분류는 키가 없어도 예외 없이 돌아온다
Body = Callable[[sqlite3.Connection, store.SideWorkflow, SideRunCounts], str | None]


@dataclass(frozen=True)
class Claim:
    """실행 자리 하나를 잡은 결과. 열린 행이거나, 이미 닫힌 건너뜀 행이다."""

    run_id: int
    workflow: store.SideWorkflow
    # 건너뛴 차례면 False 다. 그때 `run_id` 는 이미 `skipped` 로 닫혀 있다
    started: bool


def claim(conn: sqlite3.Connection, side_workflow_id: int, trigger: str) -> Claim:
    """실행 행을 연다. 워크플로우가 없으면 `SideWorkflowNotFoundError` 다.

    설정을 표에서 다시 읽는 자리가 여기다. 부르는 쪽은 id 만 안다.
    """
    workflow = store.read(conn, side_workflow_id)
    if workflow is None:
        raise store.SideWorkflowNotFoundError(f"부가 워크플로우가 없다: {side_workflow_id}")
    return Claim(run_id=runs.start(conn, workflow.id, trigger), workflow=workflow, started=True)


def run_claimed(
    conn: sqlite3.Connection, workflow: store.SideWorkflow, run_id: int, body: Body
) -> SideRun:
    """열어 둔 행 하나를 채우고 닫는다. 어떤 종료 경로에서도 닫힌다.

    예외는 여기서 끝난다. 사유를 행에 적고 로그에 남기며, 부르는 쪽에는 닫힌 행을 돌려준다.
    `KeyboardInterrupt` 와 종료 신호만은 다시 올린다 — 그것은 이 실행의 실패가 아니라
    프로세스가 내려가는 중이라는 뜻이고, 삼키면 종료가 늦어진다.
    """
    counts = SideRunCounts()
    try:
        reason = body(conn, workflow, counts)
    except Exception as exc:
        logger.exception("부가 워크플로우 %s 실행 %s 가 예외로 끝났다", workflow.id, run_id)
        runs.finish(
            conn, run_id, status=FAILED, counts=counts, error_message=f"{type(exc).__name__}: {exc}"
        )
        return _closed(conn, run_id)
    except BaseException as exc:
        runs.finish(
            conn, run_id, status=FAILED, counts=counts, error_message=f"{type(exc).__name__}: {exc}"
        )
        raise
    runs.finish(
        conn,
        run_id,
        status=FAILED if reason else SUCCESS,
        counts=counts,
        error_message=reason,
    )
    return _closed(conn, run_id)


def run_once(
    conn: sqlite3.Connection, side_workflow_id: int, body: Body, *, trigger: str = MANUAL
) -> SideRun:
    """실행 한 번을 처음부터 끝까지 돈다. 돌아올 때 행은 닫혀 있다."""
    taken = claim(conn, side_workflow_id, trigger)
    if not taken.started:
        return _closed(conn, taken.run_id)
    return run_claimed(conn, taken.workflow, taken.run_id, body)


def _closed(conn: sqlite3.Connection, run_id: int) -> SideRun:
    run = runs.read(conn, run_id)
    if run is None:  # pragma: no cover - 방금 적은 행이 사라지는 경로는 없다
        raise LookupError(f"방금 닫은 실행을 다시 읽지 못했다: {run_id}")
    return run


def run_now(
    conn: sqlite3.Connection,
    side_workflow_id: int,
    *,
    trigger: str = MANUAL,
    client: Any | None = None,
    settings: Settings | None = None,
) -> SideRun:
    """그 워크플로우를 종류에 맞게 한 번 돈다. 돌아올 때 행은 닫혀 있다.

    `client` 와 `settings` 는 테스트가 가짜 제공자를 넣는 자리다. 비워 두면 화면에서 고른
    제공자와 모델을 실행할 때 읽는다 (`app/llm/settings.py`).
    """
    return run_once(conn, side_workflow_id, _body(client, settings), trigger=trigger)


def _body(client: Any | None, settings: Settings | None) -> Body:
    """종류에 맞는 일. 아직 돌릴 수 없는 종류는 사유를 남기고 실패로 닫힌다."""

    def body(
        conn: sqlite3.Connection, workflow: store.SideWorkflow, counts: SideRunCounts
    ) -> str | None:
        if workflow.kind == store.CLASSIFY:
            return _classify(conn, workflow, counts, client=client, settings=settings)
        # 전달은 설정과 화면까지가 이번 범위이고 아무것도 보내지 않는다 (PRD 3절). 조용히
        # 성공으로 닫으면 보낸 적 없는 실행이 성공 이력으로 쌓인다
        return f"{workflow.kind} 종류는 아직 실행할 수 없다. 이 워크플로우는 아무것도 보내지 않는다"

    return body


def _classify(
    conn: sqlite3.Connection,
    workflow: store.SideWorkflow,
    counts: SideRunCounts,
    *,
    client: Any | None,
    settings: Settings | None,
) -> str | None:
    """대상 범위로 공고를 고르고 1회 상한만큼 잘라 분류에 넘긴다.

    **분류 자체는 여기서 하지 않는다.** 무엇을 돌릴지만 고르고 `app/classify/batch.py` 에
    넘긴다. 실행기가 분류를 다시 구현하면 화면에서 부른 분류와 주기로 도는 분류가 서로 다른
    코드가 되고, 한쪽만 고쳐지는 날이 온다.

    `target_days` 는 그대로 넘긴다. `recent` 가 아닌 범위에서는 값이 NULL 이고, 조회가
    그것을 보지 않는다 (`app/classify/store.py`).
    """
    raw_job_ids = scope_ids(
        conn, workflow.target_scope, days=workflow.target_days, limit=workflow.batch_limit
    )
    counts.target_count = len(raw_job_ids)
    if not raw_job_ids:
        # 대상이 없는 것은 실패가 아니다. 다만 아무 일도 없었다는 사실은 적힌다
        counts.note = f"{workflow.target_scope} 범위에 대상이 없다"
        return None

    progress = ClassifyProgress()
    asyncio.run(classify_ids(conn, raw_job_ids, progress, client=client, settings=settings))
    counts.processed_count = progress.processed
    counts.failed_count = progress.failed
    return None
