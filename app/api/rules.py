"""정규화 규칙 CRUD.

등록·수정·삭제·순서 변경까지다. 규칙 변경은 **이후 신규 데이터부터** 적용된다
(`.claude/docs/data-model.md`).

이 파일의 어떤 경로도 재정규화를 부르지 않는다. 규칙 하나 고칠 때마다 전체 재처리가 도는 것을
막기 위한 결정이고(2026-08-21), 기존 데이터 갱신은 운영자가 명시적으로 누르는 별도 동작이다.
그 동작은 `app/normalize/backfill.py` 에 있다.

설정 검증은 `app/normalize/rules.py` 가 한다. 라우터는 거절 사유를 HTTP 로 옮기기만 한다.
스키마에 맞지 않는 설정은 저장되지 않는다 — 저장되는 순간 그 규칙을 쓰는 실행이 전부 같은
이유로 실패한다.

화면은 Push 6 이다. 여기까지가 저장소와 API 다.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import db
from app.normalize.rules import RuleConfigError, build_rule

router = APIRouter(prefix="/api/rules", tags=["rules"])

_SELECT = """
    SELECT id, field_name, rule_type, rule_config_json, priority, enabled
      FROM normalization_rules
"""


class RuleCreate(BaseModel):
    field_name: str
    rule_type: str
    # 타입별 스키마는 `app/normalize/rules.py` 의 표가 정한다
    rule_config: dict[str, Any]
    priority: int = 0
    enabled: bool = True


class RuleUpdate(BaseModel):
    """부분 수정. 주지 않은 값은 그대로 둔다."""

    field_name: str | None = None
    rule_type: str | None = None
    rule_config: dict[str, Any] | None = None
    priority: int | None = None
    enabled: bool | None = None


class RuleOut(BaseModel):
    id: int
    field_name: str
    rule_type: str
    rule_config: dict[str, Any]
    priority: int
    enabled: bool


class RulePosition(BaseModel):
    id: int
    priority: int


class ReorderRequest(BaseModel):
    """같은 필드 안의 적용 순서를 한 번에 바꾼다."""

    order: list[RulePosition]


def get_connection() -> Iterator[sqlite3.Connection]:
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def _out(row: sqlite3.Row) -> RuleOut:
    return RuleOut(
        id=int(row["id"]),
        field_name=str(row["field_name"]),
        rule_type=str(row["rule_type"]),
        rule_config=json.loads(row["rule_config_json"]),
        priority=int(row["priority"]),
        enabled=bool(row["enabled"]),
    )


def _rejected(exc: RuleConfigError) -> HTTPException:
    """거절 사유를 그대로 실어 보낸다. 무엇을 고쳐야 하는지는 화면이 아니라 여기가 안다."""
    return HTTPException(status_code=422, detail={"reason": exc.reason, "message": str(exc)})


def _row(conn: sqlite3.Connection, rule_id: int) -> sqlite3.Row:
    row = conn.execute(_SELECT + " WHERE id = ?", (rule_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail={"message": f"규칙 {rule_id} 가 없다"})
    return row


@router.get("", response_model=list[RuleOut])
def list_rules(conn: Annotated[sqlite3.Connection, Depends(get_connection)]) -> list[RuleOut]:
    """등록된 규칙 전부. 꺼진 규칙도 함께 보여준다 — 화면에서 다시 켜야 한다."""
    rows = conn.execute(_SELECT + " ORDER BY field_name, priority, id").fetchall()
    return [_out(row) for row in rows]


@router.post("", response_model=RuleOut, status_code=201)
def create_rule(
    payload: RuleCreate, conn: Annotated[sqlite3.Connection, Depends(get_connection)]
) -> RuleOut:
    """규칙을 등록한다. 이 규칙은 다음에 정규화되는 건부터 적용된다."""
    try:
        rule = build_rule(
            payload.field_name,
            payload.rule_type,
            payload.rule_config,
            priority=payload.priority,
            enabled=payload.enabled,
        )
    except RuleConfigError as exc:
        raise _rejected(exc) from exc

    cursor = conn.execute(
        """
        INSERT INTO normalization_rules
               (field_name, rule_type, rule_config_json, priority, enabled)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            rule.field_name,
            rule.rule_type,
            rule.config_json(),
            rule.priority,
            int(rule.enabled),
        ),
    )
    return _out(_row(conn, int(cursor.lastrowid or 0)))


@router.put("/order", response_model=list[RuleOut])
def reorder_rules(
    payload: ReorderRequest, conn: Annotated[sqlite3.Connection, Depends(get_connection)]
) -> list[RuleOut]:
    """여러 규칙의 `priority` 를 한 번에 바꾼다.

    화면에서 순서를 끌어 옮기면 여러 행이 같이 움직인다. 한 건씩 보내면 중간 상태가 그대로
    저장되어, 요청 하나가 실패했을 때 어떤 순서가 남아 있는지 아무도 모른다.
    """
    missing = [
        item.id
        for item in payload.order
        if conn.execute("SELECT 1 FROM normalization_rules WHERE id = ?", (item.id,)).fetchone()
        is None
    ]
    if missing:
        raise HTTPException(
            status_code=404,
            detail={"message": f"없는 규칙이 있다: {', '.join(str(item) for item in missing)}"},
        )

    conn.execute("BEGIN")
    try:
        for item in payload.order:
            conn.execute(
                "UPDATE normalization_rules SET priority = ? WHERE id = ?",
                (item.priority, item.id),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return list_rules(conn)


@router.put("/{rule_id}", response_model=RuleOut)
def update_rule(
    rule_id: int,
    payload: RuleUpdate,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
) -> RuleOut:
    """규칙을 고친다. 이미 정규화된 데이터는 그대로다 — 다음 건부터 새 규칙이다."""
    current = _out(_row(conn, rule_id))
    merged = current.model_copy(update=payload.model_dump(exclude_none=True))

    try:
        # 타입만 바꾸고 설정을 그대로 두는 요청처럼, 합쳐 놓고 봐야 알 수 있는 조합이 있다
        rule = build_rule(
            merged.field_name,
            merged.rule_type,
            merged.rule_config,
            priority=merged.priority,
            enabled=merged.enabled,
        )
    except RuleConfigError as exc:
        raise _rejected(exc) from exc

    conn.execute(
        """
        UPDATE normalization_rules
           SET field_name = ?, rule_type = ?, rule_config_json = ?, priority = ?, enabled = ?
         WHERE id = ?
        """,
        (
            rule.field_name,
            rule.rule_type,
            rule.config_json(),
            rule.priority,
            int(rule.enabled),
            rule_id,
        ),
    )
    return _out(_row(conn, rule_id))


@router.delete("/{rule_id}", status_code=204)
def delete_rule(rule_id: int, conn: Annotated[sqlite3.Connection, Depends(get_connection)]) -> None:
    """규칙을 지운다. 그 규칙으로 이미 정규화된 값은 되돌아가지 않는다."""
    _row(conn, rule_id)
    conn.execute("DELETE FROM normalization_rules WHERE id = ?", (rule_id,))
