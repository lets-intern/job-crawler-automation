"""화면에서의 지금 1회 실행 테스트 (15.3).

실사이트에 나가지 않는다. fetch 클라이언트를 저장된 python.org 픽스처를 돌려주는 스텁으로
갈아끼우고, 확인하는 것은 `crawl_runs` 행과 `raw_jobs` 적재, 그리고 갈린 조각이다.

| 확인 | 깨지면 |
|---|---|
| 실행이 `crawl_runs` 와 `raw_jobs` 를 남긴다 | 화면이 실행했다고 적고 아무것도 안 남는다 |
| 갈리는 것은 누른 워크플로우 하나뿐이다 | 다른 워크플로우에 입력하던 주기가 같이 날아간다 |
| 진행 중이면 새로 시작하지 않는다 | 같은 워크플로우의 실행 둘이 같은 사이트를 동시에 때린다 |
| 상한이 차 있으면 시작하지 않는다 | 상한이 화면 경로에서만 무시된다 |
| 실패는 사유까지 적는다 | 실패가 조용히 지나가 무엇을 고쳐야 하는지 알 수 없다 |
"""

from __future__ import annotations

import json
import pathlib
import re
import sqlite3
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Request
from fastapi.testclient import TestClient

from app import db
from app.api import crawlers as crawlers_api
from app.api import ui_workflows
from app.api import workflows as workflows_api
from app.config import Settings
from app.crawler.fetcher import Fetcher
from app.main import app
from app.scheduler import RunGate, WorkflowScheduler

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
LIST_HTML = (FIXTURES / "pythonorg-jobs-list-20260821.html").read_text(encoding="utf-8")
DETAIL_HTML = (FIXTURES / "pythonorg-job-detail-20260821.html").read_text(encoding="utf-8")

LIST_URL = "https://www.python.org/jobs/"
ROBOTS = "User-agent: *\nDisallow:\n"

SELECTORS: dict[str, Any] = {
    "list": {
        "item": "ol.list-recent-jobs > li",
        "title": "span.listing-company-name > a",
        "link": "span.listing-company-name > a",
        "date": "span.listing-posted time",
    },
    "detail": {
        "title": "h1.listing-company span.company-name",
        "body": "div.job-description",
        "requirements": "",
        "deadline": "",
        "department": "span.listing-company-category a",
    },
}

MISSING_SELECTORS: dict[str, Any] = {
    "list": {"item": "ol.nothing-here > li", "title": "a", "link": "a", "date": "time"},
    "detail": {"title": "h1", "body": "div", "requirements": "", "deadline": "", "department": ""},
}


def stub_fetcher() -> Fetcher:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        if request.url.path == "/jobs/":
            return httpx.Response(200, text=LIST_HTML)
        return httpx.Response(200, text=DETAIL_HTML)

    async def no_wait(seconds: float) -> None:
        return None

    return Fetcher(
        settings=Settings(crawl_delay_seconds=0.0, crawl_max_retries=0),
        transport=httpx.MockTransport(handle),
        sleep=no_wait,
    )


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def scheduler() -> Iterator[WorkflowScheduler]:
    async def do_nothing(workflow_id: int) -> None:
        return None

    instance = WorkflowScheduler(scheduler=AsyncIOScheduler(timezone="UTC"), runner=do_nothing)
    try:
        yield instance
    finally:
        instance.shutdown()


@pytest.fixture
def gate() -> RunGate:
    """상한 2 짜리 문. 전역 문을 쓰면 상한을 운영 DB 에서 읽는다."""
    return RunGate(lambda: 2)


@pytest.fixture
def client(
    tmp_path: pathlib.Path,
    conn: sqlite3.Connection,
    scheduler: WorkflowScheduler,
    gate: RunGate,
) -> Iterator[TestClient]:
    def request_connection() -> Iterator[sqlite3.Connection]:
        connection = db.connect(tmp_path / "jobs.db")
        try:
            yield connection
        finally:
            connection.close()

    fetcher = stub_fetcher()
    app.dependency_overrides[workflows_api.get_connection] = request_connection
    app.dependency_overrides[crawlers_api.get_connection] = request_connection
    app.dependency_overrides[crawlers_api.get_crawl_fetcher] = lambda: fetcher
    app.dependency_overrides[workflows_api.get_workflow_scheduler] = lambda: scheduler
    app.dependency_overrides[ui_workflows.get_run_gate] = lambda: gate
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def add_workflow(
    conn: sqlite3.Connection,
    name: str = "python.org 채용",
    selectors: dict[str, Any] | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO crawlers (name, list_url, detail_url, selectors_json, status)
        VALUES (?, ?, ?, ?, 'promoted')
        """,
        (
            name,
            LIST_URL,
            "https://www.python.org/jobs/8126/",
            json.dumps(SELECTORS if selectors is None else selectors),
        ),
    )
    crawler_id = int(cursor.lastrowid or 0)
    cursor = conn.execute(
        """
        INSERT INTO workflows (crawler_id, name, interval_minutes, status)
        VALUES (?, ?, 360, 'active')
        """,
        (crawler_id, name),
    )
    return int(cursor.lastrowid or 0)


def rows_in(html: str) -> list[str]:
    return re.findall(r'<article id="workflow-row-(\d+)"', html)


def counts(conn: sqlite3.Connection, workflow_id: int) -> tuple[int, int]:
    runs = conn.execute(
        "SELECT COUNT(*) AS n FROM crawl_runs WHERE workflow_id = ?", (workflow_id,)
    ).fetchone()["n"]
    jobs = conn.execute(
        "SELECT COUNT(*) AS n FROM raw_jobs WHERE workflow_id = ?", (workflow_id,)
    ).fetchone()["n"]
    return int(runs), int(jobs)


def test_1회_실행이_crawl_runs_와_raw_jobs_를_남긴다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    workflow_id = add_workflow(conn)

    html = client.post(f"/ui/workflows/{workflow_id}/run").text

    runs, jobs = counts(conn, workflow_id)
    assert runs == 1
    assert jobs > 0

    run = conn.execute("SELECT * FROM crawl_runs WHERE workflow_id = ?", (workflow_id,)).fetchone()
    assert run["status"] == "success"
    assert run["finished_at"] is not None
    assert f"1회 실행 {run['id']}: 성공" in html
    assert f"신규 {jobs}건" in html


def test_실행_뒤에_그_카드의_최근_실행과_카운트가_갱신된다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    workflow_id = add_workflow(conn)
    other = add_workflow(conn, name="다른 워크플로우")

    html = client.post(f"/ui/workflows/{workflow_id}/run").text

    # 갈리는 것은 누른 워크플로우 하나뿐이다
    assert rows_in(html) == [str(workflow_id)]
    assert str(other) not in rows_in(html)

    row = conn.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
    assert (row["success_count"], row["fail_count"]) == (1, 0)
    assert row["last_run_at"] is not None
    # 최근 실행과 최근 결과가 이 조각에서 이미 갱신돼 있다. 새로고침을 눌러야 보이면 안 된다
    assert "실행 기록 없음" not in html
    assert '<span class="state-ok">성공</span>' in html
    assert counts(conn, other) == (0, 0)


def test_이미_실행_중이면_새로_시작하지_않는다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """스케줄러의 tick 스킵과 같은 판단이다. 끝나지 않은 실행은 `status` 가 비어 있다."""
    workflow_id = add_workflow(conn)
    conn.execute("INSERT INTO crawl_runs (workflow_id) VALUES (?)", (workflow_id,))

    html = client.post(f"/ui/workflows/{workflow_id}/run").text

    assert "이미 실행 중이다" in html
    runs, jobs = counts(conn, workflow_id)
    assert runs == 1  # 심어 둔 그 행 하나뿐이다
    assert jobs == 0


async def test_상한이_차_있으면_기다리지_않고_건너뛴다(
    conn: sqlite3.Connection, scheduler: WorkflowScheduler
) -> None:
    """화면은 문 앞에서 기다리지 않는다. 기다리면 누른 사람이 몇 분 동안 답을 못 받는다."""
    workflow_id = add_workflow(conn)
    gate = RunGate(lambda: 1)
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})

    async with gate.slot():
        response = await ui_workflows.run_now_fragment(
            request=request,
            workflow_id=workflow_id,
            conn=conn,
            scheduler=scheduler,
            fetcher=stub_fetcher(),
            gate=gate,
        )

    html = bytes(response.body).decode()
    assert "동시 실행 상한(1)에 걸렸다" in html
    assert counts(conn, workflow_id) == (0, 0)


def test_실패한_실행은_사유까지_적는다(client: TestClient, conn: sqlite3.Connection) -> None:
    workflow_id = add_workflow(conn, selectors=MISSING_SELECTORS)

    html = client.post(f"/ui/workflows/{workflow_id}/run").text

    assert "실패" in html
    assert "selector_miss" in html
    run = conn.execute(
        "SELECT status, error_class FROM crawl_runs WHERE workflow_id = ?", (workflow_id,)
    ).fetchone()
    assert run["status"] == "failed"
    assert run["error_class"] == "selector_miss"


def test_없는_워크플로우는_실행하지_않는다(client: TestClient, conn: sqlite3.Connection) -> None:
    html = client.post("/ui/workflows/999/run").text

    assert "워크플로우 999 가 없다" in html
    assert conn.execute("SELECT COUNT(*) AS n FROM crawl_runs").fetchone()["n"] == 0
