"""운영 설정 화면의 조각 라우트.

`app/api/settings.py` 를 그대로 부른다. 값 검증은 `app/settings.py` 가 하고, 화면은 거절 사유를
그대로 옮긴다 — 화면에서만 통과하는 값이 생기면 어느 쪽이 진실인지 알 수 없게 된다.

이 화면에 나오는 값은 동시 실행 상한 하나다. 환경변수로 충분한 값을 여기로 옮기면 같은 설정이
두 곳에 생긴다 (`app/settings.py`).
"""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from app import settings as store
from app.api import settings as settings_api
from app.api.ui import render
from app.api.ui_crawlers import error_detail

router = APIRouter(tags=["ui"], include_in_schema=False)


def _form(
    request: Request,
    conn: sqlite3.Connection,
    *,
    message: str = "",
    error: str = "",
) -> HTMLResponse:
    """설정 폼 하나. 저장 결과도 이 조각으로 돌아온다."""
    return render(
        request,
        "fragments/settings_form.html",
        values=settings_api.read_settings(conn),
        key=store.MAX_CONCURRENT_RUNS,
        message=message,
        error=error,
    )


@router.get("/ui/settings", response_class=HTMLResponse)
def settings_form_fragment(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(settings_api.get_connection)],
) -> HTMLResponse:
    """저장된 값. 아직 없는 키는 환경변수 값으로 채워진 뒤 돌아온다."""
    return _form(request, conn)


@router.put("/ui/settings/{key}", response_class=HTMLResponse)
def update_setting_fragment(
    request: Request,
    key: str,
    conn: Annotated[sqlite3.Connection, Depends(settings_api.get_connection)],
    value: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """값을 바꾼다. 거절된 값은 저장되지 않고 저장된 값이 그대로 다시 그려진다."""
    try:
        parsed = int(value)
    except ValueError:
        return _form(request, conn, error=f"정수가 아니다: {value!r}")

    try:
        saved = settings_api.update_setting(key, settings_api.SettingUpdate(value=parsed), conn)
    except HTTPException as exc:
        return _form(request, conn, error=error_detail(exc)["message"])

    return _form(request, conn, message=f"{saved.key} 를 {saved.value} 로 저장했다")
