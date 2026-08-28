"""완성 공고 화면. 정규화·분류가 열여섯 칸 중 80% 이상을 채운 공고만 보여준다.

운영자가 "분류까지 다 끝나서 데이터가 거의 빠짐없는 것" 만 훑어보고 싶을 때 쓰는 자리다.
검수 화면(`/review`)은 무엇을 고칠지 찾는 화면이고, 여기는 반대로 이미 채워진 것만 골라
보여준다 — 고치는 기능은 없다.

## "완성" 은 열여섯 칸 중 80% 이상(열세 칸 이상)이 채워졌다는 뜻이다

`app/normalize/rules.py` 의 `NORMALIZED_FIELDS` 열여섯 칸(수집이 채우는 것, 분류가 채우는
것, 직무 분류 둘 포함) 중 값이 있는 칸 수를 세어 임계치(`_THRESHOLD`) 이상이면 완성으로
본다. 사이트에 따라 `preferred`·`hiring_process`·`etc_info` 처럼 빈 것이 정상인 칸이
있어서(`app/api/review_filter.py` 의 `EMPTY_NOTES`) 열여섯 칸 전부를 요구하면 통과하는
건이 지나치게 적어진다 — 2026-08-29 운영자 요청으로 100% 에서 80% 로 낮췄다.

사람이 고친 값(`job_field_overrides`)은 여기서 보지 않는다. 목록은 `normalized_jobs` 원
컬럼만 본다 — 상세를 열면(검수 모달을 그대로 재사용한다) 보정이 반영된 값이 보인다. 목록
단계에서 보정까지 적용하면 조회 하나가 두 표를 조인해야 해서 화면이 무거워지고, 완성
여부를 가르는 화면에서 그 정밀도 차이는 실익이 적다.

## 목록은 커서로, 상세는 검수 모달을 그대로 쓴다

무한스크롤이라 오프셋이 아니라 `id` 커서를 쓴다 — 스크롤 중 새 공고가 쌓여도 이미 본 행이
밀리거나 중복되지 않는다. 상세는 새로 만들지 않는다. `GET /ui/review/modal/{raw_job_id}`
가 이미 공고 한 건을 통째로 보여주고 `app-modal` 틀도 이미 있다(`app/templates/base.html`).
"""

from __future__ import annotations

import math
import sqlite3
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


def _rows(conn: sqlite3.Connection, after: int | None) -> list[sqlite3.Row]:
    params: list[object] = []
    where = _COMPLETE_WHERE
    if after is not None:
        where += " AND id < ?"
        params.append(after)
    params.append(PAGE_SIZE)
    return conn.execute(
        f"""
        SELECT id, raw_job_id, parent_company, company, title, job_role, job_major,
               job_minor, employment_type, career_level, work_location, source_url
          FROM normalized_jobs
         WHERE {where}
         ORDER BY id DESC
         LIMIT ?
        """,
        params,
    ).fetchall()


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
    next_after = int(rows[-1]["id"]) if len(rows) == PAGE_SIZE else None
    return render(
        request,
        "fragments/complete_list.html",
        rows=rows,
        next_after=next_after,
        is_first_page=after is None,
    )
