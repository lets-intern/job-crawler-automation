"""완성 공고 화면. 정규화·분류가 열여섯 칸 중 80% 이상을 채운 공고만 보여준다.

운영자가 "분류까지 다 끝나서 데이터가 거의 빠짐없는 것" 만, 소비 측(잡보드)에 나갈 모양
그대로 미리 훑어보고 싶을 때 쓰는 자리다. 검수 화면(`/review`)은 무엇을 고칠지 찾는
화면이고, 여기는 고치는 기능이 없다 — 로고까지 붙여 실제로 어떻게 보일지 확인만 한다.

## "완성" 은 열여섯 칸 중 80% 이상(열세 칸 이상)이 채워졌다는 뜻이다

`app/normalize/rules.py` 의 `NORMALIZED_FIELDS` 열여섯 칸(수집이 채우는 것, 분류가 채우는
것, 직무 분류 둘 포함) 중 값이 있는 칸 수를 세어 임계치(`_THRESHOLD`) 이상이면 완성으로
본다. 사이트에 따라 `preferred`·`hiring_process`·`etc_info` 처럼 빈 것이 정상인 칸이
있어서(`app/api/review_filter.py` 의 `EMPTY_NOTES`) 열여섯 칸 전부를 요구하면 통과하는
건이 지나치게 적어진다 — 2026-08-29 운영자 요청으로 100% 에서 80% 로 낮췄다.

사람이 고친 값(`job_field_overrides`)은 여기서 보지 않는다. 목록·상세 모두
`normalized_jobs` 원 컬럼만 본다 — 검수해서 고친 값을 보려면 `/review`로 간다.

## 로고는 이름으로 잇는다

`companies.name` 은 자회사가 있으면 자회사, 없으면 모회사다(`app/companies.py::register`).
그래서 `COALESCE(NULLIF(company,''), parent_company)` 로 이어야 로고가 실제로 붙는 경로와
같아진다.

## 목록은 커서로, 상세는 이 화면 전용 읽기 전용 미리보기다

무한스크롤이라 오프셋이 아니라 `id` 커서를 쓴다 — 스크롤 중 새 공고가 쌓여도 이미 본 행이
밀리거나 중복되지 않는다. 상세(`GET /ui/complete/{id}/preview`)는 검수 모달을 재사용하지
않는다 — 이 화면은 고치는 기능이 필요 없고, 소비 측 화면처럼 섹션으로 나눠 읽기 좋게 보여
주는 것이 목적이라 모양 자체가 다르다.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from app.api.settings import get_connection
from app.api.ui import render, render_page
from app.normalize.rules import NORMALIZED_FIELDS

router = APIRouter(tags=["ui"], include_in_schema=False)

# 한 번에 불러오는 건수. 너무 크면 스크롤 한 번에 다 오고, 너무 작으면 요청이 잦다
PAGE_SIZE = 20

# 완성으로 볼 최소 채움 비율. 100% 는 사이트별로 정상적으로 비는 칸 때문에 통과하는 건이
# 거의 없어서 낮췄다(2026-08-29)
_THRESHOLD = 0.8
_REQUIRED_FILLED = math.ceil(len(NORMALIZED_FIELDS) * _THRESHOLD)

# 채워진 칸 수를 세는 SQL 조각. 열여섯 칸 중 이 값이 _REQUIRED_FILLED 이상이면 완성이다
_FILLED_COUNT_SQL = " + ".join(
    f"(CASE WHEN {name} IS NOT NULL AND trim({name}) != '' THEN 1 ELSE 0 END)"
    for name in NORMALIZED_FIELDS
)
_COMPLETE_WHERE = f"({_FILLED_COUNT_SQL}) >= {_REQUIRED_FILLED}"

# 로고를 잇는 이름. companies.name 과 같은 규칙이어야 로고가 실제로 붙는 것과 같은 회사를
# 가리킨다(app/companies.py::register)
_COMPANY_NAME_SQL = "COALESCE(NULLIF(n.company, ''), n.parent_company)"


def _d_day(deadline: str | None) -> str | None:
    """마감까지 며칠인지. 못 읽으면(형식이 다르거나 없으면) None 이다."""
    if not deadline:
        return None
    try:
        target = date.fromisoformat(deadline.strip()[:10])
    except ValueError:
        return None
    delta = (target - date.today()).days
    if delta < 0:
        return "마감"
    if delta == 0:
        return "D-DAY"
    return f"D-{delta}"


def _rows(conn: sqlite3.Connection, after: int | None) -> list[sqlite3.Row]:
    params: list[object] = []
    where = _COMPLETE_WHERE
    if after is not None:
        where += " AND n.id < ?"
        params.append(after)
    params.append(PAGE_SIZE)
    return conn.execute(
        f"""
        SELECT n.id, n.raw_job_id, n.parent_company, n.company, n.title, n.job_role,
               n.job_major, n.job_minor, n.employment_type, n.career_level,
               n.work_location, n.deadline, n.source_url, c.logo_url
          FROM normalized_jobs n
          LEFT JOIN companies c ON c.name = {_COMPANY_NAME_SQL}
         WHERE {where}
         ORDER BY n.id DESC
         LIMIT ?
        """,
        params,
    ).fetchall()


def _read_detail(conn: sqlite3.Connection, normalized_id: int) -> sqlite3.Row | None:
    return conn.execute(
        f"""
        SELECT n.*, c.logo_url
          FROM normalized_jobs n
          LEFT JOIN companies c ON c.name = {_COMPANY_NAME_SQL}
         WHERE n.id = ?
        """,
        (normalized_id,),
    ).fetchone()


@router.get("/complete", response_class=HTMLResponse)
def complete_page(request: Request) -> HTMLResponse:
    return render_page(request, "pages/complete.html")


@router.get("/ui/complete", response_class=HTMLResponse)
def complete_list_fragment(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    after: Annotated[int | None, Query()] = None,
) -> HTMLResponse:
    """공고 한 묶음. 마지막 행에 다음 묶음을 불러오는 감지기가 붙는다.

    더 가져올 것이 없으면 감지기를 붙이지 않는다 — 붙이면 스크롤이 바닥에 닿을 때마다
    같은 빈 요청을 반복한다.
    """
    rows = _rows(conn, after)
    cards = [{"row": row, "d_day": _d_day(row["deadline"])} for row in rows]
    next_after = int(rows[-1]["id"]) if len(rows) == PAGE_SIZE else None
    return render(
        request,
        "fragments/complete_list.html",
        cards=cards,
        next_after=next_after,
        is_first_page=after is None,
    )


@router.get("/ui/complete/{normalized_id}/preview", response_class=HTMLResponse)
def complete_preview_fragment(
    request: Request,
    normalized_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
) -> HTMLResponse:
    """공고 한 건을 소비 측이 볼 모양대로 읽기 전용으로 보여준다. 고치는 자리가 없다."""
    row = _read_detail(conn, normalized_id)
    if row is None:
        # 다른 `/ui/*` 실패와 같은 규칙이다 — 조각은 200으로 돌아오고 안에 사유를 적는다.
        # HTMX 스왑은 상태 코드가 아니라 본문을 그대로 자리에 끼운다
        return render(request, "fragments/complete_not_found.html", normalized_id=normalized_id)
    return render(
        request,
        "fragments/complete_preview.html",
        job=row,
        d_day=_d_day(row["deadline"]),
    )
