"""AI 제공자 설정 화면 (2.3.V 의 자동 확인분).

눈으로 보는 것은 따로 하고, 여기서는 화면이 지켜야 하는 셋을 잠근다.

**저장한 키가 화면에 다시 나오지 않는다.** 끝 네 자리와 있음·없음까지다.
**키 없는 제공자를 고르면 거절 사유가 화면에 그대로 나온다.** 조용히 다른 제공자로 넘어가지
않는다 (`.claude/rules/llm.md`).
**저장하면 다음 호출부터 그 값을 쓴다.** 서버를 다시 띄우지 않는다.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import settings as settings_api
from app.config import get_settings
from app.llm import settings as store
from app.llm.log import CLASSIFY
from app.main import app

FULL_KEY = "sk-화면에서-넣은-키-0000-abcd"


@pytest.fixture
def conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[sqlite3.Connection]:
    """환경변수는 gemini 만 채운다. 나머지 셋은 키가 없는 제공자다."""
    monkeypatch.setenv("GEMINI_API_KEY", "sk-환경변수-키-1111")
    monkeypatch.setenv("CLAUDE_API_KEY", "")
    monkeypatch.setenv("GPT_API_KEY", "")
    monkeypatch.setenv("QWEN_API_KEY", "")
    monkeypatch.setenv("CLASSIFY_PROVIDER", "gemini")
    get_settings.cache_clear()

    path = tmp_path / "jobs.db"
    connection = db.connect(path)
    db.migrate_up(connection)
    try:
        yield connection
    finally:
        connection.close()
        get_settings.cache_clear()


@pytest.fixture
def client(tmp_path: Path, conn: sqlite3.Connection) -> Iterator[TestClient]:
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


def test_설정_화면이_제공자_조각을_불러온다(client: TestClient) -> None:
    body = client.get("/settings").text

    assert 'hx-get="/ui/llm"' in body


def test_키_상태를_있음과_없음으로_적는다(client: TestClient) -> None:
    body = client.get("/ui/llm").text

    assert "1111" in body
    assert "sk-환경변수-키-1111" not in body
    assert "없음" in body


def test_저장한_키는_끝_네_자리만_돌아온다(client: TestClient, conn: sqlite3.Connection) -> None:
    body = client.put("/ui/llm/key/qwen", data={"value": FULL_KEY}).text

    assert FULL_KEY not in body
    assert "abcd" in body
    assert store.read_config(conn).key("qwen").stored is True


def test_키를_비우면_지우고_환경변수로_돌아간다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    client.put("/ui/llm/key/qwen", data={"value": FULL_KEY})

    body = client.put("/ui/llm/key/qwen", data={"value": ""}).text

    assert "지웠다" in body
    assert store.read_config(conn).key("qwen").present is False


def test_키_없는_제공자를_고르면_거절_사유가_화면에_나온다(client: TestClient) -> None:
    body = client.put("/ui/llm/feature/classify", data={"provider": "claude", "model": ""}).text

    assert "저장하지 못했다" in body
    assert "API 키가 없다" in body
    assert "claude" in body


def test_스키마를_못_지키는_모델을_분류에_고르면_거절한다(client: TestClient) -> None:
    client.put("/ui/llm/key/qwen", data={"value": FULL_KEY})

    body = client.put(
        "/ui/llm/feature/classify", data={"provider": "qwen", "model": "qwen-plus"}
    ).text

    assert "저장하지 못했다" in body
    assert "qwen-plus" in body


def test_기능마다_다른_제공자와_모델을_저장한다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    client.put("/ui/llm/key/qwen", data={"value": FULL_KEY})

    body = client.put(
        "/ui/llm/feature/classify", data={"provider": "qwen", "model": "qwen3.8-flash"}
    ).text

    assert "본문 분류" in body
    assert "qwen3.8-flash" in body
    resolved = store.settings_for(conn, CLASSIFY)
    assert resolved.classify_provider == "qwen"
    assert resolved.qwen_model == "qwen3.8-flash"
    assert resolved.qwen_api_key == FULL_KEY


def test_조각에_이모지가_없다(client: TestClient) -> None:
    """상태는 낱말로 적는다 (`.claude/rules/writing.md`)."""
    body = client.get("/ui/llm").text

    assert not any(character in body for character in "✅❌⚠\U0001f4dd⭐")
