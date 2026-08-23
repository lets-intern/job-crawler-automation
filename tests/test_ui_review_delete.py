"""검수 화면에서 공고를 골라 지우기 (27.1 ~ 27.4).

실사이트에 나가지 않는다. 저장된 행을 넣고 화면 경로로만 고르고 지운다.

`raw_jobs` 는 다시 만들 수 없다. 마감된 공고는 사이트에서 이미 내려가 다시 수집되지 않으므로,
지우기 전에 무엇이 몇 건 사라지는지가 화면에 숫자로 나와 있어야 한다.

| 확인 | 깨지면 |
|---|---|
| 행마다 체크박스가 있고 표를 지우기 폼이 감싼다 | 고를 방법이 없다 |
| 머리칸 체크박스는 이 페이지에 보이는 것만 고른다 | 20건인 줄 알고 148건을 지운다 |
| `필터 전체` 는 조건에 걸린 수를 글자와 숫자로 밝힌다 | 무엇을 고른 것인지 화면에서 알 수 없다 |
| 아무것도 고르지 않으면 지우기 단추가 눌리지 않는다 | 빈 요청이 확인 창을 연다 |
| 확인 창이 세 표에서 사라질 행 수를 각각 보여준다 | 보정과 정규화 행이 조용히 함께 사라진다 |
| 브라우저 confirm() 을 쓰지 않는다 | 자동화 세션이 멈춘다 |
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import crawlers as crawlers_api
from app.main import app

LIST_URL = "https://www.python.org/jobs/"


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    """워크플로우 둘에 공고 다섯. 하나는 이미 전달됐고 하나는 사람 보정이 붙어 있다."""
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    connection.execute(
        "INSERT INTO crawlers (name, list_url, status) VALUES ('python.org', ?, 'promoted')",
        (LIST_URL,),
    )
    connection.execute(
        "INSERT INTO crawlers (name, list_url, status) VALUES ('example', ?, 'promoted')",
        ("https://example.com/jobs/",),
    )
    connection.execute("INSERT INTO workflows (crawler_id, name) VALUES (1, 'python.org 채용')")
    connection.execute("INSERT INTO workflows (crawler_id, name) VALUES (2, 'example 채용')")
    for raw_job_id, workflow_id, company, title in (
        (1, 1, "파이썬재단", "백엔드 개발자"),
        (2, 1, "파이썬재단", "프론트 개발자"),
        (3, 1, "다른회사", "데이터 엔지니어"),
        (4, 2, "이그잼플", "안드로이드 개발자"),
        (5, 2, "이그잼플", "iOS 개발자"),
    ):
        connection.execute(
            """
            INSERT INTO raw_jobs (id, workflow_id, source_url, raw_data_json, content_hash)
            VALUES (?, ?, ?, '{}', ?)
            """,
            (raw_job_id, workflow_id, f"{LIST_URL}{raw_job_id}/", f"hash-{raw_job_id}"),
        )
        connection.execute(
            """
            INSERT INTO normalized_jobs (raw_job_id, company, title, source_url)
            VALUES (?, ?, ?, ?)
            """,
            (raw_job_id, company, title, f"{LIST_URL}{raw_job_id}/"),
        )
    connection.execute(
        "UPDATE normalized_jobs SET delivered_at = datetime('now') WHERE raw_job_id = 2"
    )
    connection.execute(
        "INSERT INTO job_field_overrides (raw_job_id, field_name, value)"
        " VALUES (1, 'company', '파이썬 소프트웨어 재단')"
    )
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
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def counts(conn: sqlite3.Connection) -> tuple[int, int, int]:
    """세 표의 행 수. 지우기는 셋을 한꺼번에 비워야 한다."""
    return (
        int(conn.execute("SELECT count(*) FROM raw_jobs").fetchone()[0]),
        int(conn.execute("SELECT count(*) FROM normalized_jobs").fetchone()[0]),
        int(conn.execute("SELECT count(*) FROM job_field_overrides").fetchone()[0]),
    )


def raw_ids(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute("SELECT id FROM raw_jobs ORDER BY id").fetchall()
    return [int(row["id"]) for row in rows]


def test_행마다_체크박스가_있고_지우기_폼이_표를_감싼다(client: TestClient) -> None:
    html = client.get("/ui/review").text

    assert 'id="review-select-form"' in html
    assert 'hx-post="/ui/review/delete/confirm"' in html
    for raw_job_id in (1, 2, 3, 4, 5):
        assert f'name="raw_job_id" value="{raw_job_id}"' in html
    # 지금 걸린 조회 조건이 폼과 함께 간다. `필터 전체` 가 화면과 같은 조건이어야 한다
    assert 'name="workflow_id"' in html
    assert 'name="company"' in html


def test_전체_선택이_무엇을_고르는지_글자로_밝힌다(client: TestClient) -> None:
    """`이 페이지 20건` 과 `필터에 걸린 148건` 은 다르다. 둘을 각각 이름으로 적는다."""
    html = client.get("/ui/review").text

    assert "이 페이지 5건 모두 고르기" in html
    assert "필터에 걸린 5건 전체 고르기" in html
    assert 'data-total="5"' in html
    # 고른 수를 늘 적는 자리
    assert 'id="review-select-count"' in html


def test_아무것도_고르지_않으면_지우기_단추가_눌리지_않는다(client: TestClient) -> None:
    html = client.get("/ui/review").text

    opener = html[
        html.index('id="review-delete-open"') : html.index('id="review-delete-open"') + 400
    ]
    assert "disabled" in opener


def test_필터를_걸면_전체_선택의_수가_그_조건의_수로_바뀐다(client: TestClient) -> None:
    html = client.get("/ui/review", params={"workflow_id": "2"}).text

    assert "필터에 걸린 2건 전체 고르기" in html
    assert 'data-total="2"' in html


def test_확인_창이_세_표에서_사라질_행_수를_각각_보여준다(client: TestClient) -> None:
    response = client.post(
        "/ui/review/delete/confirm",
        data={"raw_job_id": ["1", "2"], "workflow_id": "", "company": "", "q": ""},
    )

    assert response.status_code == 200
    html = response.text
    assert "raw_jobs" in html and "2건" in html
    assert "normalized_jobs" in html
    assert "job_field_overrides" in html
    # 브라우저 모달은 자동화 세션을 멈춘다. 이 저장소는 <dialog> 를 쓴다
    assert "hx-confirm" not in html


def test_확인_창이_고른_범위를_글자로_적는다(client: TestClient) -> None:
    picked = client.post(
        "/ui/review/delete/confirm",
        data={"raw_job_id": ["1"], "workflow_id": "", "company": "", "q": ""},
    ).text
    whole = client.post(
        "/ui/review/delete/confirm",
        data={"all_filtered": "1", "workflow_id": "1", "company": "", "q": ""},
    ).text

    assert "표에서 고른 공고" in picked
    assert "지금 조회 조건에 걸린 전부" in whole
    # 필터 전체는 체크박스가 보낸 id 가 아니라 조건으로 다시 센다
    assert "3건" in whole


def test_이미_사라진_id_를_보내도_그_수가_늘지_않는다(client: TestClient) -> None:
    response = client.post(
        "/ui/review/delete/confirm",
        data={"raw_job_id": ["1", "999"], "workflow_id": "", "company": "", "q": ""},
    )

    assert "1건" in response.text
