"""실행 하나가 놓친 공고를 화면에 낸다 (5.3).

`fail_count = 3` 은 무엇을 하라는 말이 아니다. 어느 공고가 어떤 사유로 빠졌는지와 목록에서
읽은 주소가 있어야 그 주소를 열어 보고 고칠 수 있다 (`migrations/0010_run_failures.sql`).

| 확인 | 깨지면 |
|---|---|
| 사유·제목·주소·메시지가 한 줄에 있다 | 건수만 알고 고칠 수는 없는 화면이 된다 |
| 사유마다 다음 행동이 붙는다 | `detail_empty` 를 보고 어디를 고칠지 모른다 |
| 실패 0건은 무엇이 정상인지 적는다 | 빈 화면이 "안 눌렸다" 로 읽힌다 |
| 분류를 모르는 실패도 줄이 남는다 | 모르는 실패가 화면에서 사라진다 |
| 테스트 실행 화면이 같은 표를 쓴다 | 같은 실패가 두 화면에서 다르게 읽힌다 |
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import crawlers as crawlers_api
from app.api import ui
from app.api import workflows as workflows_api
from app.api.ui_runs import FAILURE_LIMIT
from app.main import app


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    connection.execute(
        "INSERT INTO crawlers (id, name, list_url, status) "
        "VALUES (1, '삼성', 'https://www.samsungcareers.com/hr/', 'promoted')"
    )
    connection.execute(
        "INSERT INTO workflows (id, crawler_id, name, status) VALUES (3, 1, '삼성', 'paused')"
    )
    connection.execute(
        """
        INSERT INTO crawl_runs (id, workflow_id, started_at, finished_at, status,
                                success_count, new_count, fail_count, skipped_count, trigger)
        VALUES (7, 3, '2026-08-25 00:10:00', '2026-08-25 00:14:00', 'success',
                14, 2, 2, 0, 'schedule')
        """
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

    app.dependency_overrides[crawlers_api.get_connection] = request_connection
    app.dependency_overrides[workflows_api.get_connection] = request_connection
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def add_failure(
    conn: sqlite3.Connection,
    *,
    reason: str | None,
    title: str,
    source_url: str,
    message: str,
    run_id: int = 7,
) -> None:
    conn.execute(
        """
        INSERT INTO crawl_run_failures (run_id, reason, title, source_url, message)
        VALUES (?, ?, ?, ?, ?)
        """,
        (run_id, reason, title, source_url, message),
    )
    conn.commit()


def test_사유와_제목과_주소가_한_줄에_있다(client: TestClient, conn: sqlite3.Connection) -> None:
    """건수만으로는 고칠 수 없다. 어느 공고였는지가 있어야 그 주소를 열어 본다."""
    add_failure(
        conn,
        reason="detail_empty",
        title="반도체 공정개발",
        source_url="https://www.samsungcareers.com/recruit/detail?seqno=22878",
        message="상세는 열렸는데 본문이 비었다",
    )

    html = client.get("/ui/runs/7/failures").text

    assert "본문이 비었음" in html
    assert "detail_empty" in html
    assert "반도체 공정개발" in html
    assert "https://www.samsungcareers.com/recruit/detail?seqno=22878" in html
    assert "상세는 열렸는데 본문이 비었다" in html


def test_사유마다_다음_행동이_붙는다(client: TestClient, conn: sqlite3.Connection) -> None:
    """사유 이름만 보고는 목록 셀렉터를 고칠지 상세 셀렉터를 고칠지 알 수 없다."""
    add_failure(
        conn,
        reason="detail_unreachable",
        title="플랜트 설계",
        source_url="https://www.samsungcareers.com/hr/",
        message="링크·속성·클릭 어느 것으로도 상세에 못 갔다",
    )

    html = client.get("/ui/runs/7/failures").text

    assert ui.NEXT_STEPS["detail_unreachable"] in html


def test_실패가_없으면_무엇이_정상인지_적는다(client: TestClient) -> None:
    """ "없음" 으로 끝내면 눌렸는지 실패가 없는 것인지 알 수 없다."""
    html = client.get("/ui/runs/7/failures").text

    assert "놓친 공고는 없다" in html
    assert "본문까지 왔다" in html


def test_분류를_모르는_실패도_줄이_남는다(client: TestClient, conn: sqlite3.Connection) -> None:
    """모르는 실패를 아는 실패로 위장하지 않는다. 대신 화면에서 지우지도 않는다."""
    add_failure(
        conn,
        reason=None,
        title="이름 모를 공고",
        source_url="https://www.samsungcareers.com/hr/",
        message="KeyError 가 났다. 분류를 정하지 못했다",
    )

    html = client.get("/ui/runs/7/failures").text

    assert "분류 없음" in html
    assert "KeyError 가 났다" in html


def test_실패가_많으면_앞부분만_그리고_전체_건수를_적는다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """수백 줄짜리 표는 열자마자 읽기를 포기하게 된다. 몇 건 중 몇 건인지 적는다."""
    for index in range(FAILURE_LIMIT + 5):
        add_failure(
            conn,
            reason="transport",
            title=f"공고 {index}",
            source_url=f"https://www.samsungcareers.com/hr/{index}",
            message="타임아웃",
        )

    html = client.get("/ui/runs/7/failures").text

    assert f"놓친 공고 {FAILURE_LIMIT + 5}건" in html
    assert f"앞 {FAILURE_LIMIT}건만 그린다" in html
    assert "공고 0" in html
    assert f"공고 {FAILURE_LIMIT + 4}" not in html


def test_워크플로우_카드가_실패_목록을_여는_자리를_준다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """고칠 대상을 보려고 화면을 옮겨 다니지 않게 카드 안에서 연다."""
    add_failure(
        conn,
        reason="transport",
        title="플랜트 설계",
        source_url="https://www.samsungcareers.com/hr/",
        message="타임아웃",
    )

    html = client.get("/ui/workflows").text

    assert 'hx-get="/ui/runs/7/failures"' in html
    assert "실패한 공고 보기" in html
    assert 'id="run-failures-3"' in html


def test_실패가_없는_카드는_여는_버튼을_내밀지_않는다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """누를 것이 없는 버튼은 안내가 아니다. 실패 0건이면 열 표도 없다."""
    conn.execute("UPDATE crawl_runs SET fail_count = 0 WHERE id = 7")
    conn.commit()

    html = client.get("/ui/workflows").text

    assert "실패한 공고 보기" not in html
