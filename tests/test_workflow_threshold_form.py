"""카드에서 자동 중지 임계치를 정한다 (18.3).

`auto_stop_threshold` 컬럼과 자동 중지 판정은 Push 4 에 이미 있었다. 없던 것은 화면이다 —
카드에 `임계치 없음` 만 있고 값을 정할 수단이 없어, 실패가 쌓여도 아무도 멈추지 않았다.

| 확인 | 깨지면 |
|---|---|
| 저장한 임계치가 다시 조회해도 남는다 | 정했다고 적어 놓고 다음 실행이 그대로 돈다 |
| 비우고 저장하면 자동 중지가 꺼진다 | 임계치를 끄는 방법이 없어 DB 를 손으로 고쳐야 한다 |
| 0·음수·정수 아닌 값은 그 자리에서 거절된다 | 잘못된 값이 저장되고 자동 중지가 조용히 죽는다 |
| 연속 실패 횟수를 함께 보여준다 | 임계치에 얼마나 가까운지 모르는 채 숫자를 정한다 |
| 자동 중지된 워크플로우는 그 사실이 카드에 남는다 | 왜 안 도는지를 다른 데서 찾는다 |
| 주기·중지·재개는 임계치를 건드리지 않는다 | 주기를 바꿨더니 임계치가 지워진다 |
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi.testclient import TestClient

from app import db
from app.api import workflows as workflows_api
from app.main import app
from app.scheduler import WorkflowScheduler

LIST_URL = "https://recruit.example.co.kr/hire/main/list"


@pytest.fixture
def db_path(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path / "jobs.db"


@pytest.fixture
def conn(db_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(db_path)
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
def client(
    db_path: pathlib.Path, conn: sqlite3.Connection, scheduler: WorkflowScheduler
) -> Iterator[TestClient]:
    def request_connection() -> Iterator[sqlite3.Connection]:
        connection = db.connect(db_path)
        try:
            yield connection
        finally:
            connection.close()

    app.dependency_overrides[workflows_api.get_connection] = request_connection
    app.dependency_overrides[workflows_api.get_workflow_scheduler] = lambda: scheduler
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def add_workflow(
    conn: sqlite3.Connection, *, threshold: int | None = None, status: str = "active"
) -> int:
    cursor = conn.execute(
        "INSERT INTO crawlers (name, list_url, status) VALUES (?, ?, 'promoted')",
        ("예시 채용", LIST_URL),
    )
    crawler_id = int(cursor.lastrowid or 0)
    cursor = conn.execute(
        """
        INSERT INTO workflows (crawler_id, name, interval_minutes, status, auto_stop_threshold)
        VALUES (?, ?, 30, ?, ?)
        """,
        (crawler_id, "예시 채용", status, threshold),
    )
    return int(cursor.lastrowid or 0)


def add_failures(conn: sqlite3.Connection, workflow_id: int, count: int) -> None:
    for _ in range(count):
        conn.execute(
            """
            INSERT INTO crawl_runs (workflow_id, finished_at, status, error_class,
                                    error_message, trigger)
            VALUES (?, datetime('now'), 'failed', 'selector_miss', '0개를 잡았다', 'schedule')
            """,
            (workflow_id,),
        )


def threshold_of(conn: sqlite3.Connection, workflow_id: int) -> int | None:
    row = conn.execute(
        "SELECT auto_stop_threshold FROM workflows WHERE id = ?", (workflow_id,)
    ).fetchone()
    value = row["auto_stop_threshold"]
    return None if value is None else int(value)


def test_카드에_임계치_입력칸이_있다(client: TestClient, conn: sqlite3.Connection) -> None:
    add_workflow(conn, threshold=3)

    html = client.get("/ui/workflows").text

    assert 'name="auto_stop_threshold"' in html
    assert 'value="3"' in html
    assert "임계치 저장" in html


def test_저장한_임계치가_재조회해도_남는다(client: TestClient, conn: sqlite3.Connection) -> None:
    workflow_id = add_workflow(conn)

    saved = client.patch(
        f"/ui/workflows/{workflow_id}/threshold", data={"auto_stop_threshold": "3"}
    ).text

    assert "임계치를 연속 실패 3회로 정했다" in saved
    assert threshold_of(conn, workflow_id) == 3
    assert "정상 (연속 실패 0회 / 임계치 3회)" in client.get("/ui/workflows").text


def test_비우고_저장하면_자동_중지가_꺼진다(client: TestClient, conn: sqlite3.Connection) -> None:
    """빈 값은 "안 바꾼다" 가 아니라 "자동으로 멈추지 않는다" 다. 끄는 유일한 방법이다.

    브라우저는 빈 입력칸을 `auto_stop_threshold=` 로 보낸다. 그대로 흉내낸다.
    """
    workflow_id = add_workflow(conn, threshold=3)

    cleared = client.patch(
        f"/ui/workflows/{workflow_id}/threshold", data={"auto_stop_threshold": ""}
    ).text

    assert "임계치를 지웠다" in cleared
    assert threshold_of(conn, workflow_id) is None
    assert "임계치 없음" in cleared


@pytest.mark.parametrize("value", ["0", "-1", "2.5", "세 번"])
def test_1_미만이거나_정수가_아니면_그_자리에서_거절한다(
    client: TestClient, conn: sqlite3.Connection, value: str
) -> None:
    workflow_id = add_workflow(conn, threshold=3)

    html = client.patch(
        f"/ui/workflows/{workflow_id}/threshold", data={"auto_stop_threshold": value}
    ).text

    assert "임계치는 1 이상의 정수여야 한다" in html
    # 거절은 저장하지 않는다는 뜻이다. 지금 값이 그대로 남아야 한다
    assert threshold_of(conn, workflow_id) == 3


def test_지금_연속_실패가_몇_회인지_함께_보인다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """임계치에 얼마나 가까운지 알아야 숫자를 정할 수 있다."""
    workflow_id = add_workflow(conn, threshold=5)
    add_failures(conn, workflow_id, 2)

    html = client.get("/ui/workflows").text

    assert "정상 (연속 실패 2회 / 임계치 5회)" in html


def test_임계치를_넘겨_멈춘_워크플로우는_그_사실이_카드에_남는다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    workflow_id = add_workflow(conn, threshold=2, status="paused")
    add_failures(conn, workflow_id, 2)

    html = client.get("/ui/workflows").text

    assert "자동 중지됨" in html
    assert "연속 실패 2회가 임계치 2회에 닿아 멈춘 상태다" in html


def test_아직_임계치에_닿지_않았으면_자동_중지_줄이_없다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """손으로 멈춘 워크플로우를 자동 중지로 읽지 않는다."""
    workflow_id = add_workflow(conn, threshold=5, status="paused")
    add_failures(conn, workflow_id, 1)

    html = client.get("/ui/workflows").text

    assert "자동 중지됨" not in html


def test_주기_변경과_중지는_임계치를_건드리지_않는다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    workflow_id = add_workflow(conn, threshold=3)

    client.patch(f"/ui/workflows/{workflow_id}", data={"interval_minutes": "60"})
    assert threshold_of(conn, workflow_id) == 3

    client.patch(f"/ui/workflows/{workflow_id}", data={"status": "paused"})
    assert threshold_of(conn, workflow_id) == 3


def test_API_도_임계치를_바꾼다(client: TestClient, conn: sqlite3.Connection) -> None:
    """화면이 부르는 것과 같은 라우트다. 화면에서만 되는 조작을 만들지 않는다."""
    workflow_id = add_workflow(conn)

    response = client.patch(f"/api/workflows/{workflow_id}", json={"auto_stop_threshold": 4})

    assert response.status_code == 200
    assert response.json()["auto_stop_threshold"] == 4
    assert (
        client.patch(f"/api/workflows/{workflow_id}", json={"auto_stop_threshold": 0}).status_code
        == 422
    )
    assert threshold_of(conn, workflow_id) == 4
