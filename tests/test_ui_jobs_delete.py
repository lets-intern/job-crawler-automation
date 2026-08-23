"""데이터 조회 화면에서 공고를 골라 지우기 (27.6 ~ 27.8).

실사이트에 나가지 않는다. 저장된 행을 넣고 화면 경로로만 고르고 지운다.

`raw_jobs` 는 다시 만들 수 없다. 마감된 공고는 사이트에서 이미 내려가 다시 수집되지 않으므로,
지우기 전에 무엇이 몇 건 사라지는지가 화면에 숫자로 나와 있어야 한다.

| 확인 | 깨지면 |
|---|---|
| 행마다 체크박스가 있고 표를 지우기 폼이 감싼다 | 고를 방법이 없다 |
| 머리칸 체크박스는 화면에 보이는 것만 고른다 | 100건인 줄 알고 148건을 지운다 |
| `필터 전체` 는 조건에 걸린 수를 글자와 숫자로 밝힌다 | 무엇을 고른 것인지 화면에서 알 수 없다 |
| 아무것도 고르지 않으면 지우기 단추가 눌리지 않는다 | 빈 요청이 확인 창을 연다 |
| 확인 창이 세 표에서 사라질 행 수를 각각 보여준다 | 보정과 정규화 행이 조용히 함께 사라진다 |
| 전달된 행이 섞여 있으면 그 수를 따로 알린다 | 소비 측이 이미 받아 간 것을 모르고 지운다 |
| 세 표가 함께 비고 고르지 않은 행은 남는다 | 가리키는 곳 없는 보정이 남거나 남길 것이 사라진다 |
| 브라우저 confirm() 을 쓰지 않는다 | 자동화 세션이 멈춘다 |
| 다시 수집된다는 것을 확인 창이 적는다 | 왜 되살아나는지 알 수 없다 |
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
    """워크플로우 둘에 공고 다섯. 하나는 이미 전달됐고 하나는 사람 보정이 둘 붙어 있다."""
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    connection.execute(
        "INSERT INTO crawlers (name, list_url, status) VALUES ('lg', ?, 'promoted')",
        (LIST_URL,),
    )
    connection.execute(
        "INSERT INTO crawlers (name, list_url, status) VALUES ('example', ?, 'promoted')",
        ("https://example.com/jobs/",),
    )
    connection.execute("INSERT INTO workflows (crawler_id, name) VALUES (1, 'LG')")
    connection.execute("INSERT INTO workflows (crawler_id, name) VALUES (2, 'example')")
    for raw_job_id, workflow_id, company, title in (
        (1, 1, "엘지전자", "백엔드 개발자"),
        (2, 1, "엘지화학", "프론트 개발자"),
        (3, 1, "엘지전자", "데이터 엔지니어"),
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
        " VALUES (1, 'company', 'LG 전자'), (1, 'title', '서버 개발자')"
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
    html = client.get("/ui/jobs").text

    assert 'id="job-select-form"' in html
    assert 'hx-post="/ui/jobs/delete/confirm"' in html
    for raw_job_id in (1, 2, 3, 4, 5):
        assert f'name="raw_job_id" value="{raw_job_id}"' in html


def test_지금_걸린_조건이_지우기_폼과_함께_간다(client: TestClient) -> None:
    """`필터 전체` 가 화면에 보이는 것과 같은 조건이어야 한다."""
    html = client.get("/ui/jobs", params={"workflow_id": "1", "status": "none"}).text

    assert '<input type="hidden" name="workflow_id" value="1">' in html
    assert '<input type="hidden" name="status" value="none">' in html
    assert 'data-total="3"' in html


def test_전체_선택이_무엇을_고르는지_글자로_밝힌다(client: TestClient) -> None:
    """`화면에 보이는 것` 과 `필터에 걸린 것` 은 다르다. 둘을 각각 이름으로 적는다."""
    html = client.get("/ui/jobs").text

    assert "화면에 보이는 5건 모두 고르기" in html
    assert "필터에 걸린 5건 전체 고르기" in html
    assert 'id="job-select-count"' in html


def test_아무것도_고르지_않으면_지우기_단추가_눌리지_않는다(client: TestClient) -> None:
    html = client.get("/ui/jobs").text

    start = html.index('id="job-delete-open"')
    assert "disabled" in html[start : start + 400]


def test_확인_창이_세_표에서_사라질_행_수를_각각_보여준다(client: TestClient) -> None:
    html = client.post("/ui/jobs/delete/confirm", data={"raw_job_id": ["1", "3"]}).text

    assert "raw_jobs" in html
    assert "normalized_jobs" in html
    assert "job_field_overrides" in html
    # 수집 2건, 정규화 2건, 보정 2건(모두 1번 것)
    assert html.count("2건</td>") == 3
    assert "되돌릴 수 없다" in html
    # 브라우저 모달은 자동화 세션을 멈춘다. 이 저장소는 <dialog> 를 쓴다
    assert "hx-confirm" not in html


def test_확인_창이_전달된_행의_수를_따로_알린다(client: TestClient) -> None:
    html = client.post("/ui/jobs/delete/confirm", data={"raw_job_id": ["1", "2"]}).text

    assert "이 중 1건은 이미 소비 측에 전달된 행이다" in html


def test_확인_창이_고른_범위와_조건을_글자로_적는다(client: TestClient) -> None:
    picked = client.post("/ui/jobs/delete/confirm", data={"raw_job_id": ["1"]}).text
    whole = client.post(
        "/ui/jobs/delete/confirm", data={"all_filtered": "1", "workflow_id": "1"}
    ).text

    assert "표에서 고른 공고" in picked
    assert "지금 조회 조건에 걸린 전부" in whole
    assert "워크플로우 1 - LG" in whole
    # 필터 전체는 체크박스가 보낸 id 가 아니라 조건으로 다시 센다
    assert "3건</td>" in whole


def test_고른_것만_세_표에서_사라지고_나머지는_남는다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    assert counts(conn) == (5, 5, 2)

    response = client.post("/ui/jobs/delete", data={"raw_job_id": ["1", "3", "5"]})

    assert response.status_code == 200
    assert "수집 건 3건" in response.text
    assert counts(conn) == (2, 2, 0)
    assert raw_ids(conn) == [2, 4]
    assert (
        int(
            conn.execute(
                "SELECT count(*) FROM normalized_jobs WHERE raw_job_id IN (1,3,5)"
            ).fetchone()[0]
        )
        == 0
    )


def test_필터_전체로_지우면_조건에_걸린_것만_사라진다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    confirm = client.post(
        "/ui/jobs/delete/confirm", data={"all_filtered": "1", "workflow_id": "2"}
    ).text
    assert 'name="raw_job_id" value="4"' in confirm
    assert 'name="raw_job_id" value="5"' in confirm

    client.post("/ui/jobs/delete", data={"scope": "filtered", "raw_job_id": ["4", "5"]})

    assert raw_ids(conn) == [1, 2, 3]


def test_지운_뒤_표를_다시_부르라고_알린다(client: TestClient) -> None:
    response = client.post("/ui/jobs/delete", data={"raw_job_id": ["5"]})

    assert response.headers["HX-Trigger-After-Settle"] == "jobs-deleted"


def test_지울_것이_없으면_지우지_않고_그렇다고_적는다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    response = client.post("/ui/jobs/delete", data={})

    assert "지울 대상이 없다" in response.text
    assert "HX-Trigger-After-Settle" not in response.headers
    assert counts(conn) == (5, 5, 2)


def test_이미_사라진_id_를_보내도_그것만_건너뛴다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    response = client.post("/ui/jobs/delete", data={"raw_job_id": ["4", "999"]})

    assert "수집 건 1건" in response.text
    assert raw_ids(conn) == [1, 2, 3, 5]


def test_지운_건수와_요청자를_로그에_남긴다(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("INFO", logger="app.api.ui_jobs"):
        client.post("/ui/jobs/delete", data={"raw_job_id": ["1"]})

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "조회 화면에서 공고를 지웠다" in logged
    assert "raw_jobs=1" in logged
    assert "job_field_overrides=2" in logged
    assert "요청=" in logged
