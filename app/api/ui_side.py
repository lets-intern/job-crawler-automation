"""부가 워크플로우 화면의 조각 라우트.

크롤 워크플로우 화면(`app/api/ui_workflows.py`)과 같은 자리이지만 대상이 다르다. 저기는
`workflows`·`crawl_runs` 를, 여기는 `side_workflows`·`side_runs` 를 본다
(`.claude/tasks/todo/prd-side-workflows.md` 1절).

## 저장은 반드시 `scheduler.sync()` 까지 간다

`app/api/workflows.py` 와 같은 이유다. 표만 고치고 스케줄러 잡을 그대로 두면, 주기를
바꿨는데 옛 주기로 계속 돌거나 멈췄는데 계속 깨어나는 워크플로우가 생긴다.

## 카드 하나가 설정이자 폼이다

`app/templates/fragments/workflow_card.html` 이 주기·임계치를 카드 안에 상시 입력칸으로
두는 것과 같다. "고치기 모드" 를 따로 두지 않는다 — 두면 지금 보는 값과 고치는 값이 다른
화면이 되고, 어느 것이 저장된 값인지 헷갈린다.

## `종류` 는 만든 뒤에 못 바꾼다

`app/side/store.py` 의 결정 그대로다. 그래서 카드에는 종류를 바꾸는 입력이 없고, 새로
만들 때만 고른다.

## `all` 확인 창

`target_scope` 로 `all` 을 고르면 저장 전에 대상 건수를 보여주고 다시 눌러야 저장된다
(PRD 2절). 이미 렌더된 같은 폼에 숨은 칸(`confirmed=1`) 하나를 얹어 다시 보내는 것으로
"확인" 을 표현한다 — 새 화면이나 별도 대화상자를 두지 않는다.

`deliver` 종류는 확인을 걸지 않는다. 지금은 실제로 아무것도 보내지 않으므로(Push 7 전까지)
`all` 을 골라도 위험이 없다.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse

from app.api.rules import get_connect_factory, get_connection
from app.api.side import Start, get_start
from app.api.ui import render, render_error
from app.api.workflows import WorkflowScheduler, get_workflow_scheduler
from app.classify.store import ALL, RECENT, scope_count
from app.normalize.backfill import ConnectFactory
from app.side import runs, store

router = APIRouter(tags=["ui"], include_in_schema=False)

# 화면에 적는 낱말. 저장되는 값(store 의 상수)과 갈라 여기 한 곳에 모은다
KIND_LABELS: dict[str, str] = {store.CLASSIFY: "분류", store.DELIVER: "전달"}
STATUS_LABELS: dict[str, str] = {store.ACTIVE: "켜짐", store.PAUSED: "멈춤"}
TRIGGER_LABELS: dict[str, str] = {
    store.INTERVAL: "주기",
    "after_crawl": "수집 직후",
    "manual": "수동",
}
SCOPE_LABELS: dict[str, str] = {
    "unclassified": "아직 분류 안 된 것",
    "empty_fields": "분류는 했지만 빈 칸이 남은 것",
    RECENT: "최근 N일",
    ALL: "전체 다시",
    "undelivered": "아직 전달 안 된 것",
}

# `all` 이 한 건에 쓰는 토큰의 대략치. 640건에 약 285만 토큰이 나간 실측에서 뽑았다
# (`.claude/tasks/todo/prd-side-workflows.md` 2절: "640건이면 약 285만 토큰"). 어림값이고
# 확인 창의 뜻은 "0 이 아니다" 를 보여주는 것이지 정산이 아니다
_TOKENS_PER_JOB_ESTIMATE = 4500

RUN_STATUS_LABELS: dict[str, str] = {
    runs.SUCCESS: "성공",
    runs.FAILED: "실패",
    runs.SKIPPED: "건너뜀",
    runs.TIMEOUT: "시간 초과",
}

# 실행 이력에서 보여줄 최근 건수. 화면 하나가 감당할 길이다
RUN_HISTORY_LIMIT = 10


@dataclass(frozen=True)
class Refusal:
    """받지 않은 값. 사유 문장을 폼 옆에 그대로 적는다."""

    message: str


def _scopes_for(kind: str) -> tuple[str, ...]:
    return store.SCOPES.get(kind, ())


def _form_values(workflow: store.SideWorkflow) -> dict[str, str]:
    """카드의 설정 폼이 기본으로 보여줄 값. 저장된 행 그대로다."""
    return {
        "name": workflow.name,
        "trigger_kind": workflow.trigger_kind,
        "interval_minutes": str(workflow.interval_minutes),
        "target_scope": workflow.target_scope,
        "target_days": "" if workflow.target_days is None else str(workflow.target_days),
        "batch_limit": str(workflow.batch_limit),
    }


def _card_context(
    conn: sqlite3.Connection,
    workflow: store.SideWorkflow,
    *,
    editing_error: Refusal | None = None,
    confirm_all: bool = False,
    pending: dict[str, str] | None = None,
    message: str = "",
) -> dict[str, object]:
    """카드 하나를 그리는 데 필요한 전부. 목록도 폴링도 같은 것을 쓴다.

    `pending` 은 저장 전에 확인을 기다리는 값이다 — 확인 창을 다시 보여줄 때, 방금 고른
    `all` 이 저장된 값 대신 폼에 그대로 남아 있어야 무엇을 확인하는지 헷갈리지 않는다.
    """
    latest = runs.latest(conn, workflow.id)
    open_run = runs.open_run(conn, workflow.id)
    return {
        "workflow": workflow,
        "form_values": pending or _form_values(workflow),
        "kind_label": KIND_LABELS.get(workflow.kind, workflow.kind),
        "status_label": STATUS_LABELS.get(workflow.status, workflow.status),
        "trigger_label": TRIGGER_LABELS.get(workflow.trigger_kind, workflow.trigger_kind),
        "scope_label": SCOPE_LABELS.get(workflow.target_scope, workflow.target_scope),
        "scopes": [(scope, SCOPE_LABELS.get(scope, scope)) for scope in workflow.scopes],
        "trigger_kinds": [(t, TRIGGER_LABELS.get(t, t)) for t in store.TRIGGER_KINDS],
        "running": open_run is not None,
        "latest_run": latest,
        "latest_run_label": (
            None
            if latest is None or latest.status is None
            else RUN_STATUS_LABELS.get(latest.status, latest.status)
        ),
        "history": runs.recent(conn, workflow.id, limit=RUN_HISTORY_LIMIT),
        "run_status_labels": RUN_STATUS_LABELS,
        "error": editing_error,
        "confirm_all": confirm_all,
        "confirm_count": scope_count(conn, ALL)
        if confirm_all and workflow.kind == store.CLASSIFY
        else None,
        "confirm_tokens": (
            scope_count(conn, ALL) * _TOKENS_PER_JOB_ESTIMATE
            if confirm_all and workflow.kind == store.CLASSIFY
            else None
        ),
        "message": message,
    }


def _card(
    request: Request,
    conn: sqlite3.Connection,
    workflow_id: int,
    *,
    editing_error: Refusal | None = None,
    confirm_all: bool = False,
    pending: dict[str, str] | None = None,
    message: str = "",
) -> HTMLResponse:
    workflow = store.read(conn, workflow_id)
    if workflow is None:
        return render_error(request, "not_found", f"부가 워크플로우가 없다: {workflow_id}")
    return render(
        request,
        "fragments/side_card.html",
        card=_card_context(
            conn,
            workflow,
            editing_error=editing_error,
            confirm_all=confirm_all,
            pending=pending,
            message=message,
        ),
    )


def _new_form_context(
    kind: str, *, values: dict[str, str] | None = None, error: Refusal | None = None
) -> dict[str, object]:
    scopes = _scopes_for(kind)
    picked_scope = (values or {}).get("target_scope") or store.default_scope(kind)
    return {
        "kind": kind,
        "kind_label": KIND_LABELS.get(kind, kind),
        "kinds": [(k, KIND_LABELS.get(k, k)) for k in store.KINDS],
        "scopes": [(scope, SCOPE_LABELS.get(scope, scope)) for scope in scopes],
        "trigger_kinds": [(t, TRIGGER_LABELS.get(t, t)) for t in store.TRIGGER_KINDS],
        "picked_scope": picked_scope,
        "values": values or {},
        "default_interval": store.DEFAULT_INTERVAL_MINUTES,
        "default_batch_limit": store.DEFAULT_BATCH_LIMIT,
        "error": error,
    }


def _list_response(
    request: Request,
    conn: sqlite3.Connection,
    *,
    kind: str = store.CLASSIFY,
    values: dict[str, str] | None = None,
    error: Refusal | None = None,
    confirm_all: bool = False,
    confirm_count: int | None = None,
    confirm_tokens: int | None = None,
) -> HTMLResponse:
    """목록 전체 + 만들기 폼. 만들기 폼의 `hx-post` 가 `#side-list` 를 통째로 바꾸므로,
    성공이든 실패든 확인 대기든 **항상 카드 목록과 폼을 함께** 돌려준다. 폼만 돌려주면 지금
    보이던 카드들이 사라진다.
    """
    workflows = store.list_all(conn)
    cards = [_card_context(conn, workflow) for workflow in workflows]
    return render(
        request,
        "fragments/side_list.html",
        cards=cards,
        **_new_form_context(kind, values=values, error=error),
        confirm_all=confirm_all,
        confirm_count=confirm_count,
        confirm_tokens=confirm_tokens,
    )


@router.get("/ui/side", response_class=HTMLResponse)
def side_list_fragment(
    request: Request, conn: Annotated[sqlite3.Connection, Depends(get_connection)]
) -> HTMLResponse:
    """전체 목록. 카드마다 종류·이름·상태·실행 시점·대상 범위·마지막 실행이 있다."""
    return _list_response(request, conn)


@router.get("/ui/side/new-form", response_class=HTMLResponse)
def side_new_form_fragment(
    request: Request,
    kind: Annotated[str, Query()] = store.CLASSIFY,
    name: Annotated[str, Query()] = "",
    trigger_kind: Annotated[str, Query()] = "manual",
    interval_minutes: Annotated[str, Query()] = "",
    target_scope: Annotated[str, Query()] = "",
    target_days: Annotated[str, Query()] = "",
    batch_limit: Annotated[str, Query()] = "",
) -> HTMLResponse:
    """종류나 대상 범위를 바꾸면 폼 전체를 다시 그린다.

    `hx-include="closest form"` 로 지금까지 적은 다른 칸 값도 함께 오므로, 종류만 바뀌고
    이름 같은 값은 사라지지 않는다. `target_scope` 가 새 종류에서 받는 값이 아니면 그 종류의
    기본값으로 되돌린다 — 분류로 골라 둔 범위를 든 채 전달로 바꾸면 저장할 수 없는 값이
    남는다.
    """
    picked = kind if kind in store.KINDS else store.CLASSIFY
    scope = target_scope if target_scope in _scopes_for(picked) else ""
    values = {
        "name": name,
        "trigger_kind": trigger_kind,
        "interval_minutes": interval_minutes,
        "target_scope": scope,
        "target_days": target_days,
        "batch_limit": batch_limit,
    }
    return render(
        request, "fragments/side_new_form.html", **_new_form_context(picked, values=values)
    )


@router.post("/ui/side", response_class=HTMLResponse)
def create_side_workflow_fragment(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    scheduler: Annotated[WorkflowScheduler, Depends(get_workflow_scheduler)],
    kind: Annotated[str, Form()],
    name: Annotated[str, Form()],
    trigger_kind: Annotated[str, Form()] = "manual",
    interval_minutes: Annotated[int, Form()] = store.DEFAULT_INTERVAL_MINUTES,
    target_scope: Annotated[str, Form()] = "",
    target_days: Annotated[str, Form()] = "",
    batch_limit: Annotated[int, Form()] = store.DEFAULT_BATCH_LIMIT,
    confirmed: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """새 부가 워크플로우. 멈춘 채로 만들어진다.

    `target_scope` 가 `all` 이고 `confirmed` 가 없으면 저장하지 않고 대상 건수를 보여주는
    같은 폼을 다시 돌려준다.
    """
    days = int(target_days) if target_days.strip().isdigit() else None
    values = {
        "kind": kind,
        "name": name,
        "trigger_kind": trigger_kind,
        "interval_minutes": str(interval_minutes),
        "target_scope": target_scope,
        "target_days": target_days,
        "batch_limit": str(batch_limit),
    }
    if target_scope == ALL and kind == store.CLASSIFY and not confirmed:
        count = scope_count(conn, ALL)
        return _list_response(
            request,
            conn,
            kind=kind,
            values=values,
            confirm_all=True,
            confirm_count=count,
            confirm_tokens=count * _TOKENS_PER_JOB_ESTIMATE,
        )
    try:
        store.create(
            conn,
            kind=kind,
            name=name,
            trigger_kind=trigger_kind,
            interval_minutes=interval_minutes,
            target_scope=target_scope or None,
            target_days=days,
            batch_limit=batch_limit,
        )
    except store.SideWorkflowError as exc:
        return _list_response(request, conn, kind=kind, values=values, error=Refusal(str(exc)))
    scheduler.sync(conn)
    return _list_response(request, conn)


@router.get("/ui/side/{side_workflow_id}/card", response_class=HTMLResponse)
def side_card_fragment(
    request: Request,
    side_workflow_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
) -> HTMLResponse:
    """카드 하나. 도는 동안 이 자리를 폴링한다."""
    return _card(request, conn, side_workflow_id)


@router.patch("/ui/side/{side_workflow_id}", response_class=HTMLResponse)
def update_side_workflow_fragment(
    request: Request,
    side_workflow_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    scheduler: Annotated[WorkflowScheduler, Depends(get_workflow_scheduler)],
    name: Annotated[str, Form()],
    trigger_kind: Annotated[str, Form()],
    interval_minutes: Annotated[int, Form()],
    target_scope: Annotated[str, Form()],
    target_days: Annotated[str, Form()] = "",
    batch_limit: Annotated[int, Form()] = store.DEFAULT_BATCH_LIMIT,
    confirmed: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """카드에서 고친 값을 저장한다. 상태(켜짐·멈춤)는 이 폼이 건드리지 않는다."""
    existing = store.read(conn, side_workflow_id)
    if existing is None:
        return render_error(request, "not_found", f"부가 워크플로우가 없다: {side_workflow_id}")
    days = int(target_days) if target_days.strip().isdigit() else None
    pending = {
        "name": name,
        "trigger_kind": trigger_kind,
        "interval_minutes": str(interval_minutes),
        "target_scope": target_scope,
        "target_days": target_days,
        "batch_limit": str(batch_limit),
    }
    if target_scope == ALL and existing.kind == store.CLASSIFY and not confirmed:
        return _card(request, conn, side_workflow_id, confirm_all=True, pending=pending)
    try:
        store.update(
            conn,
            side_workflow_id,
            name=name,
            status=existing.status,
            trigger_kind=trigger_kind,
            interval_minutes=interval_minutes,
            target_scope=target_scope,
            target_days=days,
            batch_limit=batch_limit,
        )
    except store.SideWorkflowError as exc:
        return _card(
            request, conn, side_workflow_id, editing_error=Refusal(str(exc)), pending=pending
        )
    scheduler.sync(conn)
    return _card(request, conn, side_workflow_id, message="저장했다")


@router.patch("/ui/side/{side_workflow_id}/status", response_class=HTMLResponse)
def toggle_side_workflow_status_fragment(
    request: Request,
    side_workflow_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    scheduler: Annotated[WorkflowScheduler, Depends(get_workflow_scheduler)],
    status: Annotated[str, Form()],
) -> HTMLResponse:
    """켜짐·멈춤만 바꾼다. 나머지 칸은 지금 값 그대로 다시 보낸다.

    `store.update` 가 부분 갱신을 받지 않으므로(`app/side/store.py`), 여기서 지금 행을 읽어
    나머지 칸을 채운 뒤 전체를 다시 저장한다.
    """
    existing = store.read(conn, side_workflow_id)
    if existing is None:
        return render_error(request, "not_found", f"부가 워크플로우가 없다: {side_workflow_id}")
    try:
        store.update(
            conn,
            side_workflow_id,
            name=existing.name,
            status=status,
            trigger_kind=existing.trigger_kind,
            interval_minutes=existing.interval_minutes,
            target_scope=existing.target_scope,
            target_days=existing.target_days,
            batch_limit=existing.batch_limit,
        )
    except store.SideWorkflowError as exc:
        return _card(request, conn, side_workflow_id, editing_error=Refusal(str(exc)))
    scheduler.sync(conn)
    return _card(request, conn, side_workflow_id)


@router.delete("/ui/side/{side_workflow_id}", response_class=HTMLResponse)
def delete_side_workflow_fragment(
    request: Request,
    side_workflow_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    scheduler: Annotated[WorkflowScheduler, Depends(get_workflow_scheduler)],
) -> HTMLResponse:
    """부가 워크플로우와 그 실행 기록을 지운다. 목록을 다시 그려 돌려준다."""
    try:
        store.delete(conn, side_workflow_id)
    except store.SideWorkflowNotFoundError as exc:
        return render_error(request, "not_found", str(exc))
    scheduler.sync(conn)
    return side_list_fragment(request, conn)


@router.post("/ui/side/{side_workflow_id}/run", response_class=HTMLResponse)
def run_side_workflow_fragment(
    request: Request,
    side_workflow_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    connect: Annotated[ConnectFactory, Depends(get_connect_factory)],
    start: Annotated[Start, Depends(get_start)],
) -> HTMLResponse:
    """지금 한 번 돌린다. 멈춘 워크플로우도 손으로는 돌릴 수 있다 (`app/api/side.py` 와 같은 일).

    이 화면은 `app/api/side.py` 의 실행기를 그대로 부른다. 화면 전용 실행 경로를 만들지
    않는다 — 실제로 무엇을 돌릴지는 `app/side/runner.py` 하나가 정한다.

    `connect` 를 요청 연결(`conn`)로 대신하지 않는다. 일은 자기 연결을 연 스레드가 하고
    요청 연결은 응답과 함께 닫히기 때문이다 (`app/side/runner.py` 의 `start`).

    **`start` 는 함수 안에서 `get_start()` 를 직접 부르지 않고 `Depends` 로 받는다.**
    2026-08-29 이전에는 직접 불렀는데, 그러면 `app.dependency_overrides` 로 갈아끼운 테스트
    더블이 FastAPI 의존성 해석을 거치지 않아 무시되고 실제 `runner.start` 가 그대로 불려
    실제 제공자를 호출했다 — 로컬에 진짜 키가 있으면 느리게라도 성공해 넘어갔지만 CI 에는
    키가 없어 매번 `no_api_key` 로 실패했다(`app/classify/classifier.py::build_client`).
    """
    try:
        start(conn, connect, side_workflow_id, trigger="manual")
    except store.SideWorkflowNotFoundError as exc:
        return render_error(request, "not_found", str(exc))
    return _card(request, conn, side_workflow_id)
