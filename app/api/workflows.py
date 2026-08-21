"""워크플로우 승격.

승격은 크롤러를 주기 실행 대상으로 올리는 단계다. `crawlers.status=tested` 인 것만 올라간다 —
테스트를 거치지 않은 셀렉터는 가설일 뿐이고, 가설을 주기 실행에 걸면 실패가 사이트 부하로
쌓인다 (`.claude/rules/llm.md`, `.claude/docs/data-model.md`).

이미 `promoted` 인 크롤러는 다시 승격하지 않는다. 같은 크롤러에 워크플로우가 둘이면 같은
목록 페이지를 두 배로 때린다.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import db

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


class WorkflowCreate(BaseModel):
    """승격 요청. 이름과 주기를 받는다."""

    crawler_id: int
    name: str = ""
    interval_minutes: int = Field(default=360, ge=1)
    # NULL 이면 자동 중지하지 않는다
    auto_stop_threshold: int | None = Field(default=None, ge=1)


class WorkflowOut(BaseModel):
    id: int
    crawler_id: int
    name: str
    interval_minutes: int
    status: str
    auto_stop_threshold: int | None
    crawler_status: str


def get_connection() -> Iterator[sqlite3.Connection]:
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


@router.post("", response_model=WorkflowOut, status_code=201)
def promote(
    payload: WorkflowCreate,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
) -> WorkflowOut:
    """`tested` 크롤러를 워크플로우로 올리고 크롤러를 `promoted` 로 바꾼다."""
    row = conn.execute(
        "SELECT name, status FROM crawlers WHERE id = ?", (payload.crawler_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404, detail={"message": f"크롤러 {payload.crawler_id} 가 없다"}
        )
    if row["status"] != "tested":
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "not_tested",
                "message": (
                    f"승격은 status=tested 인 크롤러만 가능하다. 현재 상태는 {row['status']} 다"
                ),
            },
        )

    name = payload.name.strip() or str(row["name"])
    cursor = conn.execute(
        """
        INSERT INTO workflows (crawler_id, name, interval_minutes, status, auto_stop_threshold)
        VALUES (?, ?, ?, 'active', ?)
        """,
        (payload.crawler_id, name, payload.interval_minutes, payload.auto_stop_threshold),
    )
    conn.execute("UPDATE crawlers SET status = 'promoted' WHERE id = ?", (payload.crawler_id,))

    return WorkflowOut(
        id=int(cursor.lastrowid or 0),
        crawler_id=payload.crawler_id,
        name=name,
        interval_minutes=payload.interval_minutes,
        status="active",
        auto_stop_threshold=payload.auto_stop_threshold,
        crawler_status="promoted",
    )
