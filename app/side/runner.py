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

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

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
