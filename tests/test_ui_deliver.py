"""전달 설정 화면 (7.3.V).

저장소 검증은 `tests/test_deliver_settings.py` 가 한다. 여기서는 화면 조각이 그 검증을
그대로 옮기는지, 그리고 테스트 전송 단추가 없는지만 본다.
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api.settings import get_connection
from app.main import app


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

    app.dependency_overrides[get_connection] = request_connection
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_아직_아무것도_보내지_않는다고_적는다(client: TestClient) -> None:
    assert "아직 아무것도 보내지 않는다" in client.get("/ui/deliver").text


def test_테스트_전송_단추가_없다(client: TestClient) -> None:
    """`app/api/ui_notify.py` 와 다른 점 — 보내는 코드가 없으니 시험할 것도 없다."""
    body = client.get("/ui/deliver").text
    assert "테스트 전송" not in body
    assert "/ui/deliver/test" not in body


def test_저장하면_화면에서_다시_읽힌다(client: TestClient) -> None:
    saved = client.put(
        "/ui/deliver",
        data={
            "url": "https://board.example.com/ingest",
            "method": "PUT",
            "auth_header": "X-Api-Key: secret",
            "batch_size": "50",
        },
    )

    assert saved.status_code == 200
    assert "저장했다" in saved.text
    assert "설정됐다" in saved.text

    reloaded = client.get("/ui/deliver").text
    assert 'value="https://board.example.com/ingest"' in reloaded
    assert 'value="X-Api-Key: secret"' in reloaded
    assert 'value="50"' in reloaded
    assert '<option value="PUT" selected>' in reloaded


def test_잘못된_주소는_사유와_함께_거절된다(client: TestClient) -> None:
    response = client.put("/ui/deliver", data={"url": "ftp://x.example.com"})

    assert "저장하지 못했다" in response.text
    assert "http" in response.text
    # 거절됐으니 저장값은 그대로 비어 있다
    assert client.get("/ui/deliver").text.count('value=""') >= 1
