"""검수 모달의 원문 (10.1).

실사이트에 나가지 않는다. 저장된 행을 넣고 화면 경로로만 연다.

원문은 `raw_jobs.raw_data_json` 의 `source_text` 키다 (side Push 8). 상세 페이지에서 본문
노드의 부모를 편 글자이고, 화면은 그것을 보여주기만 한다.

| 확인 | 깨지면 |
|---|---|
| 원문이 있으면 모달에 그 글자가 나온다 | 수집해 둔 근거를 화면에서 볼 방법이 없다 |
| 원문은 입력 요소가 아니다 | append-only 인 수집분을 화면에서 고치려 든다 |
| 원문을 폼에 실어 보내도 보정이 생기지 않는다 | 고칠 수 없는 값이 저장 경로로 새어 든다 |
| 저장 경로가 `raw_jobs` 를 건드리지 않는다 | 원문이 사람 손을 타 근거가 아니게 된다 |
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
from app.api import crawlers as crawlers_api
from app.main import app

LIST_URL = "https://static.example.test/"

# 원문에만 있는 글자. 본문에는 없어서, 화면에 나오면 원문에서 온 것이 확실하다
SOURCE_MARK = "원문 표식 A9"
SOURCE_TEXT = f"{SOURCE_MARK}\n회사 예시\n근무지 판교\n마감 2026-09-30"

INPUT_TAG = re.compile(r"<(?:input|textarea)\b[^>]*>")
TEXTAREA_BODY = re.compile(r"<textarea\b[^>]*>(.*?)</textarea>", re.DOTALL)


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    connection.execute(
        """
        INSERT INTO crawlers (id, name, list_url, status, detail_mode)
        VALUES (1, '정적 상세', ?, 'promoted', 'static')
        """,
        (LIST_URL,),
    )
    connection.execute("INSERT INTO workflows (id, crawler_id, name) VALUES (1, 1, '정적 상세')")
    # 1번은 원문이 있는 건, 2번은 `source_text` 키가 아예 없는 옛 수집분이다
    connection.execute(
        """
        INSERT INTO raw_jobs (id, workflow_id, source_url, raw_data_json, content_hash)
        VALUES (1, 1, ?, json_object('title', '공고 1', 'body', '본문 1',
                                     'source_text', ?), 'hash-1')
        """,
        (f"{LIST_URL}1", SOURCE_TEXT),
    )
    connection.execute(
        """
        INSERT INTO raw_jobs (id, workflow_id, source_url, raw_data_json, content_hash)
        VALUES (2, 1, ?, json_object('title', '공고 2', 'body', '본문 2'), 'hash-2')
        """,
        (f"{LIST_URL}2",),
    )
    for raw_id in (1, 2):
        connection.execute(
            """
            INSERT INTO normalized_jobs (raw_job_id, company, title, body, source_url)
            VALUES (?, '예시', ?, ?, ?)
            """,
            (raw_id, f"공고 {raw_id}", f"본문 {raw_id}", f"{LIST_URL}{raw_id}"),
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


def modal(client: TestClient, raw_job_id: int) -> str:
    response = client.get(f"/ui/review/modal/{raw_job_id}")
    assert response.status_code == 200
    return response.text


def test_원문이_있으면_모달에_그대로_나온다(client: TestClient) -> None:
    html = modal(client, 1)

    assert SOURCE_MARK in html
    assert "근무지 판교" in html


def test_원문은_고칠_수_있는_칸으로_나오지_않는다(client: TestClient) -> None:
    """수집분은 append-only 다. 입력으로 두면 화면에서 고칠 수 있는 것처럼 보인다."""
    html = modal(client, 1)

    assert 'name="source_text"' not in html
    for tag in INPUT_TAG.findall(html):
        assert SOURCE_MARK not in tag, tag
    for body in TEXTAREA_BODY.findall(html):
        assert SOURCE_MARK not in body


def test_원문을_폼에_실어_보내도_보정이_생기지_않는다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """고칠 수 있는 필드 목록 밖의 이름은 저장 경로가 받지 않는다."""
    response = client.put(
        "/ui/review/jobs/1",
        data={"title": "공고 1", "body": "본문 1", "source_text": "손으로 고친 원문"},
    )

    assert response.status_code == 200
    rows = conn.execute("SELECT field_name FROM job_field_overrides").fetchall()
    assert [str(row["field_name"]) for row in rows] == []


def test_저장_경로가_원문을_건드리지_않는다(client: TestClient, conn: sqlite3.Connection) -> None:
    before = str(conn.execute("SELECT raw_data_json FROM raw_jobs WHERE id = 1").fetchone()[0])

    client.put("/ui/review/jobs/1", data={"title": "고친 제목", "source_text": "손으로 고친 원문"})

    after = str(conn.execute("SELECT raw_data_json FROM raw_jobs WHERE id = 1").fetchone()[0])
    assert after == before
    assert json.loads(after)["source_text"] == SOURCE_TEXT
