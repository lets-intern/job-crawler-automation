"""`delivered_at` 쓰기 경로 격리.

이 컬럼을 쓰는 곳은 `POST /api/jobs/delivered` 하나뿐이다 (`../.claude/rules/data-safety.md`).
값이 지워지거나 뒤로 밀리면 소비 측이 이미 받은 공고를 다시 받는다.

여기서 보는 것은 둘이다. 전달 표시된 행을 재정규화하고 같은 워크플로우를 한 번 더 돌려도
`delivered_at` 이 그대로인가, 그리고 저장소 안에 이 컬럼을 쓰는 다른 코드가 생기지 않았는가.

크롤링은 저장된 python.org 픽스처로 돈다. 실사이트에 나가지 않는다.
"""

from __future__ import annotations

import json
import pathlib
import re
import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import jobs as jobs_api
from app.crawler.runner import run_workflow
from app.main import app
from app.normalize.backfill import BackfillProgress, renormalize
from tests.test_normalize_pipeline import LIST_URL, SELECTORS, stub_fetcher

# 눈에 띄게 과거인 값. 덮어쓰이면 오늘 날짜로 바뀌어 바로 드러난다
LONG_AGO = "2020-01-01 00:00:00"

APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"
# 이 컬럼에 쓰기가 허용된 유일한 파일
WRITER = APP_DIR / "api" / "jobs.py"

_SET_WRITE = re.compile(r"SET\b[^;]{0,600}?delivered_at\s*=", re.DOTALL)
_INSERT_WRITE = re.compile(r"INSERT\s+INTO\s+normalized_jobs\s*\([^)]*delivered_at", re.DOTALL)


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
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
def client(tmp_path: pathlib.Path, conn: sqlite3.Connection) -> Iterator[TestClient]:
    def request_connection() -> Iterator[sqlite3.Connection]:
        connection = db.connect(tmp_path / "jobs.db")
        try:
            yield connection
        finally:
            connection.close()

    app.dependency_overrides[jobs_api.get_connection] = request_connection
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def add_trim_rule(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT INTO normalization_rules (field_name, rule_type, rule_config_json)
        VALUES ('title', 'trim', '{}')
        """
    )


def snapshot(conn: sqlite3.Connection) -> list[tuple[int, str | None, str, str | None]]:
    rows = conn.execute(
        "SELECT id, delivered_at, normalized_at, title FROM normalized_jobs ORDER BY id"
    ).fetchall()
    return [
        (int(row["id"]), row["delivered_at"], str(row["normalized_at"]), row["title"])
        for row in rows
    ]


async def test_delivered_at_survives_renormalize_and_a_second_run(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """전달 표시 → 재정규화 → 같은 워크플로우 1회 더. `delivered_at` 은 그대로여야 한다."""
    await run_workflow(conn, 1, fetcher=stub_fetcher(), limit=2)
    ids = [int(row["id"]) for row in conn.execute("SELECT id FROM normalized_jobs ORDER BY id")]
    assert len(ids) == 2

    # 전달 표시는 계약이 정한 경로로만 찍는다
    marked = client.post("/api/jobs/delivered", json={"ids": ids}).json()
    assert marked == {"marked": 2, "already_delivered": 0, "missing": []}

    # 오래 전에 전달된 상태로 돌려 놓는다. 아래 두 동작이 값을 다시 쓰면 오늘로 바뀐다
    conn.execute("UPDATE normalized_jobs SET delivered_at = ?", (LONG_AGO,))
    before = snapshot(conn)
    assert [row[1] for row in before] == [LONG_AGO, LONG_AGO]
    assert all("\n" in (row[3] or "") for row in before), "규칙 없이 들어간 값은 원문 그대로다"

    add_trim_rule(conn)
    progress = renormalize(conn, BackfillProgress())
    assert (progress.total, progress.processed, progress.failed) == (2, 2, 0)

    raw_before = int(conn.execute("SELECT count(*) AS n FROM raw_jobs").fetchone()["n"])
    await run_workflow(conn, 1, fetcher=stub_fetcher(), limit=2)
    raw_after = int(conn.execute("SELECT count(*) AS n FROM raw_jobs").fetchone()["n"])
    assert raw_after == raw_before, "같은 페이지를 다시 돌면 내용 해시가 같아 새 행이 없다"

    after = snapshot(conn)
    assert [row[0] for row in after] == [row[0] for row in before]
    # 단언의 본체. 두 동작을 거쳐도 전달 시각은 처음 값 그대로다
    assert [row[1] for row in after] == [LONG_AGO, LONG_AGO]
    # 재정규화가 실제로 값을 바꿨다. 아무 일도 없어서 통과한 것이 아니다
    assert all("\n" not in (row[3] or "") for row in after)


async def test_second_run_does_not_clear_delivered_at_of_untouched_rows(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """한 건만 전달 표시한 뒤 다시 돌려도, 표시한 건만 값이 있고 나머지는 NULL 이다."""
    await run_workflow(conn, 1, fetcher=stub_fetcher(), limit=2)
    ids = [int(row["id"]) for row in conn.execute("SELECT id FROM normalized_jobs ORDER BY id")]

    client.post("/api/jobs/delivered", json={"ids": [ids[0]]})
    conn.execute("UPDATE normalized_jobs SET delivered_at = ? WHERE id = ?", (LONG_AGO, ids[0]))

    await run_workflow(conn, 1, fetcher=stub_fetcher(), limit=2)

    values = [row[1] for row in snapshot(conn)]
    assert values == [LONG_AGO, None]


def test_only_the_delivery_endpoint_writes_delivered_at() -> None:
    """저장소 안에서 이 컬럼에 쓰는 파일이 하나인지 확인한다.

    앞의 테스트는 지금 있는 두 경로만 본다. 이 테스트는 나중에 생기는 세 번째 경로를 잡는다.
    """
    writers = [
        path.relative_to(APP_DIR.parent).as_posix()
        for path in sorted(APP_DIR.rglob("*.py"))
        if _SET_WRITE.search(path.read_text(encoding="utf-8"))
        or _INSERT_WRITE.search(path.read_text(encoding="utf-8"))
    ]
    assert writers == [WRITER.relative_to(APP_DIR.parent).as_posix()]
