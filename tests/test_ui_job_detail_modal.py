"""조회 상세 모달 (16.2).

실사이트에 나가지 않는다. 저장된 행을 넣고 화면 경로로만 연다.

| 확인 | 깨지면 |
|---|---|
| 표의 상세가 모달을 연다 | 상세가 표 아래로 밀려 스크롤해야 보인다 |
| 페이지에 표 아래 상세 자리가 없다 | 상세가 열리는 자리가 둘이 되어 어느 쪽이 최신인지 모른다 |
| 모달이 본문·자격요건을 자르지 않는다 | 긴 본문을 확인하려고 원문 사이트를 다시 연다 |
| 원문 링크가 모달 안에 있다 | 상세를 닫아야 원문으로 갈 수 있다 |
| 상세에 고치는 입력이 없다 | 조회와 검수의 역할이 섞이고, 고친 값이 어디로 갔는지 모른다 |
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
SOURCE_URL = "https://www.python.org/jobs/7788/"
# 표 칸에 들어가지 않는 길이. 모달이 이것을 통째로 보여줘야 한다
LONG_BODY = "본문 시작\n" + ("긴 본문이 여기서 이어진다. " * 60) + "\n본문 끝"
LONG_REQUIREMENTS = "자격요건 시작\n" + ("여러 줄로 이어지는 자격요건이다. " * 40) + "\n자격요건 끝"


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    connection.execute(
        "INSERT INTO crawlers (name, list_url, status) VALUES ('python.org', ?, 'promoted')",
        (LIST_URL,),
    )
    connection.execute("INSERT INTO workflows (crawler_id, name) VALUES (1, 'python.org 채용')")
    connection.execute(
        """
        INSERT INTO raw_jobs (id, workflow_id, source_url, raw_data_json, content_hash)
        VALUES (7, 1, ?, '{}', 'hash-7')
        """,
        (SOURCE_URL,),
    )
    connection.execute(
        """
        INSERT INTO normalized_jobs
               (id, raw_job_id, company, company_source, title, body, requirements, source_url)
        VALUES (3, 7, '파이썬재단', 'parsed', '백엔드 개발자', ?, ?, ?)
        """,
        (LONG_BODY, LONG_REQUIREMENTS, SOURCE_URL),
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


def test_표의_상세가_모달을_연다(client: TestClient) -> None:
    html = client.get("/ui/jobs").text

    assert 'id="job-open-3"' in html
    assert "data-modal-open" in html
    assert 'hx-target="#app-modal-body"' in html
    assert 'hx-target="#job-detail"' not in html


def test_페이지에_표_아래_상세_자리가_없다(client: TestClient) -> None:
    """상세가 열리는 자리는 모달 하나다. 표 아래 영역은 남기지 않는다."""
    html = client.get("/jobs").text

    assert 'id="job-detail"' not in html
    assert "표에서 상세를 누르면 여기에 들어온다" not in html
    assert 'id="app-modal"' in html


def test_모달이_본문과_자격요건을_자르지_않는다(client: TestClient) -> None:
    html = client.get("/ui/jobs/3").text

    assert "본문 시작" in html and "본문 끝" in html
    assert "자격요건 시작" in html and "자격요건 끝" in html
    # 긴 값은 모달 안에서 스크롤한다. 페이지가 아니라 이 자리가 움직인다
    assert "modal-scroll" in html


def test_원문_링크가_모달_안에_있다(client: TestClient) -> None:
    html = client.get("/ui/jobs/3").text

    assert f'href="{SOURCE_URL}"' in html
    assert "원문 열기" in html


def test_상세는_읽기_전용이다(client: TestClient) -> None:
    """고치는 것은 검수 화면의 일이다. 두 화면의 역할을 섞지 않는다."""
    html = client.get("/ui/jobs/3").text

    assert "<form" not in html
    assert "<textarea" not in html
    assert "hx-put" not in html and "hx-delete" not in html
    assert 'href="/review"' in html  # 고치러 갈 자리는 알려 준다


def test_없는_공고는_모달_안에_사유를_적는다(client: TestClient) -> None:
    html = client.get("/ui/jobs/999").text

    assert "공고 999 가 없다" in html
    assert "modal-body" in html
