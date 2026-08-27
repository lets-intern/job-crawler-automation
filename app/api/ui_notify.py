"""알림 설정 화면의 조각 라우트.

값 검증은 `app/notify/settings.py` 가 하고 화면은 거절 사유를 그대로 옮긴다. 화면에서만
통과하는 값이 생기면 어느 쪽이 진실인지 알 수 없게 된다 (`app/api/ui_settings.py` 와 같은
규칙이다).

주소를 `/ui/settings/...` 아래 두지 않는다. `app/api/ui_settings.py` 에 이미
`PUT /ui/settings/{key}` 가 있어서, 같은 자리에 두면 `PUT /ui/settings/notify` 가 키 이름이
`notify` 인 정수 설정으로 먼저 잡힌다. 등록 순서로 푸는 것은 라우터 등록 줄을 옮기는 순간
조용히 깨진다.

**테스트 전송은 저장된 설정으로 보낸다.** 폼에 적힌 값이 아니라 실행이 실제로 쓰게 될 값이라야
확인이 뜻을 갖는다. 그래서 순서는 저장하고 나서 보내기다.

켜기·끄기와 상관없이 보낸다. 켜기 전에 주소가 맞는지 확인하는 것이 이 단추의 쓸모다.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from app.api.settings import get_connection
from app.api.ui import render
from app.notify import settings as store
from app.notify.message import build_test_message
from app.notify.ntfy import PRIORITIES, SendResult, send

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ui"], include_in_schema=False)


def _form(
    request: Request,
    conn: sqlite3.Connection,
    *,
    message: str = "",
    error: dict[str, str] | None = None,
    sent: SendResult | None = None,
) -> HTMLResponse:
    """알림 설정 폼 하나. 저장 결과도 테스트 전송 결과도 이 조각으로 돌아온다."""
    return render(
        request,
        "fragments/notify_form.html",
        config=store.read_config(conn),
        priorities=PRIORITIES,
        message=message,
        error=error,
        sent=sent,
        sent_at=datetime.now(UTC) if sent is not None else None,
    )


@router.get("/ui/notify", response_class=HTMLResponse)
def notify_form_fragment(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
) -> HTMLResponse:
    """저장된 설정. 아직 저장한 적이 없으면 기본값이 그려진다."""
    return _form(request, conn)


@router.put("/ui/notify", response_class=HTMLResponse)
def update_notify_fragment(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    server_url: Annotated[str, Form()] = "",
    topic: Annotated[str, Form()] = "",
    priority: Annotated[str, Form()] = store.DEFAULT_PRIORITY,
    min_new_count: Annotated[str, Form()] = "",
    click_base: Annotated[str, Form()] = "",
    enabled: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """설정 한 벌을 저장한다. 하나라도 거절되면 아무것도 저장되지 않는다.

    체크박스는 꺼져 있으면 폼에 아예 실리지 않는다. 그래서 값이 왔는지로 판정한다.
    """
    try:
        count = int(min_new_count)
    except ValueError:
        return _form(
            request,
            conn,
            error={
                "reason": "invalid_input",
                "message": f"알림 기준 건수가 정수가 아니다: {min_new_count!r}",
            },
        )

    config = store.NotifyConfig(
        enabled=bool(enabled),
        server_url=server_url.strip(),
        topic=topic.strip(),
        priority=priority,
        min_new_count=count,
        click_base=click_base.strip(),
    )
    try:
        saved = store.write_config(conn, config)
    except store.NotifySettingError as exc:
        return _form(request, conn, error={"reason": "invalid_value", "message": str(exc)})

    word = "켜짐" if saved.enabled else "꺼짐"
    return _form(
        request,
        conn,
        message=f"저장했다. 알림은 {word} 이고 새 공고 {saved.min_new_count}건부터 보낸다",
    )


@router.post("/ui/notify/test", response_class=HTMLResponse)
async def test_send_fragment(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
) -> HTMLResponse:
    """저장된 설정으로 알림을 한 번 보내 본다. 실제로 휴대폰에 알림이 간다."""
    config = store.read_config(conn)
    result = await send(config.target, build_test_message(click=config.click_url))
    logger.info("알림 테스트 전송: ok=%s %s", result.ok, result.detail)
    return _form(request, conn, sent=result)
