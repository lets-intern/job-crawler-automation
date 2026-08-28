"""전달 설정 화면의 조각 라우트.

값 검증은 `app/deliver/settings.py` 가 하고 화면은 거절 사유를 그대로 옮긴다
(`app/api/ui_notify.py` 와 같은 규칙).

**테스트 전송 라우트를 두지 않는다.** `app/api/ui_notify.py` 에는 `POST /ui/notify/test` 가
있지만, 저기는 보낼 것이 있고 여기는 없다 — 보내는 코드 자체가 아직 없는데 "테스트 전송"
단추를 달면 눌렀을 때 무엇을 확인했다는 것인지 아무도 설명하지 못한다.

주소를 `/ui/settings/...` 아래 두지 않는 이유는 `app/api/ui_notify.py` 와 같다.
"""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from app.api.settings import get_connection
from app.api.ui import render
from app.deliver import settings as store

router = APIRouter(tags=["ui"], include_in_schema=False)


def _form(
    request: Request,
    conn: sqlite3.Connection,
    *,
    message: str = "",
    error: dict[str, str] | None = None,
) -> HTMLResponse:
    """전달 설정 폼 하나."""
    return render(
        request,
        "fragments/deliver_form.html",
        config=store.read_config(conn),
        methods=store.METHODS,
        message=message,
        error=error,
    )


@router.get("/ui/deliver", response_class=HTMLResponse)
def deliver_form_fragment(
    request: Request, conn: Annotated[sqlite3.Connection, Depends(get_connection)]
) -> HTMLResponse:
    """저장된 설정. 아직 저장한 적이 없으면 기본값이 그려진다."""
    return _form(request, conn)


@router.put("/ui/deliver", response_class=HTMLResponse)
def update_deliver_fragment(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    url: Annotated[str, Form()] = "",
    method: Annotated[str, Form()] = store.DEFAULT_METHOD,
    auth_header: Annotated[str, Form()] = "",
    batch_size: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """설정 한 벌을 저장한다. 하나라도 거절되면 아무것도 저장되지 않는다."""
    try:
        size = int(batch_size)
    except ValueError:
        return _form(
            request,
            conn,
            error={
                "reason": "invalid_input",
                "message": f"1회 전달 건수가 정수가 아니다: {batch_size!r}",
            },
        )

    config = store.DeliverConfig(
        url=url.strip(), method=method, auth_header=auth_header.strip(), batch_size=size
    )
    try:
        saved = store.write_config(conn, config)
    except store.DeliverSettingError as exc:
        return _form(request, conn, error={"reason": "invalid_value", "message": str(exc)})

    word = "설정됐다" if saved.configured else "아직 설정되지 않았다"
    return _form(request, conn, message=f"저장했다. 받는 주소는 {word}")
