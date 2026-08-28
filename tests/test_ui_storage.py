"""저장소 설정 화면 테스트 (5.6.V).

확인하는 것은 넷이다. 저장하고 다시 불러 값이 남는지, 거절 사유가 화면에 그대로 나오는지,
비밀 키가 화면에 통째로 실려 나가지 않는지, 그리고 연결 확인이 폼이 아니라 저장된 설정으로
도는지.

실제 왕복은 로컬 MinIO 로 확인한다. 여기서는 저장소를 부르는 자리를 바꿔치기한다 — 화면
테스트가 컨테이너가 떠 있는지에 매달리게 두지 않는다.
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
from app.storage import s3
from app.storage import settings as store


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


FORM = {
    "endpoint": "http://minio:9000",
    "region": "us-east-1",
    "bucket": "logos",
    "access_key": "minioadmin",
    "secret_key": "supersecretvalue",
    "public_base": "http://localhost:9000/logos",
}


def test_page_calls_the_fragment(client: TestClient) -> None:
    """운영 설정 하위 메뉴에서 열린다."""
    response = client.get("/settings/storage")

    assert response.status_code == 200
    assert 'hx-get="/ui/storage"' in response.text


def test_saved_values_survive_a_reload(client: TestClient, conn: sqlite3.Connection) -> None:
    """저장하고 새로 고쳐도 값이 남는다."""
    saved = client.put("/ui/storage", data=FORM)
    assert saved.status_code == 200
    assert "logos" in saved.text

    again = client.get("/ui/storage")
    assert 'value="http://minio:9000"' in again.text
    assert 'value="logos"' in again.text
    assert 'value="http://localhost:9000/logos"' in again.text
    assert store.read_config(conn).bucket == "logos"


def test_secret_never_reaches_the_screen(client: TestClient) -> None:
    """비밀 키는 끝 네 자리만 나간다."""
    client.put("/ui/storage", data=FORM)
    body = client.get("/ui/storage").text

    assert "supersecretvalue" not in body
    assert "alue" in body


def test_blank_secret_keeps_the_stored_one(client: TestClient, conn: sqlite3.Connection) -> None:
    """버킷 이름 하나 고치려고 키를 다시 타이핑하지 않는다."""
    client.put("/ui/storage", data=FORM)
    client.put("/ui/storage", data={**FORM, "secret_key": "", "bucket": "other"})

    config = store.read_config(conn)
    assert config.bucket == "other"
    assert config.secret_key == "supersecretvalue"


def test_rejected_value_says_why(client: TestClient, conn: sqlite3.Connection) -> None:
    """화면이 저장소의 거절 사유를 그대로 옮기고, 아무것도 저장하지 않는다."""
    response = client.put("/ui/storage", data={**FORM, "endpoint": "minio:9000"})

    assert response.status_code == 200
    assert "엔드포인트" in response.text
    assert store.read_config(conn).bucket == ""


def test_check_uses_the_saved_config(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """폼에 적힌 값이 아니라 저장된 값으로 확인한다."""
    client.put("/ui/storage", data=FORM)
    seen: list[store.StorageConfig] = []

    def fake_check(config: store.StorageConfig) -> s3.CheckResult:
        seen.append(config)
        return s3.CheckResult(ok=True, step="지우기", reason="ok", message="넣고 읽고 지웠다")

    monkeypatch.setattr(s3, "check", fake_check)
    response = client.post("/ui/storage/check", data={"bucket": "typed-in-the-form"})

    assert response.status_code == 200
    assert seen[0].bucket == "logos"
    assert "연결 확인" in response.text
    assert "성공" in response.text


def test_check_failure_names_the_step(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """어디서 멈췄는지가 화면에 남는다."""
    client.put("/ui/storage", data=FORM)

    def fake_check(config: store.StorageConfig) -> s3.CheckResult:
        return s3.CheckResult(
            ok=False, step="넣기", reason="no_bucket", message="버킷 `logos` 이 저장소에 없다"
        )

    monkeypatch.setattr(s3, "check", fake_check)
    body = client.post("/ui/storage/check").text

    assert "실패" in body
    assert "넣기" in body
    assert "버킷 `logos` 이 저장소에 없다" in body


def test_check_before_saving_says_not_configured(client: TestClient) -> None:
    """저장 전에는 저장소를 부르지도 않는다. 순서는 저장하고 나서 확인이다."""
    body = client.post("/ui/storage/check").text

    assert "실패" in body
    assert "먼저 저장한다" in body
