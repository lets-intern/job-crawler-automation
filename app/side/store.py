"""부가 워크플로우 행을 읽고 쓴다. `side_workflows` 하나만 건드린다.

`app/companies.py` 와 같은 자리의 모듈이다 — 표 하나를 가진 저장소이고, 그 표에 쓰는 코드는
여기 말고 없다. 화면도 스케줄러도 이 함수들을 지나간다.

## 읽기는 예외를 던지지 않고 쓰기는 검증을 지난다

`app/notify/settings.py` 와 같다. 목록과 한 건 읽기는 없는 것을 빈 값으로 돌려준다 — 이 값을
읽는 자리가 목록 화면과 스케줄러 동기화라, 행 하나가 이상하다고 화면 전체가 500 이 되거나
스케줄러가 뜨지 않게 둘 수 없다.

쓰기는 반대로 깐깐하다. 저장되는 값은 전부 검증을 지나고, 하나라도 걸리면 아무것도 저장되지
않는다.

## 종류를 나중에 바꾸지 않는다

`kind` 는 만들 때 정하고 `update` 는 받지 않는다. 종류가 바뀌면 `target_scope` 의 뜻이 같이
바뀌는데, 그때 이미 저장된 범위가 새 종류에서 무엇을 뜻하는지 정할 방법이 없다. 종류를 바꾸는
일은 지우고 다시 만드는 일이다.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.classify.batch import MAX_LIMIT
from app.classify.store import ALL, CLASSIFY_SCOPES, RECENT

CLASSIFY = "classify"
DELIVER = "deliver"
KINDS: tuple[str, ...] = (CLASSIFY, DELIVER)

ACTIVE = "active"
PAUSED = "paused"
STATUSES: tuple[str, ...] = (ACTIVE, PAUSED)

# 주기로 도는 실행 시점. 스케줄러가 잡으로 등록하는 것은 이것 하나다 (`app/scheduler.py`).
# 나머지 둘은 낱말이 필요한 자리가 아직 없어 이름을 두지 않는다
INTERVAL = "interval"
TRIGGER_KINDS: tuple[str, ...] = (INTERVAL, "after_crawl", "manual")

# 종류마다 받는 대상 범위가 다르다. 앞의 것이 그 종류의 기본값이다 (PRD 2·3 절).
#
# 분류가 받는 넷은 `app/classify/store.py` 가 정한다. 그 이름으로 대상을 고르는 조회가
# 거기 있고, 이름을 두 벌 두면 범위를 하나 더할 때 한쪽만 넓어진다 — 저장은 되는데 아무것도
# 고르지 못하는 워크플로우가 그렇게 생긴다
SCOPES: dict[str, tuple[str, ...]] = {
    CLASSIFY: CLASSIFY_SCOPES,
    DELIVER: ("undelivered", RECENT, ALL),
}

# 표의 기본값과 같은 값이다. 화면이 폼을 그릴 때 쓴다
DEFAULT_INTERVAL_MINUTES = 360
DEFAULT_BATCH_LIMIT = 50

_COLUMNS = (
    "id, kind, name, status, trigger_kind, interval_minutes, target_scope, target_days,"
    " batch_limit, last_run_at, created_at"
)


class SideWorkflowNotFoundError(LookupError):
    """그 id 의 부가 워크플로우가 없다. 쓰기는 있는 행에만 한다."""


class SideWorkflowError(ValueError):
    """저장할 수 없는 값. 거절 사유를 화면이 그대로 옮긴다."""


@dataclass(frozen=True)
class SideWorkflow:
    """부가 워크플로우 한 행. 화면이 그리는 값 전부다."""

    id: int
    kind: str
    name: str
    # 새로 만들면 `paused` 다. 켜는 것은 운영자가 한다
    status: str
    trigger_kind: str
    interval_minutes: int
    target_scope: str
    # `recent` 일 때만 값이 있다
    target_days: int | None
    # 1회 상한 건수
    batch_limit: int
    last_run_at: str | None
    created_at: str

    @property
    def scopes(self) -> tuple[str, ...]:
        """이 종류가 받는 대상 범위. 화면이 고를 것을 그릴 때 쓴다."""
        return SCOPES.get(self.kind, ())


def default_scope(kind: str) -> str:
    """그 종류의 기본 대상 범위. 모르는 종류면 빈 문자열이다 — 검증이 거절한다."""
    return SCOPES.get(kind, ("",))[0]


def list_all(conn: sqlite3.Connection) -> list[SideWorkflow]:
    """모든 부가 워크플로우. 만든 순서다. 읽기 전용이다.

    실행 기록을 함께 읽지 않는다. 목록에 마지막 실행 결과를 붙이는 일은 그 표를 읽는 쪽이
    하고, 이 모듈은 설정 한 표만 본다.
    """
    rows = conn.execute(f"SELECT {_COLUMNS} FROM side_workflows ORDER BY id").fetchall()
    return [_from_row(row) for row in rows]


def read(conn: sqlite3.Connection, side_workflow_id: int) -> SideWorkflow | None:
    """그 id 의 부가 워크플로우. 없으면 None 이다."""
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM side_workflows WHERE id = ?", (side_workflow_id,)
    ).fetchone()
    return None if row is None else _from_row(row)


def create(
    conn: sqlite3.Connection,
    *,
    kind: str,
    name: str,
    status: str = PAUSED,
    trigger_kind: str = "manual",
    interval_minutes: int = DEFAULT_INTERVAL_MINUTES,
    target_scope: str | None = None,
    target_days: int | None = None,
    batch_limit: int = DEFAULT_BATCH_LIMIT,
) -> SideWorkflow:
    """부가 워크플로우 하나를 만든다.

    **멈춘 채로 시작한다.** 대상 범위를 잘못 고른 채 저장하는 것과 그것이 곧바로 도는 것은
    다른 이야기고, `all` 은 640건이면 약 285만 토큰이다 (PRD 2절).

    `target_scope` 를 주지 않으면 그 종류의 기본값이다.
    """
    scope = default_scope(kind) if target_scope is None else target_scope
    cleaned = _validated(
        kind=kind,
        name=name,
        status=status,
        trigger_kind=trigger_kind,
        interval_minutes=interval_minutes,
        target_scope=scope,
        target_days=target_days,
        batch_limit=batch_limit,
    )
    cursor = conn.execute(
        """
        INSERT INTO side_workflows (kind, name, status, trigger_kind, interval_minutes,
                                    target_scope, target_days, batch_limit)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (kind, cleaned, status, trigger_kind, interval_minutes, scope, target_days, batch_limit),
    )
    created = read(conn, int(cursor.lastrowid or 0))
    if created is None:  # pragma: no cover - 방금 넣은 행이 사라지는 경로는 없다
        raise SideWorkflowNotFoundError("방금 만든 부가 워크플로우를 다시 읽지 못했다")
    return created


def update(
    conn: sqlite3.Connection,
    side_workflow_id: int,
    *,
    name: str,
    status: str,
    trigger_kind: str,
    interval_minutes: int,
    target_scope: str,
    target_days: int | None,
    batch_limit: int,
) -> SideWorkflow:
    """고칠 수 있는 칸을 통째로 바꾼다. 행이 없으면 `SideWorkflowNotFoundError` 다.

    한 칸씩 고치는 함수를 두지 않는다. 이 값을 고치는 자리가 등록·수정 폼 하나이고, 그 폼은
    언제나 전부를 보낸다. 칸마다 setter 를 두면 `target_scope` 만 `recent` 로 바꾸고
    `target_days` 는 안 보내는 호출이 생기는데, 그것은 저장할 수 없는 상태다.

    `kind` 와 `last_run_at` 은 받지 않는다. 종류는 만들 때 정해지고, 마지막 실행 시각은
    실행 기록이 적는다.

    대상 범위는 **저장된 종류**로 본다. 폼이 종류를 함께 보내더라도 그것을 믿지 않는다 —
    믿으면 분류 워크플로우를 전달로 적어 보내는 것만으로 `unclassified` 가 아닌 범위가
    들어간다.
    """
    existing = read(conn, side_workflow_id)
    if existing is None:
        raise SideWorkflowNotFoundError(f"부가 워크플로우가 없다: {side_workflow_id}")
    cleaned = _validated(
        kind=existing.kind,
        name=name,
        status=status,
        trigger_kind=trigger_kind,
        interval_minutes=interval_minutes,
        target_scope=target_scope,
        target_days=target_days,
        batch_limit=batch_limit,
    )
    conn.execute(
        """
        UPDATE side_workflows
           SET name = ?, status = ?, trigger_kind = ?, interval_minutes = ?,
               target_scope = ?, target_days = ?, batch_limit = ?
         WHERE id = ?
        """,
        (
            cleaned,
            status,
            trigger_kind,
            interval_minutes,
            target_scope,
            target_days,
            batch_limit,
            side_workflow_id,
        ),
    )
    updated = read(conn, side_workflow_id)
    if updated is None:  # pragma: no cover - 방금 고친 행이 사라지는 경로는 없다
        raise SideWorkflowNotFoundError(f"부가 워크플로우가 없다: {side_workflow_id}")
    return updated


def delete(conn: sqlite3.Connection, side_workflow_id: int) -> None:
    """부가 워크플로우와 그 실행 기록을 지운다. 행이 없으면 `SideWorkflowNotFoundError` 다.

    실행 기록을 함께 지운다. `side_runs.side_workflow_id` 가 외래키라 남겨 둘 수가 없고,
    설정이 사라진 실행 기록은 무엇을 대상으로 무엇이 돌았는지 알 수 없는 행이다.

    **`raw_jobs` 도 `normalized_jobs` 도 건드리지 않는다.** 지워지는 것은 이 작업을 언제 어떻게
    돌릴지에 대한 설정이지 그 작업이 만든 데이터가 아니다. 분류 결과는 `job_classifications` 에
    그대로 남는다.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM side_runs WHERE side_workflow_id = ?", (side_workflow_id,))
        cursor = conn.execute("DELETE FROM side_workflows WHERE id = ?", (side_workflow_id,))
        if cursor.rowcount == 0:
            raise SideWorkflowNotFoundError(f"부가 워크플로우가 없다: {side_workflow_id}")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _validated(
    *,
    kind: str,
    name: str,
    status: str,
    trigger_kind: str,
    interval_minutes: int,
    target_scope: str,
    target_days: int | None,
    batch_limit: int,
) -> str:
    """저장하기 전에 본다. 하나라도 걸리면 아무것도 저장하지 않는다. 다듬은 이름을 돌려준다.

    표의 CHECK 가 같은 것을 대부분 막지만, `sqlite3.IntegrityError` 는 운영자에게 어느 칸이
    왜 틀렸는지 말해 주지 않는다. 여기서 먼저 걸러 사유를 낱말로 만든다. CHECK 를 빼지 않는
    것은 화면이 아닌 길로 들어오는 값도 있기 때문이다.

    `batch_limit` 의 상한만은 여기에만 있다. `MAX_LIMIT` 은 `app/classify/batch.py` 의 값이고,
    그것을 표에 적으면 상한을 고치는 일이 마이그레이션이 된다.
    """
    if kind not in KINDS:
        raise SideWorkflowError(
            f"부가 워크플로우 종류가 아니다: {kind!r}. {' 또는 '.join(KINDS)} 다"
        )
    cleaned = name.strip()
    if not cleaned:
        raise SideWorkflowError("이름이 비어 있다")
    if status not in STATUSES:
        raise SideWorkflowError(f"상태는 {' 또는 '.join(STATUSES)} 다: {status!r}")
    if trigger_kind not in TRIGGER_KINDS:
        raise SideWorkflowError(
            f"실행 시점이 아니다: {trigger_kind!r}. {', '.join(TRIGGER_KINDS)} 중 하나다"
        )
    if interval_minutes < 1:
        raise SideWorkflowError(f"주기는 1분 이상이어야 한다: {interval_minutes}")

    scopes = SCOPES[kind]
    if target_scope not in scopes:
        raise SideWorkflowError(
            f"{kind} 가 받는 대상 범위가 아니다: {target_scope!r}. {', '.join(scopes)} 중 하나다"
        )
    if target_scope == RECENT:
        if target_days is None or target_days < 1:
            raise SideWorkflowError(
                f"대상 범위가 {RECENT} 면 최근 며칠을 볼지 1 이상으로 적어야 한다: {target_days}"
            )
    elif target_days is not None:
        raise SideWorkflowError(
            f"대상 범위가 {target_scope} 면 일수를 두지 않는다: {target_days}."
            f" 일수는 {RECENT} 에만 쓴다"
        )

    if not 1 <= batch_limit <= MAX_LIMIT:
        raise SideWorkflowError(f"1회 상한 건수는 1 이상 {MAX_LIMIT} 이하여야 한다: {batch_limit}")
    return cleaned


def _from_row(row: sqlite3.Row) -> SideWorkflow:
    return SideWorkflow(
        id=int(row["id"]),
        kind=str(row["kind"]),
        name=str(row["name"]),
        status=str(row["status"]),
        trigger_kind=str(row["trigger_kind"]),
        interval_minutes=int(row["interval_minutes"]),
        target_scope=str(row["target_scope"]),
        target_days=None if row["target_days"] is None else int(row["target_days"]),
        batch_limit=int(row["batch_limit"]),
        last_run_at=None if row["last_run_at"] is None else str(row["last_run_at"]),
        created_at=str(row["created_at"]),
    )
