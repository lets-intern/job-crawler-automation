"""워크플로우 카드가 지켜야 하는 구조 (16.3).

폭은 브라우저가 정하므로 여기서 재지 않는다. 대신 그 폭을 만드는 구조를 지킨다 — 열 열 개짜리
표로 돌아가면 좁은 화면에서 오른쪽 값이 다시 가로 스크롤 안으로 들어간다.

| 지키는 것 | 깨지면 |
|---|---|
| 목록이 표도 가로 스크롤 상자도 쓰지 않는다 | 임계치가 다시 화면 밖으로 나간다 |
| 상태·최근 결과·누적 성공·누적 실패·임계치가 카드 하나에 있다 | 한눈에 들어와야 할 값이 흩어진다 |
| 쌓인 실패에 색과 함께 단어가 붙는다 | 색을 못 보면 실패한 워크플로우가 보이지 않는다 |
| 최근 실패 사유가 카드에 있다 | 어느 단계가 왜 실패했는지 다른 화면을 열어야 안다 |

2026-08-22 측정(Chromium, 문서 폭 = 뷰포트 폭): 1280px 에서 1280, 1440px 에서 1440.
가로 스크롤 없음.
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import workflows as workflows_api
from app.main import app

LIST_URL = "https://recruit.example.co.kr/hire/main/list?srchClassCd=100&srchJobCd=1000&page=1"


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
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


def add_workflow(
    conn: sqlite3.Connection,
    *,
    name: str = "예시 채용",
    threshold: int | None = None,
    success_count: int = 0,
    fail_count: int = 0,
) -> int:
    cursor = conn.execute(
        "INSERT INTO crawlers (name, list_url, status) VALUES (?, ?, 'promoted')",
        (name, LIST_URL),
    )
    crawler_id = int(cursor.lastrowid or 0)
    cursor = conn.execute(
        """
        INSERT INTO workflows (crawler_id, name, interval_minutes, status,
                               auto_stop_threshold, success_count, fail_count, last_run_at)
        VALUES (?, ?, 360, 'active', ?, ?, ?, datetime('now'))
        """,
        (crawler_id, name, threshold, success_count, fail_count),
    )
    return int(cursor.lastrowid or 0)


def add_run(
    conn: sqlite3.Connection,
    workflow_id: int,
    *,
    status: str,
    error_class: str | None = None,
    error_message: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO crawl_runs (workflow_id, finished_at, status, error_class, error_message)
        VALUES (?, datetime('now'), ?, ?, ?)
        """,
        (workflow_id, status, error_class, error_message),
    )


def test_목록이_표도_가로_스크롤_상자도_쓰지_않는다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """열이 열 개였을 때 오른쪽 값이 스크롤 안쪽으로 들어갔다. 그 구조로 돌아가지 않는다."""
    add_workflow(conn)

    html = client.get("/ui/workflows").text

    assert "<table" not in html
    assert "table-scroll" not in html
    assert '<article id="workflow-row-' in html


def test_한_카드에_상태와_최근_결과와_누적과_임계치가_같이_있다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    workflow_id = add_workflow(conn, threshold=3, success_count=7, fail_count=2)
    add_run(conn, workflow_id, status="success")

    html = client.get("/ui/workflows").text

    assert "실행 중" in html  # 상태
    assert "최근 실행" in html
    assert "성공" in html  # 최근 결과
    assert "누적 성공" in html
    assert "7회" in html
    assert "누적 실패" in html
    assert "2회" in html
    assert "정상 (연속 실패 0회 / 임계치 3회)" in html


def test_쌓인_실패는_색이_아니라_단어로도_구분된다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """색만으로 구분하면 색을 못 보는 경우 정보가 사라진다 (`.claude/rules/writing.md`)."""
    workflow_id = add_workflow(conn, fail_count=2)
    add_run(conn, workflow_id, status="failed", error_class="selector_miss", error_message="0개")
    add_run(conn, workflow_id, status="failed", error_class="selector_miss", error_message="0개")

    html = client.get("/ui/workflows").text

    assert "연속 실패 2회" in html  # 배지에 붙는 단어
    assert "임계치 없음 (연속 실패 2회)" in html
    assert "border-red-300" in html  # 색은 단어에 더해서만 쓴다


def test_임계치를_넘기면_초과라고_적는다(client: TestClient, conn: sqlite3.Connection) -> None:
    workflow_id = add_workflow(conn, threshold=2, fail_count=2)
    add_run(conn, workflow_id, status="failed", error_class="transport", error_message="시간 초과")
    add_run(conn, workflow_id, status="failed", error_class="transport", error_message="시간 초과")

    html = client.get("/ui/workflows").text

    assert "임계치 초과 (연속 실패 2회)" in html
    assert "초과 (연속 실패 2회 / 임계치 2회)" in html


def test_최근_실패_사유가_카드에_그대로_있다(client: TestClient, conn: sqlite3.Connection) -> None:
    workflow_id = add_workflow(conn, fail_count=1)
    add_run(
        conn,
        workflow_id,
        status="failed",
        error_class="selector_miss",
        error_message="목록 셀렉터가 0개를 잡았다: ol.list > li",
    )

    html = client.get("/ui/workflows").text

    assert "최근 실패 사유" in html
    assert "selector_miss" in html
    assert "목록 셀렉터가 0개를 잡았다: ol.list &gt; li" in html


def test_성공으로_끝난_워크플로우에는_사유_줄이_없다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """지난 실패가 남아 있어도, 마지막이 성공이면 그것이 지금의 사실이다."""
    workflow_id = add_workflow(conn, success_count=1, fail_count=1)
    add_run(conn, workflow_id, status="failed", error_class="transport", error_message="끊김")
    add_run(conn, workflow_id, status="success")

    html = client.get("/ui/workflows").text

    assert "최근 실패 사유" not in html
    # 배지와 임계치 칸이 세는 값이다. 임계치 입력칸의 이름(18.3)에도 같은 말이 들어가므로
    # 문구 조각이 아니라 실제로 세어진 횟수가 없는지를 본다
    assert "연속 실패 1회" not in html
    assert "누적 실패" in html  # 누적은 남는다. 값을 지우지 않는다
