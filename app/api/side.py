"""부가 워크플로우를 한 번 돌리고 진행 상황을 본다.

응답은 시작했다는 것까지다. 진행은 `GET /api/side/{id}` 로 본다 — 재정규화와 분류가 이미
그 모양이다 (`app/api/classify.py`, `app/api/rules.py`).

다른 점이 하나 있다. **진행 상황이 메모리가 아니라 `side_runs` 행에 있다.** 분류는 한
프로세스의 메모리에 두어서 서버가 다시 뜨면 언제 얼마나 돌았는지가 통째로 사라지는데,
그것이 이 PRD 가 고치려는 것이다. 여기서는 행을 읽으므로 프로세스가 바뀌어도 답이 같다.

등록·수정·삭제는 여기 없다. 이 Push 의 범위는 실행이고, 설정을 고치는 자리는 화면이다
(Push 5).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.rules import get_connect_factory, get_connection
from app.normalize.backfill import ConnectFactory
from app.side import runner, runs, store

router = APIRouter(prefix="/api/side", tags=["side"])

# 실행을 거는 함수. 테스트가 가짜 제공자를 끼우는 자리다 (`app/api/classify.py` 의
# `get_classify_run` 과 같은 이유)
Start = Callable[..., runs.SideRun]


def get_start() -> Start:
    return runner.start


class SideRunOut(BaseModel):
    """실행 한 건. 도는 동안에는 종료가 비어 있다."""

    id: int
    trigger: str
    started_at: str
    finished_at: str | None
    # `success` / `failed` / `skipped` / `timeout`. 도는 동안에는 비어 있다
    status: str | None
    running: bool
    target_count: int
    processed_count: int
    failed_count: int
    note: str | None
    error_message: str | None


class SideWorkflowOut(BaseModel):
    """부가 워크플로우 하나와 그 마지막 실행. 화면이 진행 상황으로 읽는다."""

    id: int
    kind: str
    name: str
    status: str
    trigger_kind: str
    interval_minutes: int
    target_scope: str
    target_days: int | None
    batch_limit: int
    last_run_at: str | None
    # 지금 돌고 있는가. 마지막 실행이 열려 있으면 참이다
    running: bool
    last_run: SideRunOut | None


def _run_out(run: runs.SideRun) -> SideRunOut:
    return SideRunOut(
        id=run.id,
        trigger=run.trigger,
        started_at=run.started_at,
        finished_at=run.finished_at,
        status=run.status,
        running=run.running,
        target_count=run.target_count,
        processed_count=run.processed_count,
        failed_count=run.failed_count,
        note=run.note,
        error_message=run.error_message,
    )


def _workflow_out(workflow: store.SideWorkflow, last: runs.SideRun | None) -> SideWorkflowOut:
    return SideWorkflowOut(
        id=workflow.id,
        kind=workflow.kind,
        name=workflow.name,
        status=workflow.status,
        trigger_kind=workflow.trigger_kind,
        interval_minutes=workflow.interval_minutes,
        target_scope=workflow.target_scope,
        target_days=workflow.target_days,
        batch_limit=workflow.batch_limit,
        last_run_at=workflow.last_run_at,
        running=last is not None and last.running,
        last_run=None if last is None else _run_out(last),
    )


@router.post("/{side_workflow_id}/run", response_model=SideRunOut, status_code=202)
def start_side_run(
    side_workflow_id: int,
    start: Annotated[Start, Depends(get_start)],
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    connect: Annotated[ConnectFactory, Depends(get_connect_factory)],
) -> SideRunOut:
    """그 부가 워크플로우를 한 번 돌린다. 멈춰 있는 워크플로우도 손으로는 돌릴 수 있다.

    **멈춤은 주기로 돌지 않는다는 뜻이지 못 돌린다는 뜻이 아니다.** 새로 만든 워크플로우는
    멈춘 채로 시작하고, 운영자는 켜기 전에 한 번 돌려 보고 결정한다.

    앞 실행이 아직 돌고 있으면 409 다. 그 차례는 `side_runs` 에 건너뜀으로 남는다 — 응답을
    받은 사람은 알지만 이력은 그것을 모르는 상태를 만들지 않는다.
    """
    try:
        run = start(conn, connect, side_workflow_id, trigger=runner.MANUAL)
    except store.SideWorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if run.status == runs.SKIPPED:
        raise HTTPException(
            status_code=409,
            detail={"reason": "already_running", "message": run.note or "이미 돌고 있다"},
        )
    return _run_out(run)


@router.get("/{side_workflow_id}", response_model=SideWorkflowOut)
def read_side_workflow(
    side_workflow_id: int, conn: Annotated[sqlite3.Connection, Depends(get_connection)]
) -> SideWorkflowOut:
    """설정과 마지막 실행. 도는 동안 이 자리를 폴링해 진행을 본다."""
    workflow = store.read(conn, side_workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"부가 워크플로우가 없다: {side_workflow_id}")
    return _workflow_out(workflow, runs.latest(conn, side_workflow_id))
