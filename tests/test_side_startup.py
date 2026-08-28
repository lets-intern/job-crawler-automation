"""기동 시 부가 실행 뒷정리 (3.1.1).

`close_orphans` 는 Push 1 이 만들었지만 부르는 곳이 없었다. 함수 단위 테스트는 그 결함을
잡지 못한다 — 함수는 잘 돌기 때문이다. 그래서 여기서는 실제 `lifespan` 을 지난다.

모델에도 실사이트에도 나가지 않는다. 임시 DB 하나를 `DATABASE_PATH` 로 가리키고 앱을
띄웠다 내린다.
"""

from __future__ import annotations

import os
from pathlib import Path

from app import db
from app.config import get_settings
from app.main import app, lifespan
from app.side import runs, store


async def test_startup_closes_side_runs_left_open(tmp_path: Path) -> None:
    """프로세스가 사라져 열린 채 남은 행이 기동 한 번으로 닫힌다."""
    path = tmp_path / "jobs.db"
    conn = db.connect(path)
    db.migrate_up(conn)
    workflow = store.create(conn, kind="classify", name="분류")
    run_id = runs.start(conn, workflow.id, "schedule")
    conn.close()

    previous = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = str(path)
    get_settings.cache_clear()
    try:
        async with lifespan(app):
            pass
    finally:
        if previous is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = previous
        get_settings.cache_clear()

    conn = db.connect(path)
    try:
        closed = runs.read(conn, run_id)
        assert closed is not None
        assert closed.status == runs.TIMEOUT
        assert closed.finished_at is not None
        assert closed.error_message is not None
    finally:
        conn.close()
