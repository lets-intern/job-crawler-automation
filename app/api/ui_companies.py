"""회사 화면의 조각 라우트.

로고를 회사마다 한 번 넣는 자리다. 잇는 값은 회사명이라, 여기서 넣은 주소 하나가 그 이름을
가진 공고 전부에 붙는다 (`migrations/0020_companies.sql`). 공고마다 로고를 넣는 길은 만들지
않는다 — 그 길이 있으면 한 회사의 로고가 공고 수만큼 갈라진다.

행을 만드는 것은 정규화다 (`app/normalize/engine.py`). 이 화면은 있는 행을 고치기만 한다.
운영자가 회사명을 손으로 치게 두면 오타 하나로 그 로고는 어느 공고에도 붙지 않는다.

## 공고 수는 여기서 센다

`app/companies.py` 는 `companies` 하나만 읽는다. 공고 수는 `normalized_jobs` 를 함께 읽어야
하고, 그 셈이 저장소 모듈에 들어가면 회사 한 행을 고치는 일과 공고를 세는 일이 한 자리에
섞인다. 그래서 세는 SQL 이 이 파일에 있다.

## 기본 정렬이 공고 많은 순이다

이름 순이 아니다. 로고 하나가 몇 건에 붙는지가 무엇을 먼저 등록할지를 정한다. 공고 한
건짜리 회사를 먼저 등록하느라 백 건짜리가 뒤에 서면 이 화면은 일을 늘리기만 한다
(`.claude/tasks/todo/prd-fields-and-logo.md` 4장).

잇는 값이 이름이므로 세는 것도 이름으로 잇는다. 외래키가 없어서가 아니라, 로고가 실제로
붙는 경로가 그것이라 그 경로로 세야 화면의 숫자와 붙는 건수가 같다.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.api.settings import get_connection
from app.api.ui import render

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ui"], include_in_schema=False)


@dataclass(frozen=True)
class CompanyRow:
    """화면이 그리는 회사 한 줄. 저장된 행에 그 이름을 가진 공고 수를 얹은 것이다."""

    name: str
    parent_name: str | None
    logo_url: str | None
    job_count: int


# 공고 많은 순, 같으면 이름 순. `LEFT JOIN` 이라 공고가 하나도 없는 회사도 0건으로 남는다 —
# 빠지면 로고를 지울 회사를 화면에서 찾을 수 없다
_ROWS_SQL = """
SELECT c.name AS name,
       c.parent_name AS parent_name,
       c.logo_url AS logo_url,
       COUNT(j.id) AS job_count
FROM companies c
LEFT JOIN normalized_jobs j ON j.company = c.name
GROUP BY c.id
ORDER BY job_count DESC, c.name
"""


def rows(conn: sqlite3.Connection) -> list[CompanyRow]:
    """회사 전부. 공고 많은 순이다. 읽기 전용이다."""
    return [
        CompanyRow(
            name=str(row["name"]),
            parent_name=None if row["parent_name"] is None else str(row["parent_name"]),
            logo_url=None if row["logo_url"] is None else str(row["logo_url"]),
            job_count=int(row["job_count"]),
        )
        for row in conn.execute(_ROWS_SQL)
    ]


@router.get("/ui/companies", response_class=HTMLResponse)
def company_list_fragment(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
) -> HTMLResponse:
    """회사 목록 한 벌. 행이 없으면 무엇을 하면 생기는지 적는다."""
    return render(request, "fragments/company_list.html", rows=rows(conn))
