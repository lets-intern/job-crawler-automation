"""운영 설정 조회·변경 API.

어드민 화면은 Push 6 이다. 여기까지가 저장소와 API 다.

값 검증은 `app/settings.py` 가 한다. 라우터는 거절 사유를 HTTP 로 옮기기만 한다.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import db, settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingUpdate(BaseModel):
    value: int


class SettingOut(BaseModel):
    key: str
    value: int


def get_connection() -> Iterator[sqlite3.Connection]:
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


@router.get("", response_model=dict[str, int])
def read_settings(conn: Annotated[sqlite3.Connection, Depends(get_connection)]) -> dict[str, int]:
    """현재 값. 아직 저장된 값이 없는 키는 환경변수 값으로 채워진 뒤 돌아온다."""
    return settings.read_all(conn)


@router.put("/{key}", response_model=SettingOut)
def update_setting(
    key: str,
    payload: SettingUpdate,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
) -> SettingOut:
    """값을 바꾼다. 다음에 값을 읽는 쪽부터 새 값을 쓴다 — 재시작하지 않는다."""
    try:
        value = settings.write_int(conn, key, payload.value)
    except settings.UnknownSettingError as exc:
        raise HTTPException(
            status_code=404, detail={"reason": "unknown_key", "message": f"모르는 설정 키다: {key}"}
        ) from exc
    except settings.SettingValueError as exc:
        raise HTTPException(
            status_code=422, detail={"reason": "invalid_value", "message": str(exc)}
        ) from exc
    return SettingOut(key=key, value=value)
