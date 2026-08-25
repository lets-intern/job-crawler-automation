"""실행 결과를 성공·건너뜀·실패 세 숫자로 낸다 (5.2).

건너뜀은 실패가 아니다. 마감이 지났거나 이미 아는 공고라 상세를 열지 않은 건수이고, 실패는
본문을 못 얻어 저장하지 못한 건수다. 둘을 합치면 마감 날짜 형식이 바뀌어 전부 걸러진 사이트가
"새 공고 0건" 인 정상 실행으로 보인다 (`migrations/0010_run_failures.sql`).

| 확인 | 깨지면 |
|---|---|
| 워크플로우 카드에 세 숫자가 각각 나온다 | 전부 걸러진 사이트가 정상 실행으로 보인다 |
| 건너뜀이 실패 숫자에 합쳐지지 않는다 | 고칠 것이 없는 건수를 고치러 다닌다 |
| 실행 기록이 없는 카드는 그렇다고 적는다 | 빈 칸이 "0건 처리했다" 로 읽힌다 |
| 테스트 실행 요약에도 건너뜀이 있다 | 상세를 안 연 이유가 화면에서 사라진다 |
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import crawlers as crawlers_api
from app.api import workflows as workflows_api
from app.main import app


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    connection.execute(
        "INSERT INTO crawlers (id, name, list_url, status) "
        "VALUES (1, 'LG', 'https://careers.lg.com/apply', 'promoted')"
    )
    connection.execute(
        "INSERT INTO workflows (id, crawler_id, name, status) VALUES (5, 1, 'LG', 'paused')"
    )
    connection.commit()
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

    app.dependency_overrides[workflows_api.get_connection] = request_connection
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def add_run(
    conn: sqlite3.Connection,
    *,
    success: int,
    new: int,
    skipped: int,
    failed: int,
    status: str = "success",
) -> None:
    conn.execute(
        """
        INSERT INTO crawl_runs (workflow_id, started_at, finished_at, status,
                                success_count, new_count, fail_count, skipped_count, trigger)
        VALUES (5, '2026-08-25 00:10:00', '2026-08-25 00:14:00', ?, ?, ?, ?, ?, 'schedule')
        """,
        (status, success, new, failed, skipped),
    )
    conn.commit()


def test_카드에_세_숫자가_각각_나온다(client: TestClient, conn: sqlite3.Connection) -> None:
    """LG 의 실제 실행이다 — 정상 87건, 건너뜀 88건, 실패 0건."""
    add_run(conn, success=87, new=0, skipped=88, failed=0)

    html = client.get("/ui/workflows").text

    assert '정상 <span class="font-semibold tabular-nums">87</span>건' in html
    assert '건너뜀 <span class="font-semibold tabular-nums">88</span>건' in html
    assert ">0</span>건" in html


def test_건너뜀은_실패에_합쳐지지_않는다(client: TestClient, conn: sqlite3.Connection) -> None:
    """합치면 마감이 지나 전부 걸러진 사이트가 실패 88건으로 보인다. 반대도 마찬가지다."""
    add_run(conn, success=0, new=0, skipped=88, failed=0)

    html = client.get("/ui/workflows").text

    assert '건너뜀 <span class="font-semibold tabular-nums">88</span>건' in html
    # 실패 자리는 0 이다. 88 이 실패로 새어 나가면 이 단언이 깨진다
    assert 'text-red-700">88</span>건' not in html


def test_실행_기록이_없으면_그렇게_적는다(client: TestClient) -> None:
    """빈 칸은 "0건 처리했다" 로 읽힌다 (`.claude/rules/writing.md`)."""
    html = client.get("/ui/workflows").text

    assert "끝난 실행이 없다" in html


def test_카드는_실행_번호를_적는다(client: TestClient, conn: sqlite3.Connection) -> None:
    """어느 실행의 건수인지 없으면 그 숫자가 언제 것인지 알 수 없다."""
    add_run(conn, success=1, new=1, skipped=0, failed=0)
    run_id = int(conn.execute("SELECT id FROM crawl_runs").fetchone()["id"])

    html = client.get("/ui/workflows").text

    assert f"실행 {run_id} 의 공고 건수" in html


def test_테스트_실행_요약에도_건너뜀이_있다(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """상세를 안 연 건수가 화면에 없으면 목록 20건에 미리보기 0건인 실행이 설명되지 않는다."""
    connection = db.connect(tmp_path / "screen.db")
    db.migrate_up(connection)
    connection.execute(
        "INSERT INTO crawlers (id, name, list_url) VALUES (1, 'LG', 'https://careers.lg.com/apply')"
    )
    connection.commit()

    async def fake_run(*args: object, **kwargs: object) -> crawlers_api.TestRunOut:
        return crawlers_api.TestRunOut(
            crawler_id=1,
            run_id=42,
            status="success",
            crawler_status="tested",
            render_mode="api",
            saved_render_mode="api",
            matched=20,
            success_count=3,
            new_count=1,
            fail_count=2,
            skipped_count=15,
            error_class=None,
            error_message="",
            items=[],
            failures=[],
        )

    monkeypatch.setattr(crawlers_api, "test_run", fake_run)

    def request_connection() -> Iterator[sqlite3.Connection]:
        conn = db.connect(tmp_path / "screen.db")
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[crawlers_api.get_connection] = request_connection
    try:
        html = TestClient(app).post("/ui/crawlers/1/test-run", data={"limit": "3"}).text
    finally:
        app.dependency_overrides.clear()
        connection.close()

    assert "건너뜀" in html
    assert "15건" in html
    assert "3건" in html
    assert "2건" in html
