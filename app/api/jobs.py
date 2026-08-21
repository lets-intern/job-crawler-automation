"""제공 API. 채용공고 사이트(별도 서비스)가 정규화된 데이터를 가져가는 경계면이다.

응답의 필드·타입·모양은 `.claude/docs/api-contract.md` 가 정한다. 이 파일과 그 문서는 같은
커밋에서 바뀐다 — 어긋나면 소비 측이 조용히 데이터를 못 받는다.

커서 기반이다. 오프셋으로 만들면 폴링 사이에 삽입된 행이 앞 페이지를 밀어내서, 소비 측이
받지 못한 채 지나가는 건이 생긴다. 커서는 `(normalized_at, id)` 한 쌍이고, 정렬도 같은 쌍의
오름차순이다. `normalized_at` 은 초 단위라 같은 값이 여러 행에 걸리므로, `id` 없이는 경계에서
행이 잘리거나 겹친다.

`normalized_at` 의 의미는 건드리지 않는다. 소비 측 폴링 커서가 이 값에 걸려 있다. 저장 형식은
SQLite `datetime('now')` 그대로 두고, 계약이 요구하는 ISO8601 모양은 응답에서만 만든다.
"""

from __future__ import annotations

import base64
import binascii
import json
import sqlite3
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app import db

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

# 계약이 정한 한 번에 가져갈 건수
DEFAULT_LIMIT = 100

_SELECT = """
    SELECT id, company, title, department, deadline, body, requirements,
           source_url, normalized_at
      FROM normalized_jobs
"""


class JobOut(BaseModel):
    """계약의 `items` 한 건. 필드 이름과 순서는 문서를 그대로 따른다."""

    id: int
    company: str | None
    title: str | None
    department: str | None
    deadline: str | None
    body: str | None
    requirements: str | None
    source_url: str
    normalized_at: str


class JobPage(BaseModel):
    items: list[JobOut]
    next_cursor: str | None
    has_more: bool


def get_connection() -> Iterator[sqlite3.Connection]:
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def encode_cursor(normalized_at: str, job_id: int) -> str:
    """커서는 소비 측이 열어 보지 않는 값이다. 그대로 돌려주기만 하면 된다."""
    payload = json.dumps({"t": normalized_at, "i": job_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, int]:
    """망가진 커서는 400 이다. 조용히 처음부터 주면 소비 측이 같은 데이터를 다시 받는다."""
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        return str(payload["t"]), int(payload["i"])
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"reason": "invalid_cursor", "message": "cursor 를 읽을 수 없다"},
        ) from exc


def _iso(stored: str) -> str:
    """저장 형식(`YYYY-MM-DD HH:MM:SS`, UTC)을 계약의 ISO8601 모양으로 옮긴다."""
    text = stored.strip().replace(" ", "T")
    if text.endswith("Z") or "+" in text:
        return text
    return text + "Z"


def _out(row: sqlite3.Row) -> JobOut:
    return JobOut(
        id=int(row["id"]),
        company=row["company"],
        title=row["title"],
        department=row["department"],
        deadline=row["deadline"],
        body=row["body"],
        requirements=row["requirements"],
        source_url=str(row["source_url"]),
        normalized_at=_iso(str(row["normalized_at"])),
    )


@router.get("", response_model=JobPage)
def list_jobs(
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    cursor: Annotated[str | None, Query()] = None,
) -> JobPage:
    """정규화된 공고를 `normalized_at` 오름차순으로 준다.

    `next_cursor` 는 항목이 있으면 항상 돌려준다. 마지막 페이지에서 비워 보내면 소비 측이 읽은
    위치를 잃고, 다음 폴링에서 처음부터 다시 받는다. 더 받을 것이 있는지는 `has_more` 가 말한다.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if cursor is not None:
        last_at, last_id = decode_cursor(cursor)
        clauses.append("(normalized_at > ? OR (normalized_at = ? AND id > ?))")
        params.extend([last_at, last_at, last_id])

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    # 한 건 더 읽어 다음 페이지가 있는지를 별도 count 없이 판정한다
    rows = conn.execute(
        f"{_SELECT}{where} ORDER BY normalized_at, id LIMIT ?",
        [*params, DEFAULT_LIMIT + 1],
    ).fetchall()

    has_more = len(rows) > DEFAULT_LIMIT
    page = rows[:DEFAULT_LIMIT]
    next_cursor: str | None = cursor
    if page:
        last = page[-1]
        next_cursor = encode_cursor(str(last["normalized_at"]), int(last["id"]))
    return JobPage(items=[_out(row) for row in page], next_cursor=next_cursor, has_more=has_more)
