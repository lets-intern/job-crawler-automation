"""직무 분류 어드민 화면 (4.1.V ~ 4.5.V).

`app/api/ui_companies.py` 와 같은 자리다 — 목록·더하기·고치기·켜기끄기가 한 화면에 있는
CRUD 조각 라우트. 공고 수는 `normalized_jobs.job_major`/`job_minor` 를 세어 얹는다.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api.settings import get_connection
from app.api.ui import NAV_GROUPS
from app.main import app
from app.normalize.engine import insert_normalized

SEED = pathlib.Path(__file__).parent.parent / "seeds" / "job-taxonomy-zighang-20260828.json"


def add_classified_job(
    conn: sqlite3.Connection, seq: int, *, job_major: str | None, job_minor: str | None
) -> None:
    """공고 한 건을 정규화까지 넣고 분류 결과를 얹는다.

    분류 호출을 실제로 돌리지 않는다 — 이 화면이 보는 것은 `normalized_jobs` 에 이미 앉은
    값이지, 그 값을 만드는 과정이 아니다.
    """
    record = {"title": f"공고 {seq}", "body": "본문", "company": "테스트회사"}
    cursor = conn.execute(
        """
        INSERT INTO raw_jobs (workflow_id, source_url, raw_data_json, content_hash)
        VALUES (1, ?, ?, ?)
        """,
        (f"https://x/{seq}", json.dumps(record, ensure_ascii=False), f"hash-{seq}"),
    )
    raw_id = int(cursor.lastrowid or 0)
    normalized_id = insert_normalized(conn, raw_id, [])
    conn.execute(
        "UPDATE normalized_jobs SET job_major = ?, job_minor = ? WHERE id = ?",
        (job_major, job_minor, normalized_id),
    )


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    connection.execute(
        "INSERT INTO crawlers (id, name, list_url, status)"
        " VALUES (1, '테스트', 'https://x', 'draft')"
    )
    connection.execute("INSERT INTO workflows (id, crawler_id, name) VALUES (1, 1, '테스트')")
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

    app.dependency_overrides[get_connection] = request_connection
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_네비게이션에_직무_분류가_있다() -> None:
    group = next(members for path, label, members in NAV_GROUPS if label == "정규화")
    assert ("/taxonomy", "직무 분류") in group


def test_화면이_열리고_네비게이션이_켜진다(client: TestClient) -> None:
    response = client.get("/taxonomy")

    assert response.status_code == 200
    assert '<a href="/taxonomy" aria-current="page"' in response.text
