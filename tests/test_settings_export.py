"""스냅샷 내보내기.

받은 파일은 그대로 다른 서버의 가져오기에 올릴 수 있어야 한다. 그러려면 열리는 SQLite 여야
하고 우리 스키마여야 한다.

파일을 그대로 복사하지 않고 `VACUUM INTO` 로 뜨는 이유는, 워크플로우가 30분마다 도는 서버에서
쓰기 도중의 페이지가 섞이면 열리지 않는 파일이 나오기 때문이다.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import settings as settings_api
from app.main import app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    path = tmp_path / "jobs.db"
    conn = db.connect(path)
    db.migrate_up(conn)
    conn.execute(
        "INSERT INTO crawlers (name, list_url, status) VALUES ('시험', 'https://x', 'draft')"
    )
    conn.commit()
    conn.close()

    def request_connection() -> Iterator[sqlite3.Connection]:
        connection = db.connect(path)
        try:
            yield connection
        finally:
            connection.close()

    app.dependency_overrides[settings_api.get_connection] = request_connection
    from app.config import get_settings

    get_settings.cache_clear()
    import os

    os.environ["DATABASE_PATH"] = str(path)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    os.environ.pop("DATABASE_PATH", None)
    get_settings.cache_clear()


def test_export_returns_a_readable_sqlite_file(client: TestClient, tmp_path: Path) -> None:
    response = client.get("/ui/settings/export")

    assert response.status_code == 200
    assert response.content[:16] == b"SQLite format 3\x00"

    got = tmp_path / "downloaded.db"
    got.write_bytes(response.content)
    conn = sqlite3.connect(got)
    try:
        names = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "crawlers" in names
        assert "raw_jobs" in names
        # 내보낸 것이 지금 DB 의 내용이어야 한다. 빈 파일을 주면 가져오기가 아무 일도 안 한다
        assert conn.execute("SELECT COUNT(*) FROM crawlers").fetchone()[0] == 1
    finally:
        conn.close()


def test_export_names_the_file_with_a_timestamp(client: TestClient) -> None:
    """같은 이름으로 여러 번 받으면 어느 것이 언제 것인지 알 수 없다."""
    response = client.get("/ui/settings/export")

    disposition = response.headers["content-disposition"]
    assert "jobs-" in disposition
    assert ".db" in disposition


def test_warning_names_the_storage_keys(client: TestClient) -> None:
    """경고에 없는 비밀은 없는 것으로 읽힌다 (5.7).

    저장소 키는 `app_settings` 에 있고, 내보내기는 DB 를 통째로 뜬다. 그래서 이 파일에
    같이 실려 나간다. 화면이 그 사실을 이름으로 말한다.
    """
    body = client.get("/settings/export").text

    assert "s3_access_key" in body
    assert "s3_secret_key" in body
    assert "저장소 키" in body
