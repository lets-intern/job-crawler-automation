"""워크플로우 목록 화면의 조각 라우트.

중지·재개와 주기 변경은 `app/api/workflows.py` 의 PATCH 라우트를 그대로 부른다. 그래야 화면에서
바꾼 값도 스케줄러 `sync()` 까지 간다 — 테이블만 고치고 잡을 두면 멈춘 워크플로우가 계속
깨어난다 (`.claude/rules/crawling.md`).

한 번 누르면 그 행 하나만 갈린다. 목록 전체를 다시 그리면 다른 행에서 입력하던 주기 값이 같이
날아간다.

임계치 초과 표시는 자동 중지가 보는 값과 같은 함수(`consecutive_failures`)로 센다. 누적 실패
횟수로 대신하면 성공과 실패가 번갈아 난 워크플로우를 초과로 잘못 표시한다.

## 화면에 무엇을 계산해서 넘기는가

카드가 받는 것은 이미 판정이 끝난 값이다 (`.claude/agents/ui-worker.md`: 계산은 라우트, 렌더는
템플릿). 연속 실패를 세는 것도, 그것을 `주의`/`점검 필요` 어느 단어로 부를지도 여기서 정한다.

실패한 워크플로우는 색과 굵기만으로 구분하지 않는다. `tone` 이 테두리 색을 정하는 동안
`attention` 이 같은 사실을 단어로 들고 간다 — 색을 못 보면 정보가 사라지는 화면을 만들지 않는다
(`.claude/rules/writing.md`).

최근 실행이 실패로 끝났으면 사유(`error_class` 와 `error_message`)를 카드까지 올린다. 어느
셀렉터가 빗나갔는지를 보려고 다른 화면으로 옮겨 다니게 하지 않는다.

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
from dataclasses import dataclass
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

# 임계치가 없는 워크플로우의 연속 실패를 어디까지 거슬러 세는가. 임계치가 있으면 그 값까지만
# 세는 것(자동 중지가 보는 것과 같은 값)과 달리, 여기서는 화면에 적을 숫자를 만들 뿐이라
# 상한이 필요하다. 이 숫자를 넘긴 연속 실패는 "10회 이상" 으로 읽으면 된다
STREAK_LOOKBACK = 10


def get_run_gate() -> RunGate:
    """동시 실행 상한을 지키는 문. 스케줄러가 쓰는 것과 같은 것이다."""
    return get_gate()


@dataclass(frozen=True)
class CardView:
    """워크플로우 카드 하나에 들어가는 값. 판정은 전부 여기 오기 전에 끝나 있다."""

    item: workflows.WorkflowItem
    threshold_state: str
    # "" | "warn" | "bad". 테두리와 배경 색을 정한다
    tone: str
    # 색과 같은 사실을 말하는 단어. 비어 있으면 배지를 붙이지 않는다
    attention: str
    # 최근 실행이 실패로 끝났을 때의 사유 한 줄
    reason: str
    # 운영자가 방금 누른 조작의 결과
    message: str


def _streak(conn: sqlite3.Connection, item: workflows.WorkflowItem) -> int:
    """지금까지 이어진 실패 횟수. 자동 중지가 보는 것과 같은 함수로 센다."""
    limit = int(item.auto_stop_threshold) if item.auto_stop_threshold else STREAK_LOOKBACK
    return consecutive_failures(conn, item.id, limit)


def _threshold_state(item: workflows.WorkflowItem, streak: int) -> str:
    """임계치 대비 지금 어디까지 왔는지. 단어로 적는다."""
    if item.auto_stop_threshold is None:
        # 임계치가 없어도 연속 실패는 센다. 자동으로 멈추지 않는 워크플로우일수록 쌓인 실패가
        # 화면에 보여야 한다
        return "임계치 없음" if streak == 0 else f"임계치 없음 (연속 실패 {streak}회)"
    word = "초과" if streak >= item.auto_stop_threshold else "정상"
    return f"{word} (연속 실패 {streak}회 / 임계치 {item.auto_stop_threshold}회)"


def _attention(item: workflows.WorkflowItem, streak: int) -> tuple[str, str]:
    """이 워크플로우가 눈에 띄어야 하는가. 색과 단어를 함께 정한다."""
    if item.auto_stop_threshold is not None and streak >= item.auto_stop_threshold:
        return "bad", f"임계치 초과 (연속 실패 {streak}회)"
    if streak >= 2:
        return "bad", f"연속 실패 {streak}회"
    if streak == 1:
        return "warn", "최근 실행 실패"
    return "", ""


def _last_failure(conn: sqlite3.Connection, workflow_id: int) -> str:
    """가장 최근에 끝난 실행이 실패였으면 그 사유. 성공으로 끝났으면 빈 문자열이다."""
    row = conn.execute(
        """
        SELECT id, status, error_class, error_message FROM crawl_runs
         WHERE workflow_id = ? AND status IS NOT NULL
         ORDER BY id DESC LIMIT 1
        """,
        (workflow_id,),
    ).fetchone()
    if row is None or row["status"] == SUCCESS:
        return ""
    word = RUN_WORDS.get(row["status"], row["status"])
    reason = row["error_message"] or "사유가 기록되지 않았다"
    return f"실행 {row['id']} {word} / {row['error_class'] or '분류 없음'}: {reason}"


def _view(
    conn: sqlite3.Connection,
    item: workflows.WorkflowItem,
    message: str = "",
) -> CardView:
    streak = _streak(conn, item)
    tone, attention = _attention(item, streak)
    return CardView(
        item=item,
        threshold_state=_threshold_state(item, streak),
        tone=tone,
        attention=attention,
        reason=_last_failure(conn, item.id),
        message=message,
    )


def _card(
    request: Request,
    conn: sqlite3.Connection,
    item: workflows.WorkflowItem,
    message: str = "",
) -> HTMLResponse:
    return render(request, "fragments/workflow_card.html", card=_view(conn, item, message))


def _missing(request: Request, workflow_id: int) -> HTMLResponse:
    """그 워크플로우가 없다. 누른 자리에 사유만 남긴다."""
    return render(
        request,
        "fragments/workflow_card.html",
        card=None,
        notice=f"워크플로우 {workflow_id} 가 없다",
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
    return render(
        request,
        "fragments/workflow_list.html",
        cards=[_view(conn, item) for item in workflows.list_workflows(conn)],
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
        return _missing(request, workflow_id)

    if status and status not in STATUSES:
        return _card(request, conn, current, message=f"알 수 없는 상태다: {status}")
    if not status and not interval_minutes.strip():
        return _card(request, conn, current, message="바꿀 값이 없다")

    try:
        payload = workflows.WorkflowUpdate(
            status=STATUSES.get(status),
            interval_minutes=int(interval_minutes) if interval_minutes.strip() else None,
        )
    except (ValidationError, ValueError):
        # 0, 음수, 정수가 아닌 값. 저장하지 않고 지금 값을 그대로 다시 그린다
        return _card(
            request,
            conn,
            current,
            message=f"주기는 1 이상의 정수여야 한다: {interval_minutes!r}",
        )

    try:
        updated = workflows.update_workflow(workflow_id, payload, conn, scheduler)
    except HTTPException as exc:
        detail = error_detail(exc)
        return _card(request, conn, current, message=detail["message"])

    if payload.status is not None:
        message = "중지했다" if payload.status == "paused" else "재개했다"
    else:
        message = f"주기를 {payload.interval_minutes}분으로 바꿨다"
    return _card(request, conn, updated, message=message)


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
        return _missing(request, workflow_id)

    if workflow_id in _running or _in_flight(conn, workflow_id):
        # 스케줄러의 tick 스킵과 같은 판단이다. 같은 워크플로우의 실행 둘을 동시에 띄우지 않는다
        return _card(
            request,
            conn,
            current,
            message="이미 실행 중이다. 새로 시작하지 않았다. 끝나면 이 줄이 갱신된다",
        )

    if gate.active >= gate.limit():
        return _card(
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
        return _card(request, conn, current, message=_run_message(result))
    return _card(request, conn, updated, message=_run_message(result))
