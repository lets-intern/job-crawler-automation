"""수동 재정규화 테스트.

확인하는 것은 넷이다.

- 규칙을 바꾼 뒤 재정규화하면 `normalized_jobs` 의 값이 새 규칙을 따른다
- `delivered_at` 은 이전 값 그대로다. 소비 측이 가져간 표시를 지우면 같은 데이터가 다시 간다
- `raw_jobs` 는 바이트 단위로 그대로다
- 돌고 있는 동안 들어온 재요청은 거부된다

크롤링은 저장된 python.org 픽스처로 돈다. 실사이트에 나가지 않는다.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
import threading
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import rules as rules_api
from app.crawler.runner import run_workflow
from app.main import app
from app.normalize.backfill import Backfill, BackfillProgress, BackfillRunningError, renormalize
from tests.test_normalize_engine import raw_snapshot
from tests.test_normalize_pipeline import LIST_URL, SELECTORS, stub_fetcher

DELIVERED_AT = "2026-08-20T09:00:00+00:00"


@pytest.fixture
def db_path(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path / "jobs.db"


@pytest.fixture
def conn(db_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(db_path)
    db.migrate_up(connection)
    connection.execute(
        """
        INSERT INTO crawlers (name, list_url, selectors_json, status)
        VALUES (?, ?, ?, 'promoted')
        """,
        ("python.org", LIST_URL, json.dumps(SELECTORS)),
    )
    connection.execute("INSERT INTO workflows (crawler_id, name) VALUES (1, 'python.org')")
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def backfill() -> Backfill:
    """테스트마다 새 것. 앱 전역 하나를 공유하면 앞 테스트가 남긴 상태가 넘어온다."""
    return Backfill()


@pytest.fixture
def client(
    db_path: pathlib.Path, conn: sqlite3.Connection, backfill: Backfill
) -> Iterator[TestClient]:
    def request_connection() -> Iterator[sqlite3.Connection]:
        connection = db.connect(db_path)
        try:
            yield connection
        finally:
            connection.close()

    app.dependency_overrides[rules_api.get_connection] = request_connection
    app.dependency_overrides[rules_api.get_connect_factory] = lambda: lambda: db.connect(db_path)
    app.dependency_overrides[rules_api.get_backfill] = lambda: backfill
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def add_rule(conn: sqlite3.Connection, field_name: str, rule_type: str, config: dict) -> None:
    conn.execute(
        """
        INSERT INTO normalization_rules (field_name, rule_type, rule_config_json)
        VALUES (?, ?, ?)
        """,
        (field_name, rule_type, json.dumps(config)),
    )


def mark_delivered(conn: sqlite3.Connection, normalized_id: int) -> None:
    """제공 API 가 하는 일을 흉내낸다. 이 컬럼을 쓰는 곳은 원래 거기뿐이다."""
    conn.execute(
        "UPDATE normalized_jobs SET delivered_at = ? WHERE id = ?", (DELIVERED_AT, normalized_id)
    )


async def collect_two(conn: sqlite3.Connection) -> None:
    await run_workflow(conn, 1, fetcher=stub_fetcher(), limit=2)


async def test_renormalize_applies_new_rules(conn: sqlite3.Connection) -> None:
    await collect_two(conn)
    before = [dict(row) for row in conn.execute("SELECT * FROM normalized_jobs ORDER BY id")]
    assert all("\n" in row["title"] for row in before), "규칙 없이 들어간 값은 원문 그대로다"

    add_rule(conn, "title", "trim", {})
    progress = renormalize(conn, BackfillProgress())

    assert (progress.total, progress.processed, progress.failed) == (2, 2, 0)
    after = [dict(row) for row in conn.execute("SELECT * FROM normalized_jobs ORDER BY id")]
    assert [row["id"] for row in after] == [row["id"] for row in before]
    assert [row["title"] for row in after] == [" ".join(row["title"].split()) for row in before]


async def test_delivered_at_survives_renormalization(conn: sqlite3.Connection) -> None:
    """소비 측이 가져간 표시를 지우면 같은 데이터가 다시 넘어간다."""
    await collect_two(conn)
    mark_delivered(conn, 1)
    add_rule(conn, "title", "trim", {})

    renormalize(conn, BackfillProgress())

    rows = conn.execute("SELECT id, delivered_at FROM normalized_jobs ORDER BY id").fetchall()
    assert rows[0]["delivered_at"] == DELIVERED_AT
    assert rows[1]["delivered_at"] is None
    # 값은 실제로 바뀌었다. 그래도 delivered_at 만 그대로여야 한다
    assert "\n" not in conn.execute("SELECT title FROM normalized_jobs WHERE id = 1").fetchone()[0]


async def test_raw_jobs_untouched(conn: sqlite3.Connection) -> None:
    await collect_two(conn)
    add_rule(conn, "title", "trim", {})
    before = raw_snapshot(conn)

    renormalize(conn, BackfillProgress())

    assert raw_snapshot(conn) == before


async def test_crawl_runs_untouched(conn: sqlite3.Connection) -> None:
    """재정규화는 크롤링 실행이 아니다. crawl_runs 에 섞어 쓰지 않는다."""
    await collect_two(conn)
    before = [dict(row) for row in conn.execute("SELECT * FROM crawl_runs ORDER BY id")]

    renormalize(conn, BackfillProgress())

    assert [dict(row) for row in conn.execute("SELECT * FROM crawl_runs ORDER BY id")] == before


async def test_failed_rows_are_counted_and_run_continues(conn: sqlite3.Connection) -> None:
    await collect_two(conn)
    add_rule(conn, "title", "date_parse", {"formats": ["%Y.%m.%d"]})

    progress = renormalize(conn, BackfillProgress())

    assert (progress.total, progress.processed, progress.failed) == (2, 0, 2)
    assert len(progress.errors) == 2
    # 실패한 건의 이전 값은 그대로 남는다. 되돌릴 원문은 raw 에 있다
    assert conn.execute("SELECT count(*) AS n FROM normalized_jobs").fetchone()["n"] == 2


async def test_missing_normalized_row_is_created(conn: sqlite3.Connection) -> None:
    """적재는 됐는데 정규화에 실패했던 건. 규칙을 고친 뒤 이 경로로 복구된다."""
    add_rule(conn, "title", "date_parse", {"formats": ["%Y.%m.%d"]})
    await collect_two(conn)
    assert conn.execute("SELECT count(*) AS n FROM normalized_jobs").fetchone()["n"] == 0

    conn.execute("DELETE FROM normalization_rules")
    progress = renormalize(conn, BackfillProgress())

    assert (progress.total, progress.processed, progress.failed) == (2, 2, 0)
    assert conn.execute("SELECT count(*) AS n FROM normalized_jobs").fetchone()["n"] == 2


async def test_broken_stored_rule_writes_nothing(conn: sqlite3.Connection) -> None:
    await collect_two(conn)
    before = [dict(row) for row in conn.execute("SELECT * FROM normalized_jobs ORDER BY id")]
    conn.execute(
        "INSERT INTO normalization_rules (field_name, rule_type, rule_config_json)"
        " VALUES ('title', 'regex', ?)",
        (json.dumps({"pattern": "(["}),),
    )

    progress = renormalize(conn, BackfillProgress())

    assert progress.processed == 0
    assert progress.failed == 1
    assert [
        dict(row) for row in conn.execute("SELECT * FROM normalized_jobs ORDER BY id")
    ] == before


def test_second_start_is_rejected(db_path: pathlib.Path, conn: sqlite3.Connection) -> None:
    """돌고 있는 동안 들어온 요청은 거부한다. 같은 재정규화가 두 번 돌지 않는다."""
    gate = threading.Event()

    def blocking_connect() -> sqlite3.Connection:
        assert gate.wait(timeout=5), "게이트가 열리지 않았다"
        return db.connect(db_path)

    backfill = Backfill()
    backfill.start(blocking_connect)
    try:
        assert backfill.progress().running is True
        with pytest.raises(BackfillRunningError):
            backfill.start(blocking_connect)
    finally:
        gate.set()

    assert backfill.wait(timeout=5)
    finished = backfill.progress()
    assert finished.running is False
    assert finished.finished_at is not None
    # 거부된 요청이 진행 상황을 덮어쓰지 않았다
    assert finished.started_at is not None


async def test_api_starts_and_reports(
    client: TestClient, conn: sqlite3.Connection, backfill: Backfill
) -> None:
    await collect_two(conn)
    add_rule(conn, "title", "trim", {})

    started = client.post("/api/rules/renormalize")
    assert started.status_code == 202
    assert started.json()["running"] is True

    assert backfill.wait(timeout=5)

    reported = client.get("/api/rules/renormalize").json()
    assert reported["running"] is False
    assert (reported["total"], reported["processed"], reported["failed"]) == (2, 2, 0)
    assert "\n" not in conn.execute("SELECT title FROM normalized_jobs WHERE id = 1").fetchone()[0]


def test_api_rejects_a_second_run(
    client: TestClient, db_path: pathlib.Path, backfill: Backfill
) -> None:
    gate = threading.Event()

    def blocking_connect() -> sqlite3.Connection:
        assert gate.wait(timeout=5), "게이트가 열리지 않았다"
        return db.connect(db_path)

    backfill.start(blocking_connect)
    try:
        response = client.post("/api/rules/renormalize")
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "already_running"
    finally:
        gate.set()
    assert backfill.wait(timeout=5)
