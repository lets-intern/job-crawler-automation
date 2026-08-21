"""워크플로우 목록 화면의 조각 라우트.

중지·재개와 주기 변경은 `app/api/workflows.py` 의 PATCH 라우트를 그대로 부른다. 그래야 화면에서
바꾼 값도 스케줄러 `sync()` 까지 간다 — 테이블만 고치고 잡을 두면 멈춘 워크플로우가 계속
깨어난다 (`.claude/rules/crawling.md`).

한 번 누르면 그 행 하나만 갈린다. 목록 전체를 다시 그리면 다른 행에서 입력하던 주기 값이 같이
날아간다.

임계치 초과 표시는 자동 중지가 보는 값과 같은 함수(`consecutive_failures`)로 센다. 누적 실패
횟수로 대신하면 성공과 실패가 번갈아 난 워크플로우를 초과로 잘못 표시한다.
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

from app.api import workflows
from app.api.ui import render
from app.api.ui_crawlers import error_detail
from app.crawler.runner import consecutive_failures
from app.scheduler import WorkflowScheduler

router = APIRouter(tags=["ui"], include_in_schema=False)

# 폼에서 온 문자열을 `WorkflowUpdate` 가 받는 값으로 옮긴다. 표에 없는 값은 거절한다
STATUSES: dict[str, Literal["active", "paused"]] = {"active": "active", "paused": "paused"}


def _threshold_state(conn: sqlite3.Connection, item: workflows.WorkflowItem) -> str:
    """임계치 대비 지금 어디까지 왔는지. 단어로 적는다."""
    if item.auto_stop_threshold is None:
        return "임계치 없음"
    streak = consecutive_failures(conn, item.id, int(item.auto_stop_threshold))
    if streak >= item.auto_stop_threshold:
        return f"초과 (연속 실패 {streak}회 / 임계치 {item.auto_stop_threshold}회)"
    return f"정상 (연속 실패 {streak}회 / 임계치 {item.auto_stop_threshold}회)"


def _row(
    request: Request,
    conn: sqlite3.Connection,
    item: workflows.WorkflowItem,
    message: str = "",
) -> HTMLResponse:
    return render(
        request,
        "fragments/workflow_row.html",
        item=item,
        threshold_state=_threshold_state(conn, item),
        message=message,
    )


def _find(conn: sqlite3.Connection, workflow_id: int) -> workflows.WorkflowItem | None:
    for item in workflows.list_workflows(conn):
        if item.id == workflow_id:
            return item
    return None


@router.get("/ui/workflows", response_class=HTMLResponse)
def workflow_table_fragment(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(workflows.get_connection)],
) -> HTMLResponse:
    """목록 전체. 페이지 로드 때 한 번 들어온다."""
    items = workflows.list_workflows(conn)
    return render(
        request,
        "fragments/workflow_table.html",
        rows=[(item, _threshold_state(conn, item)) for item in items],
    )


@router.patch("/ui/workflows/{workflow_id}", response_class=HTMLResponse)
def update_workflow_fragment(
    request: Request,
    workflow_id: int,
    conn: Annotated[sqlite3.Connection, Depends(workflows.get_connection)],
    scheduler: Annotated[WorkflowScheduler, Depends(workflows.get_workflow_scheduler)],
    status: Annotated[str, Form()] = "",
    interval_minutes: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """중지·재개와 주기 변경. 갈리는 것은 이 행 하나다."""
    current = _find(conn, workflow_id)
    if current is None:
        return render(
            request,
            "fragments/workflow_row.html",
            item=None,
            threshold_state="",
            message=f"워크플로우 {workflow_id} 가 없다",
        )

    if status and status not in STATUSES:
        return _row(request, conn, current, message=f"알 수 없는 상태다: {status}")
    if not status and not interval_minutes.strip():
        return _row(request, conn, current, message="바꿀 값이 없다")

    try:
        payload = workflows.WorkflowUpdate(
            status=STATUSES.get(status),
            interval_minutes=int(interval_minutes) if interval_minutes.strip() else None,
        )
    except (ValidationError, ValueError):
        # 0, 음수, 정수가 아닌 값. 저장하지 않고 지금 값을 그대로 다시 그린다
        return _row(
            request,
            conn,
            current,
            message=f"주기는 1 이상의 정수여야 한다: {interval_minutes!r}",
        )

    try:
        updated = workflows.update_workflow(workflow_id, payload, conn, scheduler)
    except HTTPException as exc:
        detail = error_detail(exc)
        return _row(request, conn, current, message=detail["message"])

    if payload.status is not None:
        message = "중지했다" if payload.status == "paused" else "재개했다"
    else:
        message = f"주기를 {payload.interval_minutes}분으로 바꿨다"
    return _row(request, conn, updated, message=message)
