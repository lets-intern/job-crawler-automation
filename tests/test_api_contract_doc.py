"""제공 API 계약 문서와 실제 응답 키의 대조 (5.4.V).

`.claude/docs/api-contract.md` 는 응답 예시를 JSON 코드 블록으로 싣는다. 구현이 필드를
더하거나 뺄 때 이 파일을 고치지 않으면 문서와 실제 응답이 조용히 갈린다
(`.claude/rules/data-safety.md`, `.claude/docs/api-contract.md` 1절 "한 커밋에서 같이 고친다").

실사이트에 나가지 않는다. 문서를 읽고, 시드 하나를 넣어 실제 응답과 견준다.

| 확인 | 깨지면 |
|---|---|
| 문서의 응답 예시 키 집합이 실제 응답 키 집합과 같다 | 계약 문서가 실제 API 를 설명하지 못한다 |
| `job_major`/`job_minor` 가 둘 다 있다 | 5.3 이 더한 필드를 문서가 놓친다 |
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
from app.api import jobs as jobs_api
from app.main import app

DOC_PATH = pathlib.Path(__file__).resolve().parent.parent / ".claude" / "docs" / "api-contract.md"

# "## 조회" 절 아래, 응답 예시로 실린 첫 JSON 코드 블록
RESPONSE_EXAMPLE = re.compile(r"## 조회.*?```json\s*(\{.*?\})\s*```", re.DOTALL)


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    connection.execute(
        "INSERT INTO crawlers (name, list_url, status)"
        " VALUES ('시드', 'https://example.test/', 'promoted')"
    )
    connection.execute("INSERT INTO workflows (crawler_id, name) VALUES (1, '시드')")
    raw = connection.execute(
        """
        INSERT INTO raw_jobs (workflow_id, source_url, raw_data_json, content_hash)
        VALUES (1, 'https://example.test/jobs/1', '{}', 'hash-1')
        """
    )
    connection.execute(
        """
        INSERT INTO normalized_jobs
               (raw_job_id, company, title, deadline, body, requirements, source_url)
        VALUES (?, '회사', '공고', '2026-09-30', '본문', '자격요건', 'https://example.test/jobs/1')
        """,
        (int(raw.lastrowid or 0),),
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

    app.dependency_overrides[jobs_api.get_connection] = request_connection
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _documented_item_keys() -> set[str]:
    text = DOC_PATH.read_text(encoding="utf-8")
    found = RESPONSE_EXAMPLE.search(text)
    assert found is not None, "계약 문서에서 조회 응답 예시 JSON 을 찾지 못했다"
    payload = json.loads(found.group(1))
    return set(payload["items"][0])


def test_문서의_응답_예시_키가_실제_응답과_같다(client: TestClient) -> None:
    item = client.get("/api/jobs").json()["items"][0]

    assert _documented_item_keys() == set(item)


def test_문서에_직무_대분류_소분류가_있다() -> None:
    assert {"job_major", "job_minor"} <= _documented_item_keys()
