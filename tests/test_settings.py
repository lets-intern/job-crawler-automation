"""운영 설정 저장소와 API 테스트.

확인하는 것은 우선순위 하나다. 값이 없을 때는 환경변수, 한 번 저장된 뒤로는 DB.
그리고 상한이 받지 않는 값(0, 음수)을 실제로 거절하는지.
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import db, settings
from app.api import settings as settings_api
from app.main import app
from app.settings import MAX_CONCURRENT_RUNS


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

    app.dependency_overrides[settings_api.get_connection] = request_connection
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def stored(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM app_settings WHERE key = ?", (key,)).fetchone()


def test_값이_없으면_환경변수_값으로_채운다(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "_env_default", lambda key: 7)
    assert stored(conn, MAX_CONCURRENT_RUNS) is None

    assert settings.read_int(conn, MAX_CONCURRENT_RUNS) == 7

    row = stored(conn, MAX_CONCURRENT_RUNS)
    assert row is not None
    assert row["value"] == "7"
    assert row["updated_at"]


def test_저장된_뒤에는_DB_값이_이긴다(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "_env_default", lambda key: 7)
    settings.write_int(conn, MAX_CONCURRENT_RUNS, 2)

    # 환경변수를 나중에 고쳐도 저장된 값을 덮지 않는다
    monkeypatch.setattr(settings, "_env_default", lambda key: 99)

    assert settings.read_int(conn, MAX_CONCURRENT_RUNS) == 2


@pytest.mark.parametrize("value", [0, -1, -100])
def test_0_과_음수는_거부한다(conn: sqlite3.Connection, value: int) -> None:
    settings.write_int(conn, MAX_CONCURRENT_RUNS, 3)

    with pytest.raises(settings.SettingValueError):
        settings.write_int(conn, MAX_CONCURRENT_RUNS, value)

    # 거절된 값은 저장되지 않는다
    assert settings.read_int(conn, MAX_CONCURRENT_RUNS) == 3


def test_모르는_키는_읽지도_쓰지도_않는다(conn: sqlite3.Connection) -> None:
    with pytest.raises(settings.UnknownSettingError):
        settings.read_int(conn, "crawl_delay_seconds")
    with pytest.raises(settings.UnknownSettingError):
        settings.write_int(conn, "crawl_delay_seconds", 5)


def test_키는_둘이다() -> None:
    """2026-08-27 에 `first_run_limit` 이 들어왔다. 등록 시 백필을 막는 값이다."""
    assert settings.KEYS == (MAX_CONCURRENT_RUNS, settings.FIRST_RUN_LIMIT)


def test_손으로_넣은_깨진_값은_그대로_알린다(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?, ?)", (MAX_CONCURRENT_RUNS, "많이")
    )

    with pytest.raises(settings.SettingValueError):
        settings.read_int(conn, MAX_CONCURRENT_RUNS)


def test_조회_API_는_현재_값을_돌려준다(client: TestClient, conn: sqlite3.Connection) -> None:
    settings.write_int(conn, MAX_CONCURRENT_RUNS, 4)

    response = client.get("/api/settings")

    assert response.status_code == 200
    assert response.json()[MAX_CONCURRENT_RUNS] == 4
    # 키가 늘어도 이 시험이 깨지지 않게 한 칸만 본다. 키 목록은 위 시험이 잠근다
    assert set(response.json()) == set(settings.KEYS)


def test_변경_API_는_다음_조회부터_새_값을_준다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    settings.write_int(conn, MAX_CONCURRENT_RUNS, 3)

    response = client.put(f"/api/settings/{MAX_CONCURRENT_RUNS}", json={"value": 5})

    assert response.status_code == 200
    assert response.json() == {"key": MAX_CONCURRENT_RUNS, "value": 5}
    assert client.get("/api/settings").json()[MAX_CONCURRENT_RUNS] == 5


@pytest.mark.parametrize("value", [0, -3])
def test_변경_API_는_1_미만을_거절한다(
    client: TestClient, conn: sqlite3.Connection, value: int
) -> None:
    settings.write_int(conn, MAX_CONCURRENT_RUNS, 3)

    response = client.put(f"/api/settings/{MAX_CONCURRENT_RUNS}", json={"value": value})

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "invalid_value"
    assert settings.read_int(conn, MAX_CONCURRENT_RUNS) == 3


def test_변경_API_는_모르는_키를_404_로_거절한다(client: TestClient) -> None:
    response = client.put("/api/settings/crawl_delay_seconds", json={"value": 5})

    assert response.status_code == 404
    assert response.json()["detail"]["reason"] == "unknown_key"
