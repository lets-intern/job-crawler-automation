"""회사 화면의 조각 라우트.

로고를 회사마다 한 번 넣는 자리다. 잇는 값은 회사명이라, 여기서 넣은 주소 하나가 그 이름을
가진 공고 전부에 붙는다 (`migrations/0020_companies.sql`). 공고마다 로고를 넣는 길은 만들지
않는다 — 그 길이 있으면 한 회사의 로고가 공고 수만큼 갈라진다.

행을 만드는 것은 정규화다 (`app/normalize/engine.py`). 이 화면은 있는 행을 고치기만 한다.
운영자가 회사명을 손으로 치게 두면 오타 하나로 그 로고는 어느 공고에도 붙지 않는다.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app import companies
from app.api.settings import get_connection
from app.api.ui import render

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ui"], include_in_schema=False)


@router.get("/ui/companies", response_class=HTMLResponse)
def company_list_fragment(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
) -> HTMLResponse:
    """회사 목록 한 벌. 행이 없으면 무엇을 하면 생기는지 적는다."""
    return render(request, "fragments/company_list.html", rows=companies.list_all(conn))
