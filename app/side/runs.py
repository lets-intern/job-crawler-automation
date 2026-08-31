"""부가 워크플로우 실행 기록. `side_runs` 하나만 건드린다.

## 기록이 없는 실행이 없어야 한다

행은 실행이 **시작할 때** 생기고 종료 상태 없이 열려 있다. 끝날 때 상태와 카운트로 닫는다.
끝나고 나서 한 번에 적으면, 도는 도중에 프로세스가 사라진 실행은 아무 데도 남지 않는다 —
그리고 그런 실행이야말로 무엇이 있었는지 알아야 하는 실행이다 (`../.claude/rules/crawling.md`).

닫는 경로가 셋이다. 정상 종료, 예외, 그리고 프로세스가 사라진 뒤의 뒷정리다. 앞의 둘은
`recording` 이 잡고, 마지막은 기동할 때 `close_orphans` 가 잡는다.

## 왜 `crawl_runs` 에 쓰지 않는가

세는 것이 다르다. 크롤 실행은 신규·건너뜀·실패를 세고 여기는 대상·처리·실패를 센다. 섞으면
워크플로우 성공·실패 통계가 크롤링과 무관한 이유로 움직인다 — `app/api/classify.py` 와
`app/normalize/backfill.py` 가 이미 그것을 결정으로 들고 있다.

## 토큰을 세지 않는다

`llm_calls` 가 호출마다 남기고 있다 (`app/llm/log.py`). 같은 숫자를 두 곳에서 세면 어느 쪽이
진실인지 매번 확인해야 한다.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# 종료 상태. 표의 CHECK 와 같은 넷이다 (`migrations/0021_side_workflows.sql`)
SUCCESS = "success"
FAILED = "failed"
SKIPPED = "skipped"
TIMEOUT = "timeout"

_COLUMNS = (
    "id, side_workflow_id, trigger, started_at, finished_at, status, target_count,"
    " processed_count, failed_count, note, error_message"
)

# 사유 문장을 몇 자까지 남길지. 키 하나가 틀리면 같은 문장이 실행마다 쌓인다
MAX_ERROR_CHARS = 500


@dataclass(frozen=True)
class SideRun:
    """실행 한 행. 화면의 실행 이력이 그리는 값 전부다."""

    id: int
    side_workflow_id: int
    trigger: str
    started_at: str
    # 도는 동안에는 둘 다 비어 있다
    finished_at: str | None
    status: str | None
    target_count: int
    processed_count: int
    failed_count: int
    note: str | None
    error_message: str | None

    @property
    def running(self) -> bool:
        """아직 종료가 적히지 않은 실행. 화면이 진행 중으로 읽는다."""
        return self.status is None


@dataclass
class SideRunCounts:
    """실행이 도는 동안 채우는 카운트. 끝날 때 그대로 행에 적힌다.

    `status` 는 실행기가 정상으로 끝내면서도 실패라고 말하고 싶을 때만 채운다. 비워 두면
    성공이다. 예외로 끝난 실행은 이 값과 무관하게 실패다 — 예외를 성공으로 적을 길을 두면
    언젠가 그렇게 적힌다.
    """

    target_count: int = 0
    processed_count: int = 0
    failed_count: int = 0
    # 사람이 읽는 한 줄. 건너뛴 사유나 대상이 없었다는 사실이 들어간다
    note: str | None = None
    status: str | None = None


def start(conn: sqlite3.Connection, side_workflow_id: int, trigger: str) -> int:
    """실행 행을 열고 그 id 를 돌려준다. 종료 상태는 아직 없다.

    `side_workflows.last_run_at` 도 여기서 적는다. **끝날 때가 아니라 시작할 때다.**
    크롤 워크플로우는 끝에 적지만(`app/crawler/runner.py`), 그렇게 하면 프로세스가 사라져
    `timeout` 으로 닫힌 실행이 목록에서는 "실행한 적 없음" 으로 보인다. 목록이 답해야 하는
    질문은 "이것이 돌기는 하는가" 이므로 시작이 그 답이다.
    """
    cursor = conn.execute(
        "INSERT INTO side_runs (side_workflow_id, trigger) VALUES (?, ?)",
        (side_workflow_id, trigger),
    )
    conn.execute(
        "UPDATE side_workflows SET last_run_at = datetime('now') WHERE id = ?",
        (side_workflow_id,),
    )
    return int(cursor.lastrowid or 0)


def finish(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    status: str,
    counts: SideRunCounts | None = None,
    error_message: str | None = None,
) -> None:
    """실행을 닫는다. 상태와 카운트를 함께 적는다.

    이미 닫힌 행도 다시 적는다. 뒷정리가 `timeout` 으로 닫아 둔 실행이 뒤늦게 제 손으로
    끝나는 경우가 그것이고, 그때 맞는 것은 나중 것이다.
    """
    tally = counts or SideRunCounts()
    conn.execute(
        """
        UPDATE side_runs
           SET finished_at = datetime('now'), status = ?, target_count = ?,
               processed_count = ?, failed_count = ?, note = ?, error_message = ?
         WHERE id = ?
        """,
        (
            status,
            tally.target_count,
            tally.processed_count,
            tally.failed_count,
            tally.note,
            _shortened(error_message),
            run_id,
        ),
    )


@contextmanager
def recording(
    conn: sqlite3.Connection, side_workflow_id: int, trigger: str
) -> Iterator[SideRunCounts]:
    """실행 하나를 감싼다. 어떤 종료 경로에서도 행이 닫힌다.

    본문은 넘겨받은 카운트를 채우기만 하면 된다. 정상으로 끝나면 성공(또는 본문이 정한 상태),
    예외로 끝나면 실패로 닫고 예외는 그대로 올려 보낸다. 삼키지 않는 것이 중요하다 — 부른
    쪽이 실패를 알아야 다음 실행을 어떻게 할지 정한다.

    `BaseException` 을 잡는다. `KeyboardInterrupt` 와 취소도 종료 경로이고, 그렇게 끝난
    실행이야말로 기록이 남아야 한다.
    """
    run_id = start(conn, side_workflow_id, trigger)
    counts = SideRunCounts()
    try:
        yield counts
    except BaseException as exc:
        finish(
            conn, run_id, status=FAILED, counts=counts, error_message=f"{type(exc).__name__}: {exc}"
        )
        logger.warning(
            "부가 워크플로우 %s 실행 %s 가 실패로 끝났다: %s", side_workflow_id, run_id, exc
        )
        raise
    finish(conn, run_id, status=counts.status or SUCCESS, counts=counts)


def skipped(conn: sqlite3.Connection, side_workflow_id: int, trigger: str, note: str) -> int:
    """돌지 않은 차례를 남긴다. 열자마자 닫힌 행 하나다.

    앞 실행이 아직 돌고 있어 건너뛴 경우다. 남기지 않으면 주기가 도는데 아무것도 못 하는
    상태와 주기가 아예 죽은 상태가 같아 보인다 (PRD 2절).
    """
    run_id = start(conn, side_workflow_id, trigger)
    finish(conn, run_id, status=SKIPPED, counts=SideRunCounts(note=note))
    return run_id


def latest(conn: sqlite3.Connection, side_workflow_id: int) -> SideRun | None:
    """그 워크플로우의 마지막 실행. 한 번도 돈 적이 없으면 None 이다. 읽기 전용이다.

    화면이 "최근 결과" 로 읽는 값이다. **돌고 있는지를 이것으로 판단하지 않는다** — 건너뛴
    차례는 열자마자 닫힌 행이라, 앞 실행이 아직 도는 중에도 마지막 행은 닫혀 있을 수 있다.
    그 질문의 답은 `open_run` 이다.
    """
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM side_runs WHERE side_workflow_id = ? ORDER BY id DESC LIMIT 1",
        (side_workflow_id,),
    ).fetchone()
    return None if row is None else _from_row(row)


def recent(conn: sqlite3.Connection, side_workflow_id: int, *, limit: int = 10) -> list[SideRun]:
    """그 워크플로우의 최근 실행들. 새것부터. 읽기 전용이다.

    화면의 실행 이력이 보는 값이다. `latest` 는 한 건뿐이라 "성공·실패·건너뜀이 섞여 왔는가"
    를 볼 수 없다.
    """
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM side_runs WHERE side_workflow_id = ? ORDER BY id DESC LIMIT ?",
        (side_workflow_id, limit),
    ).fetchall()
    return [_from_row(row) for row in rows]


def open_run(conn: sqlite3.Connection, side_workflow_id: int) -> SideRun | None:
    """그 워크플로우에서 아직 돌고 있는 실행. 없으면 None 이다. 읽기 전용이다.

    겹침 방지가 보는 값이다. 마지막 행이 아니라 **열린 행**을 찾는다. 건너뛴 차례는 열자마자
    닫히므로, 마지막 행으로 판단하면 건너뜀 하나가 앞의 열린 실행을 가려 그다음 차례부터
    겹쳐 돌게 된다.
    """
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM side_runs"
        " WHERE side_workflow_id = ? AND status IS NULL ORDER BY id LIMIT 1",
        (side_workflow_id,),
    ).fetchone()
    return None if row is None else _from_row(row)


def open_runs(conn: sqlite3.Connection) -> list[SideRun]:
    """지금 돌고 있는 실행 전부. 종료가 적히지 않은 행이다. 읽기 전용이다.

    부가 워크플로우 밖에서 같은 일을 걸려는 경로가 이 값을 본다 — 지금은 `POST /api/classify`
    하나다 (`app/api/classify.py`). 두 경로가 서로를 못 보면 같은 공고에 두 번 돈을 쓴다.

    스키마가 아직 없는 DB 에서는 빈 목록이다. 이 값을 읽는 자리는 실행을 막을지 정하는
    곳이고, 표가 없다는 이유로 500 을 내는 것은 그 질문의 답이 아니다 (`close_orphans` 와
    같은 이유).
    """
    try:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM side_runs WHERE status IS NULL ORDER BY id"
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [_from_row(row) for row in rows]


def read(conn: sqlite3.Connection, run_id: int) -> SideRun | None:
    """그 실행. 없으면 None 이다. 읽기는 예외를 던지지 않는다."""
    row = conn.execute(f"SELECT {_COLUMNS} FROM side_runs WHERE id = ?", (run_id,)).fetchone()
    return None if row is None else _from_row(row)


def close_orphans(conn: sqlite3.Connection) -> int:
    """프로세스가 죽으며 남긴 미완 실행을 닫는다. 기동 시 한 번 부른다.

    `app/crawler/runner.py` 의 `close_orphan_runs` 와 같은 일을 `side_runs` 에 한다.
    SIGKILL 이나 컨테이너 재시작은 코드가 종료를 적을 기회조차 주지 않아서, 그 행은 영원히
    열린 채로 남고 화면은 끝나지 않는 실행을 진행 중으로 읽는다.

    `timeout` 으로 적는다. 얼마나 돌았는지 모르는 채 끝난 실행이고, 성공이 아닌 것은 실패로
    센다는 규칙과 어긋나지 않는다.
    """
    try:
        cursor = conn.execute(
            """
            UPDATE side_runs
               SET status = ?, finished_at = datetime('now'),
                   error_message = '프로세스가 끝나기 전에 사라져 결과를 남기지 못했다'
             WHERE status IS NULL
            """,
            (TIMEOUT,),
        )
    except sqlite3.OperationalError:
        # 스키마가 아직 없는 DB 다. 정리할 것도 없다. 이 함수는 기동 시 뒷정리이지 기동
        # 조건이 아니다 (`app/crawler/runner.py` 와 같은 이유)
        return 0
    return int(cursor.rowcount or 0)


def _shortened(message: str | None) -> str | None:
    if message is None:
        return None
    cleaned = message.strip()
    if not cleaned:
        return None
    return cleaned[:MAX_ERROR_CHARS]


def _from_row(row: sqlite3.Row) -> SideRun:
    return SideRun(
        id=int(row["id"]),
        side_workflow_id=int(row["side_workflow_id"]),
        trigger=str(row["trigger"]),
        started_at=str(row["started_at"]),
        finished_at=None if row["finished_at"] is None else str(row["finished_at"]),
        status=None if row["status"] is None else str(row["status"]),
        target_count=int(row["target_count"]),
        processed_count=int(row["processed_count"]),
        failed_count=int(row["failed_count"]),
        note=None if row["note"] is None else str(row["note"]),
        error_message=None if row["error_message"] is None else str(row["error_message"]),
    )
