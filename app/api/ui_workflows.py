"""워크플로우 목록 화면의 조각 라우트.

중지·재개와 주기 변경은 `app/api/workflows.py` 의 PATCH 라우트를 그대로 부른다. 그래야 화면에서
바꾼 값도 스케줄러 `sync()` 까지 간다 — 테이블만 고치고 잡을 두면 멈춘 워크플로우가 계속
깨어난다 (`.claude/rules/crawling.md`).

한 번 누르면 그 행 하나만 갈린다. 목록 전체를 다시 그리면 다른 행에서 입력하던 주기 값이 같이
날아간다.

임계치 초과 표시는 자동 중지가 보는 값과 같은 함수(`consecutive_failures`)로 센다. 누적 실패
횟수로 대신하면 성공과 실패가 번갈아 난 워크플로우를 초과로 잘못 표시한다.

승격도 여기 있다. 화면이 부르는 것은 `app/api/workflows.py` 의 `promote()` 그대로다 — 승격
규칙(`tested` 만, 크롤러는 `promoted` 로, 스케줄러 `sync()` 까지)을 화면용으로 다시 쓰지
않는다. 이 라우트가 하는 일은 폼 값을 `WorkflowCreate` 로 옮기고 결과를 실행 대상 표에 다시
그리는 것뿐이다.

승격 결과를 실행 대상 표(`fragments/test_targets.html`)에 그리는 이유는 승격이 눌리는 자리가
거기이기 때문이다. 승격은 `crawlers.status` 를 바꾸므로 그 표는 어차피 다시 그려야 한다.

## 지금 1회 실행

주기 기본값이 360분이라, 승격이 제대로 됐는지 보려면 여섯 시간을 기다려야 한다. 그것을 지금
확인하는 자리다. 실행하는 것은 스케줄러가 부르는 것과 같은 `run_workflow()` 이고, 무엇을
가져올지는 여기서도 테이블이 정한다 — 화면 전용 실행 경로는 만들지 않는다.

스케줄러가 지키는 두 가지를 이 경로도 그대로 지킨다 (`.claude/rules/crawling.md`).

| 지키는 것 | 여기서 어떻게 |
|---|---|
| 한 워크플로우에 실행 둘이 동시에 뜨지 않는다 | 진행 중이면 시작하지 않고 그 사실을 줄에 적는다 |
| 동시 실행 상한 | `RunGate` 로 자리를 얻고, 자리가 없으면 기다리지 않고 건너뛴다 |

상한에 걸렸을 때 기다리지 않는 것은 화면이기 때문이다. 자리가 날 때까지 문 앞에서 기다리면
버튼을 누른 사람은 몇 분 동안 아무 대답도 못 받는다. 스케줄러의 tick 스킵과 같은 판단을 하고,
건너뛴 사실을 그 자리에 적는다.

실행이 끝나면 `sync()` 한다. 연속 실패로 자동 중지된 워크플로우가 테이블에서는 `paused` 인데
잡이 남아 있으면 멈춘 워크플로우가 계속 깨어난다.
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

from app.api import crawlers, workflows
from app.api.ui import render
from app.api.ui_crawlers import crawler_rows, error_detail
from app.api.ui_tests import mode_word
from app.crawler.failures import SUCCESS
from app.crawler.fetcher import FetchPolicy
from app.crawler.runner import RunResult, consecutive_failures, run_workflow
from app.scheduler import RunGate, WorkflowScheduler, get_gate

router = APIRouter(tags=["ui"], include_in_schema=False)

# 폼에서 온 문자열을 `WorkflowUpdate` 가 받는 값으로 옮긴다. 표에 없는 값은 거절한다
STATUSES: dict[str, Literal["active", "paused"]] = {"active": "active", "paused": "paused"}

# 종료 상태를 사람이 읽는 단어로. 저장값은 그대로 영어다 (`.claude/rules/writing.md`)
RUN_WORDS: dict[str, str] = {SUCCESS: "성공", "timeout": "시간 초과", "failed": "실패"}

# 이 프로세스가 지금 화면에서 돌리고 있는 워크플로우. `crawl_runs` 행은 브라우저를 띄우고 나서야
# 생기므로, 그전에 두 번째로 누른 요청을 이것이 막는다
_running: set[int] = set()


def get_run_gate() -> RunGate:
    """동시 실행 상한을 지키는 문. 스케줄러가 쓰는 것과 같은 것이다."""
    return get_gate()


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


def _targets(
    request: Request,
    conn: sqlite3.Connection,
    notice: str,
    *,
    notice_href: str = "",
) -> HTMLResponse:
    """승격을 누른 자리로 돌아간다. 승격은 크롤러 상태를 바꾸므로 표 전체를 다시 그린다."""
    return render(
        request,
        "fragments/test_targets.html",
        crawlers=crawler_rows(conn),
        mode_word=mode_word,
        notice=notice,
        notice_href=notice_href,
    )


def _in_flight(conn: sqlite3.Connection, workflow_id: int) -> bool:
    """아직 끝나지 않은 실행이 있는가. 스케줄러가 돌리는 중인 것도 여기서 보인다."""
    row = conn.execute(
        """
        SELECT 1 FROM crawl_runs
         WHERE workflow_id = ? AND status IS NULL AND finished_at IS NULL
         LIMIT 1
        """,
        (workflow_id,),
    ).fetchone()
    return row is not None


def _run_message(result: RunResult) -> str:
    """실행 하나를 한 줄로. 실패하면 분류와 사유까지 적는다."""
    word = RUN_WORDS.get(result.status, result.status or "알 수 없음")
    line = (
        f"1회 실행 {result.run_id}: {word} — 목록 {result.matched}건, "
        f"정상 {result.success_count}건, 신규 {result.new_count}건, 실패 {result.fail_count}건"
    )
    if result.status == SUCCESS:
        return line
    reason = result.error_message or "사유가 기록되지 않았다"
    return f"{line} / {result.error_class or '분류 없음'}: {reason}"


def _find(conn: sqlite3.Connection, workflow_id: int) -> workflows.WorkflowItem | None:
    for item in workflows.list_workflows(conn):
        if item.id == workflow_id:
            return item
    return None


@router.post("/ui/workflows", response_class=HTMLResponse)
def promote_fragment(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(workflows.get_connection)],
    scheduler: Annotated[WorkflowScheduler, Depends(workflows.get_workflow_scheduler)],
    crawler_id: Annotated[int, Form()],
    name: Annotated[str, Form()] = "",
    interval_minutes: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """테스트를 통과한 크롤러를 워크플로우로 올린다. 판단은 전부 `promote()` 가 한다."""
    try:
        payload = workflows.WorkflowCreate(
            crawler_id=crawler_id,
            name=name,
            # 비우고 보내면 `WorkflowCreate` 의 기본값(360분)이 쓰인다
            **({"interval_minutes": int(interval_minutes)} if interval_minutes.strip() else {}),
        )
    except (ValidationError, ValueError):
        return _targets(request, conn, f"주기는 1 이상의 정수여야 한다: {interval_minutes!r}")

    try:
        created = workflows.promote(payload, conn, scheduler)
    except HTTPException as exc:
        # `tested` 가 아니었거나 크롤러가 사라졌다. 사유를 그대로 옮긴다
        return _targets(request, conn, f"승격하지 못했다: {error_detail(exc)['message']}")

    return _targets(
        request,
        conn,
        (
            f"크롤러 {created.crawler_id} 를 워크플로우 {created.id}({created.name})로 승격했다. "
            f"주기 {created.interval_minutes}분으로 지금부터 돈다"
        ),
        notice_href="/workflows",
    )


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


@router.post("/ui/workflows/{workflow_id}/run", response_class=HTMLResponse)
async def run_now_fragment(
    request: Request,
    workflow_id: int,
    conn: Annotated[sqlite3.Connection, Depends(workflows.get_connection)],
    scheduler: Annotated[WorkflowScheduler, Depends(workflows.get_workflow_scheduler)],
    fetcher: Annotated[FetchPolicy, Depends(crawlers.get_crawl_fetcher)],
    gate: Annotated[RunGate, Depends(get_run_gate)],
) -> HTMLResponse:
    """다음 주기를 기다리지 않고 지금 1회 실행한다. 갈리는 것은 이 워크플로우 하나다.

    실제 사이트를 가져오므로 `RUN_TIMEOUT_SECONDS` 까지 걸릴 수 있다. 그동안 버튼은 잠겨
    있고, 끝나면 최근 실행·최근 결과·누적 카운트가 이 줄과 함께 갱신된다.
    """
    current = _find(conn, workflow_id)
    if current is None:
        return render(
            request,
            "fragments/workflow_row.html",
            item=None,
            threshold_state="",
            message=f"워크플로우 {workflow_id} 가 없다",
        )

    if workflow_id in _running or _in_flight(conn, workflow_id):
        # 스케줄러의 tick 스킵과 같은 판단이다. 같은 워크플로우의 실행 둘을 동시에 띄우지 않는다
        return _row(
            request,
            conn,
            current,
            message="이미 실행 중이다. 새로 시작하지 않았다. 끝나면 이 줄이 갱신된다",
        )

    if gate.active >= gate.limit():
        return _row(
            request,
            conn,
            current,
            message=(
                f"동시 실행 상한({gate.limit()})에 걸렸다. 진행 중 {gate.active}건이 "
                "끝난 뒤 다시 누른다"
            ),
        )

    _running.add(workflow_id)
    try:
        async with gate.slot():
            result = await run_workflow(conn, workflow_id, fetcher=fetcher)
    finally:
        _running.discard(workflow_id)
        # 연속 실패로 자동 중지됐을 수 있다. 그 사실이 잡까지 가야 실제로 멈춘다
        scheduler.sync(conn)

    updated = _find(conn, workflow_id)
    if updated is None:
        return _row(request, conn, current, message=_run_message(result))
    return _row(request, conn, updated, message=_run_message(result))
