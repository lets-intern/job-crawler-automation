"""본문 분류를 걸고 진행 상황을 본다.

수집과 따로 도는 동작이다. 운영자가 눌렀을 때만 돌고, 크롤링 실행 기록(`crawl_runs`)에는
아무것도 쓰지 않는다 — 분류는 크롤링이 아니고, 섞어 쓰면 워크플로우의 성공·실패 통계가
크롤링과 무관한 이유로 움직인다.

`limit` 은 한 번에 도는 건수다. 상한을 넘긴 값은 거절하지 않고 상한으로 깎는다. 640건을 한
번에 돌리면 약 285만 토큰이 실제로 나가고, 돌기 시작하면 멈출 수가 없다.

응답은 시작했다는 것까지다. 진행 상황은 같은 경로의 GET 으로 본다. 재정규화와 같은 모양이다
(`app/api/rules.py`).
"""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.rules import get_connect_factory, get_connection
from app.classify.batch import (
    DEFAULT_LIMIT,
    ClassifyProgress,
    ClassifyRun,
    ClassifyRunningError,
    bounded,
    get_classify_run,
    remaining,
)
from app.normalize.backfill import ConnectFactory

router = APIRouter(prefix="/api/classify", tags=["classify"])


class ClassifyOut(BaseModel):
    """분류 진행 상황. 대상·처리·실패 건수와 이번 실행이 쓴 토큰."""

    running: bool
    total: int
    processed: int
    failed: int
    # 모델이 냈지만 본문에서 찾지 못해 버린 칸의 수
    dropped: int
    calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    started_at: str | None
    finished_at: str | None
    errors: list[str]
    # 아직 분류되지 않은 공고 수. 화면이 "몇 건 남았나" 로 읽는다
    pending: int


def _out(progress: ClassifyProgress, pending: int) -> ClassifyOut:
    return ClassifyOut(
        running=progress.running,
        total=progress.total,
        processed=progress.processed,
        failed=progress.failed,
        dropped=progress.dropped,
        calls=progress.calls,
        input_tokens=progress.input_tokens,
        output_tokens=progress.output_tokens,
        total_tokens=progress.total_tokens,
        started_at=progress.started_at,
        finished_at=progress.finished_at,
        errors=progress.errors,
        pending=pending,
    )


@router.post("", response_model=ClassifyOut, status_code=202)
def start_classify(
    run: Annotated[ClassifyRun, Depends(get_classify_run)],
    connect: Annotated[ConnectFactory, Depends(get_connect_factory)],
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    limit: Annotated[int, Query(ge=1)] = DEFAULT_LIMIT,
) -> ClassifyOut:
    """본문이 있고 아직 분류되지 않은 공고를 `limit` 건까지 분류한다."""
    try:
        progress = run.start(connect, bounded(limit))
    except ClassifyRunningError as exc:
        raise HTTPException(
            status_code=409, detail={"reason": "already_running", "message": str(exc)}
        ) from exc
    return _out(progress, remaining(conn))


@router.get("", response_model=ClassifyOut)
def read_classify(
    run: Annotated[ClassifyRun, Depends(get_classify_run)],
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
) -> ClassifyOut:
    """마지막 분류의 진행 상황과 남은 건수. 프로세스가 다시 뜨면 진행 상황은 비어 있다."""
    return _out(run.progress(), remaining(conn))
