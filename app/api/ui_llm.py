"""AI 제공자 설정 화면의 조각 라우트.

값 검증은 `app/llm/settings.py` 가 하고 화면은 거절 사유를 그대로 옮긴다
(`app/api/ui_notify.py` 와 같은 규칙이다).

주소를 `/ui/settings/...` 아래 두지 않는다. 거기에는 이미 `PUT /ui/settings/{key}` 가 있어서
같은 자리에 두면 키 이름이 `llm` 인 정수 설정으로 먼저 잡힌다.

**저장한 키를 화면에 다시 그리지 않는다.** 폼의 입력 칸은 언제나 비어 있고, 저장된 값은
있음·없음과 끝 네 자리로만 나온다. 빈 칸을 저장하면 그 키를 지우고 환경변수로 돌아간다 —
지우는 길이 없으면 잘못 넣은 키를 화면에서 뺄 방법이 없다.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from app.api.settings import get_connection
from app.api.ui import render
from app.llm import providers as registry
from app.llm import settings as store

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ui"], include_in_schema=False)


def _form(
    request: Request,
    conn: sqlite3.Connection,
    *,
    message: str = "",
    error: dict[str, str] | None = None,
) -> HTMLResponse:
    """제공자 설정 폼 하나. 키 저장도 기능 저장도 이 조각으로 돌아온다."""
    return render(
        request,
        "fragments/llm_form.html",
        config=store.read_config(conn),
        provider_names=sorted(registry.PROVIDERS),
        message=message,
        error=error,
    )


@router.get("/ui/llm", response_class=HTMLResponse)
def llm_form_fragment(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
) -> HTMLResponse:
    """저장된 설정. 저장한 적이 없으면 환경변수 값이 그려진다."""
    return _form(request, conn)


@router.get("/ui/llm/models", response_class=HTMLResponse)
async def llm_models_fragment(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    provider: str = "",
    feature: str = "",
    model: str = "",
) -> HTMLResponse:
    """모델 고르는 칸 하나. 제공자를 바꾸면 이 조각만 다시 그린다.

    **목록을 못 받아도 200 이다.** 칸은 손으로 적는 칸으로 나오고 사유만 옆에 적힌다 —
    목록은 편의이지 저장의 조건이 아니다. 키가 없는 제공자를 골라 보는 것도 정상 흐름이다.
    """
    try:
        models, problem = await store.list_models(conn, provider)
    except store.LlmSettingError as exc:
        models, problem = [], str(exc)
    return render(
        request,
        "fragments/llm_models.html",
        feature=feature,
        provider=provider,
        models=models,
        current=model,
        problem=problem,
    )


@router.put("/ui/llm/key/{provider}", response_class=HTMLResponse)
def update_key_fragment(
    request: Request,
    provider: str,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    value: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """제공자 하나의 키를 저장한다. 빈 값이면 지우고 환경변수로 돌아간다.

    로그에도 응답에도 값을 남기지 않는다. 남기는 것은 어느 제공자를 건드렸는지까지다.
    """
    try:
        config = store.write_key(conn, provider, value)
    except store.LlmSettingError as exc:
        return _form(request, conn, error={"reason": "invalid_value", "message": str(exc)})

    view = config.key(provider)
    logger.info("제공자 키를 바꿨다 provider=%s 저장됨=%s", provider, view.stored)
    if not view.stored:
        return _form(request, conn, message=f"{provider} 의 키를 지웠다. 환경변수 값으로 돌아간다")
    tail = f"끝 네 자리는 {view.tail} 다" if view.tail else "네 자리 이하라 끝자리를 가렸다"
    return _form(request, conn, message=f"{provider} 의 키를 저장했다. {tail}")


@router.put("/ui/llm/feature/{feature}", response_class=HTMLResponse)
def update_feature_fragment(
    request: Request,
    feature: str,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    provider: Annotated[str, Form()] = "",
    model: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """기능 하나가 쓸 제공자와 모델을 저장한다. 거절되면 아무것도 저장되지 않는다."""
    try:
        config = store.write_feature(conn, feature, provider, model)
    except store.LlmSettingError as exc:
        return _form(request, conn, error={"reason": "invalid_value", "message": str(exc)})

    view = next(item for item in config.features if item.feature == feature)
    return _form(
        request,
        conn,
        message=(
            f"{view.label}: {view.provider} 의 {view.model} 로 저장했다. 다음 호출부터 이 값을 쓴다"
        ),
    )
