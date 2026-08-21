"""크롤러 등록·셀렉터 편집 화면의 조각 라우트.

`app/api/crawlers.py` 를 그대로 부른다. 화면에서만 되는 등록 경로를 따로 만들지 않는다.

생성된 셀렉터는 가설이다. 실패한 필드가 있어도 행은 남고, 화면은 어느 필드가 몇 개 매칭됐는지
그대로 보여준다. 그 다음은 운영자가 손으로 고치는 것이지 다시 생성하는 것이 아니다
(`.claude/rules/llm.md`).

## 실패를 200 으로 돌려주는 이유

HTMX 는 4xx 응답을 기본적으로 갈아 끼우지 않는다. 조각 라우트가 422 를 돌려주면 화면에는
아무 일도 일어나지 않고, 운영자는 저장이 됐는지 안 됐는지 알 수 없다. 그래서 조각은 거절
사유를 담은 HTML 을 200 으로 돌려주고, 사유와 메시지를 화면에 그대로 적는다. 상태 코드로
실패를 알려야 하는 쪽은 `/api/...` 이고 그 라우터는 그대로다.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.api import crawlers
from app.api.ui import render

_LIST_QUERY = (
    "SELECT id, name, status, list_url, detail_url, default_company, render_mode "
    "FROM crawlers ORDER BY id DESC"
)

router = APIRouter(tags=["ui"], include_in_schema=False)


def error_detail(exc: HTTPException) -> dict[str, str]:
    """HTTPException 의 detail 을 화면이 읽는 모양으로 옮긴다."""
    detail = exc.detail
    if isinstance(detail, dict):
        return {
            "reason": str(detail.get("reason", exc.status_code)),
            "message": str(detail.get("message", detail)),
        }
    return {"reason": str(exc.status_code), "message": str(detail)}


def crawler_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """등록된 크롤러 전부. 테스트 실행 화면도 같은 목록을 쓴다."""
    return list(conn.execute(_LIST_QUERY).fetchall())


def _pretty(selectors_json: str) -> str:
    """저장된 JSON 을 사람이 고칠 수 있게 편다. 못 읽는 값은 그대로 보여준다."""
    try:
        return json.dumps(json.loads(selectors_json), ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return selectors_json


def _result(
    request: Request,
    *,
    conn: sqlite3.Connection | None = None,
    crawler_id: int | None = None,
    status: str = "",
    selectors_json: str = "",
    notice: str = "",
    error: dict[str, str] | None = None,
    generation: dict[str, Any] | None = None,
) -> HTMLResponse:
    """결과 영역 하나를 렌더한다. `conn` 을 주면 크롤러 목록도 함께 갱신한다(OOB)."""
    return render(
        request,
        "fragments/crawler_result.html",
        crawler_id=crawler_id,
        status=status,
        selectors_json=selectors_json,
        notice=notice,
        error=error,
        generation=generation,
        crawlers=crawler_rows(conn) if conn is not None else None,
    )


def _created_notice(created: crawlers.CrawlerOut) -> str:
    notice = f"크롤러 {created.id}({created.name}) 를 등록했다."
    if created.default_company:
        return f"{notice} 회사명 {created.default_company} 를 함께 저장했다."
    return notice


@router.get("/ui/crawlers", response_class=HTMLResponse)
def crawler_list_fragment(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(crawlers.get_connection)],
) -> HTMLResponse:
    """등록된 크롤러 표. 페이지가 로드될 때와 등록 직후에 갈린다."""
    return render(request, "fragments/crawler_list.html", crawlers=crawler_rows(conn))


@router.post("/ui/crawlers", response_class=HTMLResponse)
async def create_crawler_fragment(
    request: Request,
    list_url: Annotated[str, Form()],
    detail_url: Annotated[str, Form()],
    conn: Annotated[sqlite3.Connection, Depends(crawlers.get_connection)],
    generate: Annotated[crawlers.GenerateFn, Depends(crawlers.get_generator)],
    name: Annotated[str, Form()] = "",
    default_company: Annotated[str, Form()] = "",
    render_mode: Annotated[str, Form()] = crawlers.DEFAULT_RENDER_MODE,
) -> HTMLResponse:
    """생성 요청. 성공하면 결과 요약과 편집기가, 실패하면 사유가 결과 영역에 들어간다.

    `default_company` 는 선택이다. 비워 두면 회사명은 공고에서 뽑은 값만 쓰인다.

    `render_mode` 는 기본이 정적이다. 셀렉터도 고른 모드로 가져온 HTML 에서 뽑는다 — JS 로
    그려지는 사이트는 정적 HTML 에 목록 자체가 없어서, 정적으로 생성한 셀렉터는 처음부터
    맞을 수가 없다. 어느 쪽이 필요한지는 테스트 실행 화면에서 두 모드를 비교해 정한다.
    """
    payload = crawlers.CrawlerCreate(
        list_url=list_url,
        detail_url=detail_url,
        name=name,
        default_company=default_company,
        render_mode=render_mode,
    )
    try:
        created = await crawlers.create_crawler(payload, conn, generate)
    except HTTPException as exc:
        return _result(request, error=error_detail(exc))

    return _result(
        request,
        conn=conn,
        crawler_id=created.id,
        status=created.status,
        selectors_json=json.dumps(created.selectors.model_dump(), ensure_ascii=False, indent=2),
        notice=_created_notice(created),
        generation={
            "matches": created.matches,
            "failed_fields": created.failed_fields,
            "notes": created.notes,
            "usage": created.usage,
        },
    )


@router.put("/ui/crawlers/{crawler_id}/render-mode", response_class=HTMLResponse)
def switch_render_mode_fragment(
    request: Request,
    crawler_id: int,
    render_mode: Annotated[str, Form()],
    conn: Annotated[sqlite3.Connection, Depends(crawlers.get_connection)],
) -> HTMLResponse:
    """정적과 렌더 사이를 옮긴다. 표의 버튼 하나가 이 경로를 부른다.

    셀렉터는 그대로 둔다. 렌더된 DOM 이 정적 HTML 과 다를 수 있어서, 올린 뒤에는 테스트
    실행으로 다시 확인해야 한다.
    """
    try:
        saved = crawlers.update_render_mode(
            crawler_id, crawlers.RenderModeUpdate(render_mode=render_mode), conn
        )
    except HTTPException as exc:
        return _result(request, error=error_detail(exc))

    return _result(
        request,
        conn=conn,
        notice=(
            f"크롤러 {saved.id} 를 {saved.render_mode} 모드로 바꿨다. "
            "셀렉터가 그 모드에서도 맞는지 테스트 실행으로 확인한다."
        ),
    )


@router.get("/ui/crawlers/{crawler_id}/editor", response_class=HTMLResponse)
def selector_editor_fragment(
    request: Request,
    crawler_id: int,
    conn: Annotated[sqlite3.Connection, Depends(crawlers.get_connection)],
) -> HTMLResponse:
    """저장된 셀렉터를 편집기에 그대로 올린다. 여는 것만으로 다시 생성하지 않는다."""
    row = conn.execute(
        "SELECT id, status, selectors_json FROM crawlers WHERE id = ?", (crawler_id,)
    ).fetchone()
    if row is None:
        return _result(
            request,
            error={"reason": "not_found", "message": f"크롤러 {crawler_id} 가 없다"},
        )
    return _result(
        request,
        crawler_id=int(row["id"]),
        status=str(row["status"]),
        selectors_json=_pretty(row["selectors_json"] or ""),
    )


@router.put("/ui/crawlers/{crawler_id}/selectors", response_class=HTMLResponse)
def save_selectors_fragment(
    request: Request,
    crawler_id: int,
    selectors_json: Annotated[str, Form()],
    conn: Annotated[sqlite3.Connection, Depends(crawlers.get_connection)],
) -> HTMLResponse:
    """손으로 고친 셀렉터를 그대로 저장한다. 거절되면 고친 내용을 편집기에 그대로 남긴다."""
    try:
        payload = json.loads(selectors_json)
    except json.JSONDecodeError as exc:
        return _result(
            request,
            crawler_id=crawler_id,
            selectors_json=selectors_json,
            error={"reason": "unparsable", "message": f"JSON 으로 읽을 수 없다: {exc}"},
        )

    try:
        saved = crawlers.update_selectors(crawler_id, payload, conn)
    except HTTPException as exc:
        return _result(
            request,
            crawler_id=crawler_id,
            selectors_json=selectors_json,
            error=error_detail(exc),
        )

    return _result(
        request,
        conn=conn,
        crawler_id=saved.id,
        status=saved.status,
        selectors_json=json.dumps(saved.selectors.model_dump(), ensure_ascii=False, indent=2),
        notice=f"크롤러 {saved.id} 의 셀렉터를 저장했다.",
    )
