"""알림 설정 저장소와 화면 테스트 (1.3.V 의 픽스처 몫).

확인하는 것은 셋이다. 값이 `app_settings` 에 들어가는지(새 표를 만들지 않는다), 거절된 값이
하나도 저장되지 않는지, 그리고 손으로 넣은 깨진 값이 읽기를 죽이지 않는지 — 이 값을 읽는
자리가 크롤링 실행의 끝이다.

테스트 전송이 실제로 도착하는지는 사람이 화면에서 확인한다. 여기서는 단추가 저장된 설정으로
보내고 결과를 화면에 적는지까지 본다.
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import ui_notify
from app.api.settings import get_connection
from app.main import app
from app.notify import settings as store


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


def saved(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        str(row["key"]): str(row["value"])
        for row in conn.execute("SELECT key, value FROM app_settings")
    }


def test_저장한_적이_없으면_기본값이고_꺼져_있다(conn: sqlite3.Connection) -> None:
    config = store.read_config(conn)

    assert config.enabled is False
    assert config.server_url == store.DEFAULT_SERVER_URL
    assert config.topic == store.DEFAULT_TOPIC
    assert config.min_new_count == 1
    # 읽기가 쓰기를 하지 않는다
    assert saved(conn) == {}


def test_값은_app_settings_에_들어간다(conn: sqlite3.Connection) -> None:
    """새 표를 만들지 않는다 (`.claude/tasks/done/ntfy-notify/tasks-ntfy-notify.md`)."""
    store.write_config(
        conn,
        store.NotifyConfig(
            enabled=True,
            server_url="https://ntfy.example.com",
            topic="job",
            priority="high",
            min_new_count=3,
            click_base="https://ops.example.com",
        ),
    )

    rows = saved(conn)
    assert rows[store.ENABLED] == "1"
    assert rows[store.SERVER_URL] == "https://ntfy.example.com"
    assert rows[store.TOPIC] == "job"
    assert rows[store.PRIORITY] == "high"
    assert rows[store.MIN_NEW_COUNT] == "3"
    assert rows[store.CLICK_BASE] == "https://ops.example.com"

    tables = {
        str(row["name"])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert "ntfy_settings" not in tables


def test_저장한_뒤에는_그_값이_읽힌다(conn: sqlite3.Connection) -> None:
    store.write_config(conn, store.NotifyConfig(enabled=True, min_new_count=5))

    config = store.read_config(conn)

    assert config.enabled is True
    assert config.min_new_count == 5


@pytest.mark.parametrize(
    "broken",
    [
        store.NotifyConfig(server_url="ntfy.example.com"),
        store.NotifyConfig(topic=""),
        store.NotifyConfig(priority="아주높음"),
        store.NotifyConfig(min_new_count=0),
        store.NotifyConfig(click_base="ops.example.com"),
    ],
)
def test_거절된_값은_하나도_저장되지_않는다(
    conn: sqlite3.Connection, broken: store.NotifyConfig
) -> None:
    with pytest.raises(store.NotifySettingError):
        store.write_config(conn, broken)

    assert saved(conn) == {}


def test_손으로_넣은_깨진_값은_읽기를_죽이지_않는다(conn: sqlite3.Connection) -> None:
    """이 값을 읽는 자리가 크롤링 실행의 끝이다. 예외가 올라가면 수집이 멈춘다."""
    conn.executemany(
        "INSERT INTO app_settings (key, value) VALUES (?, ?)",
        [(store.MIN_NEW_COUNT, "많이"), (store.PRIORITY, "매우높음"), (store.ENABLED, "네")],
    )

    config = store.read_config(conn)

    assert config.min_new_count == store.DEFAULT_MIN_NEW_COUNT
    assert config.priority == store.DEFAULT_PRIORITY
    assert config.enabled is False


def test_누르면_열_주소는_데이터_검수_화면이다() -> None:
    config = store.NotifyConfig(click_base="https://ops.example.com/")

    assert config.click_url == "https://ops.example.com/review"


def test_주소를_적지_않으면_누를_곳이_없다() -> None:
    assert store.NotifyConfig(click_base="  ").click_url == ""


def test_화면이_저장된_설정을_그린다(client: TestClient, conn: sqlite3.Connection) -> None:
    store.write_config(conn, store.NotifyConfig(enabled=True, topic="job", min_new_count=7))

    response = client.get("/ui/notify")

    assert response.status_code == 200
    body = response.text
    assert 'name="topic"' in body
    assert 'value="7"' in body
    assert "켜짐" in body


def test_화면에서_저장하면_값이_들어간다(client: TestClient, conn: sqlite3.Connection) -> None:
    response = client.put(
        "/ui/notify",
        data={
            "enabled": "1",
            "server_url": "https://ntfy.example.com",
            "topic": "job",
            "priority": "high",
            "min_new_count": "4",
            "click_base": "https://ops.example.com",
        },
    )

    assert response.status_code == 200
    assert "저장했다" in response.text
    config = store.read_config(conn)
    assert config.enabled is True
    assert config.priority == "high"
    assert config.min_new_count == 4


def test_체크를_풀면_꺼진다(client: TestClient, conn: sqlite3.Connection) -> None:
    """체크박스는 꺼져 있으면 폼에 아예 실리지 않는다."""
    store.write_config(conn, store.NotifyConfig(enabled=True))

    client.put(
        "/ui/notify",
        data={
            "server_url": store.DEFAULT_SERVER_URL,
            "topic": store.DEFAULT_TOPIC,
            "priority": "default",
            "min_new_count": "1",
            "click_base": "",
        },
    )

    assert store.read_config(conn).enabled is False


def test_화면은_거절_사유를_그대로_옮긴다(client: TestClient, conn: sqlite3.Connection) -> None:
    response = client.put(
        "/ui/notify",
        data={
            "server_url": "ntfy.example.com",
            "topic": "job",
            "priority": "default",
            "min_new_count": "1",
            "click_base": "",
        },
    )

    assert response.status_code == 200
    assert "저장하지 못했다" in response.text
    assert "http:// 나 https:// 로 시작해야 한다" in response.text
    assert saved(conn) == {}


def test_정수가_아닌_기준_건수는_저장하지_않는다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    response = client.put(
        "/ui/notify",
        data={
            "server_url": store.DEFAULT_SERVER_URL,
            "topic": store.DEFAULT_TOPIC,
            "priority": "default",
            "min_new_count": "많이",
            "click_base": "",
        },
    )

    assert "정수가 아니다" in response.text
    assert saved(conn) == {}


def test_테스트_전송은_저장된_설정으로_보낸다(
    client: TestClient, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.write_config(
        conn,
        store.NotifyConfig(
            server_url="https://ntfy.example.com",
            topic="job",
            priority="high",
            click_base="https://ops.example.com",
        ),
    )
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "abc"})

    monkeypatch.setattr(
        ui_notify,
        "send",
        _with_transport(httpx.MockTransport(handle)),
    )

    response = client.post("/ui/notify/test")

    assert response.status_code == 200
    assert "테스트 전송" in response.text
    assert "성공" in response.text
    assert len(seen) == 1
    assert str(seen[0].url) == "https://ntfy.example.com/job"
    assert seen[0].headers["X-Priority"] == "high"
    assert seen[0].headers["X-Click"] == "https://ops.example.com/review"
    # 확인용 알림은 새 공고 알림과 제목도 태그도 달라야 휴대폰에서 구분된다
    assert seen[0].headers["X-Title"] == "알림 설정 확인"
    assert seen[0].headers["X-Tags"] == "white_check_mark"


def test_테스트_전송이_실패해도_화면은_뜬다(
    client: TestClient, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("연결하지 못했다", request=request)

    monkeypatch.setattr(ui_notify, "send", _with_transport(httpx.MockTransport(broken)))

    response = client.post("/ui/notify/test")

    assert response.status_code == 200
    assert "실패" in response.text


def _with_transport(transport: httpx.MockTransport):  # type: ignore[no-untyped-def]
    """라우트가 부르는 `send` 에 테스트 transport 를 끼운다."""
    from app.notify.ntfy import send as real_send

    async def send(target, message, **kwargs):  # type: ignore[no-untyped-def]
        return await real_send(target, message, transport=transport)

    return send
