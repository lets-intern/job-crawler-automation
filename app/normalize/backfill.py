"""수동 재정규화.

운영자가 명시적으로 실행할 때만 도는 동작이다. 규칙을 저장해도 기존 `normalized_jobs` 는
그대로고, 버튼을 눌렀을 때만 `raw_jobs` 를 다시 읽어 갱신한다 (2026-08-21 결정).

규칙 저장에 재처리를 묶지 않는 이유는 하나다. 규칙 하나 고칠 때마다 전체 재처리가 돌면,
규칙 다섯 개를 손보는 동안 같은 데이터를 다섯 번 다시 쓴다.

## 건드리지 않는 것

`raw_jobs` 는 읽기만 한다. `delivered_at` 도 그대로 둔다 — 소비 측이 이미 가져간 표시를
지우면 같은 데이터가 다시 넘어간다 (`.claude/rules/data-safety.md`). 아래 UPDATE 문이
규칙이 만드는 컬럼과 `company_source`, `normalized_at` 만 적는 것이 그 보장이다.

`crawl_runs` 에도 쓰지 않는다. 재정규화는 크롤링 실행이 아니고, 섞어 쓰면 워크플로우의
성공·실패 통계가 크롤링과 무관한 이유로 움직인다.

## 진행 상황

한 프로세스 안의 메모리에 둔다. 이 서비스는 FastAPI 한 프로세스이고, 재정규화는 그 프로세스가
살아 있는 동안만 도는 작업이라 진행 상황도 그 수명을 넘길 이유가 없다. 프로세스가 죽으면
작업도 같이 죽고, 운영자는 다시 누른다. 이력이 필요해지면 그때 테이블을 만든다.

돌고 있는 동안 들어온 요청은 거부한다. 같은 재정규화가 둘이면 같은 행을 두 번 쓰고, 진행
상황은 어느 쪽 것인지 알 수 없게 된다.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.normalize.engine import (
    COMPANY_SOURCE,
    NormalizeError,
    RawJobMissingError,
    insert_normalized,
    load_rules,
    normalize_fields,
    read_default_company,
    read_raw,
)
from app.normalize.rules import Rule

logger = logging.getLogger(__name__)

ConnectFactory = Callable[[], sqlite3.Connection]

# 실패 사유를 몇 건까지 들고 있을지. 전부 쌓아 두면 규칙 하나가 틀렸을 때 메모리에 만 건이
# 같은 문장으로 들어찬다. 앞의 몇 건이면 무엇이 틀렸는지는 충분히 보인다.
MAX_ERRORS = 20


class BackfillRunningError(RuntimeError):
    """이미 재정규화가 돌고 있다. 두 번 돌리지 않는다."""


@dataclass
class BackfillProgress:
    """대상 건수, 처리 건수, 실패 건수. 화면이 그대로 읽는다."""

    running: bool = False
    total: int = 0
    processed: int = 0
    failed: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    errors: list[str] = field(default_factory=list)

    def snapshot(self) -> BackfillProgress:
        """읽는 쪽에 넘길 복사본. 돌고 있는 작업이 값을 바꿔도 흔들리지 않는다."""
        return BackfillProgress(
            running=self.running,
            total=self.total,
            processed=self.processed,
            failed=self.failed,
            started_at=self.started_at,
            finished_at=self.finished_at,
            errors=list(self.errors),
        )

    def note(self, message: str) -> None:
        self.failed += 1
        if len(self.errors) < MAX_ERRORS:
            self.errors.append(message)


class Backfill:
    """재정규화 한 번. 동시에 하나만 돈다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._progress = BackfillProgress()
        self._thread: threading.Thread | None = None

    def progress(self) -> BackfillProgress:
        with self._lock:
            return self._progress.snapshot()

    def start(self, connect: ConnectFactory) -> BackfillProgress:
        """백그라운드로 시작한다. 이미 돌고 있으면 `BackfillRunningError`."""
        with self._lock:
            if self._progress.running:
                raise BackfillRunningError("재정규화가 이미 돌고 있다")
            self._progress = BackfillProgress(running=True, started_at=_now())
            started = self._progress.snapshot()

        self._thread = threading.Thread(
            target=self._work, args=(connect,), name="renormalize", daemon=True
        )
        self._thread.start()
        return started

    def wait(self, timeout: float | None = None) -> bool:
        """작업이 끝날 때까지 기다린다. 끝났으면 True. 테스트와 종료 처리가 쓴다."""
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def _work(self, connect: ConnectFactory) -> None:
        conn = connect()
        try:
            renormalize(conn, self._progress)
        except Exception as exc:
            # 스레드에서 올라온 예외는 아무도 보지 못한다. 진행 상황에 남긴다
            logger.exception("재정규화가 중단됐다")
            with self._lock:
                self._progress.note(f"재정규화가 중단됐다: {exc}")
        finally:
            conn.close()
            with self._lock:
                self._progress.running = False
                self._progress.finished_at = _now()


def renormalize(conn: sqlite3.Connection, progress: BackfillProgress) -> BackfillProgress:
    """`raw_jobs` 를 처음부터 다시 읽어 `normalized_jobs` 를 갱신한다.

    한 건이 실패해도 나머지는 계속 간다. 규칙 하나가 어떤 값에서만 터지는 경우가 흔하고,
    거기서 멈추면 뒤쪽 데이터는 손도 못 댄 채 남는다.
    """
    raw_ids = [int(row["id"]) for row in conn.execute("SELECT id FROM raw_jobs ORDER BY id")]
    progress.total = len(raw_ids)

    try:
        rules = load_rules(conn)
    except NormalizeError as exc:
        # 규칙을 못 읽으면 어떤 건도 정규화할 수 없다. 아무것도 쓰지 않고 끝낸다
        progress.note(f"정규화 규칙을 읽지 못했다: {exc}")
        return progress

    for raw_id in raw_ids:
        try:
            _rewrite(conn, raw_id, rules)
            progress.processed += 1
        except (NormalizeError, RawJobMissingError) as exc:
            progress.note(f"raw_jobs {raw_id}: {exc}")

    logger.info(
        "재정규화: 대상 %s건, 처리 %s건, 실패 %s건",
        progress.total,
        progress.processed,
        progress.failed,
    )
    return progress


def _rewrite(conn: sqlite3.Connection, raw_job_id: int, rules: list[Rule]) -> None:
    """한 건을 다시 정규화한다. 행이 없으면 새로 넣는다.

    UPDATE 가 적는 컬럼은 규칙이 만드는 여섯 개와 `company_source`, `normalized_at` 뿐이다.
    `delivered_at` 은 목록에 없고, 그래서 소비 측이 가져간 표시는 재정규화를 몇 번 돌려도
    그대로다.

    운영자가 `crawlers.default_company` 를 고쳤으면 그 값이 이 경로로 반영된다. 회사명을
    파싱값으로 확정한 행은 운영자값을 고쳐도 같은 파싱값이 다시 이겨서 바뀌지 않는다.
    """
    _, data = read_raw(conn, raw_job_id)
    fields = normalize_fields(data, rules, read_default_company(conn, raw_job_id))
    cursor = conn.execute(
        """
        UPDATE normalized_jobs
           SET company = ?, company_source = ?, title = ?, department = ?, deadline = ?,
               body = ?, requirements = ?, normalized_at = datetime('now')
         WHERE raw_job_id = ?
        """,
        (
            fields["company"],
            fields[COMPANY_SOURCE],
            fields["title"],
            fields["department"],
            fields["deadline"],
            fields["body"],
            fields["requirements"],
            raw_job_id,
        ),
    )
    if cursor.rowcount == 0:
        # 적재는 됐는데 정규화에 실패했던 건이다. 규칙을 고친 뒤 이 경로로 복구된다
        insert_normalized(conn, raw_job_id, rules)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


_backfill = Backfill()


def get_backfill() -> Backfill:
    """앱이 쓰는 재정규화 하나. 테스트는 이 의존성을 갈아끼운다."""
    return _backfill
