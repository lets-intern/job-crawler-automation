"""모델 목록을 제공자에게 물어 화면 칸을 채우는 자리. 실제 호출은 하지 않는다.

모델 ID 를 소스에 적지 않으려고 물어본다 (`.claude/rules/llm.md`). 그래서 이 파일이 잠그는
것은 "목록이 오면 고르는 상자가 되고, 못 오면 손으로 적는 칸이 된다" 는 갈림 하나다.

**못 받는 것이 정상 경로다.** 키가 없거나 크레딧이 끊긴 제공자를 화면에서 골라 보는 일이
흔하고, 그때도 저장은 되어야 한다.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from app.config import Settings
from app.llm import settings as store
from app.llm.base import LlmCallError, Provider


def _entry(name: str, lister: Any) -> Provider:
    return Provider(
        name=name,
        sdk="테스트",
        key_setting="gemini_api_key",
        model_setting="gemini_model",
        build_client=lambda settings: object(),
        call_model=None,  # type: ignore[arg-type]
        list_models=lister,
    )


@pytest.fixture
def conn() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
    )
    return connection


async def test_키가_있으면_목록이_정렬되어_온다(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def lister(client: Any) -> list[str]:
        return ["나중-모델", "가장-먼저", "중간"]

    monkeypatch.setitem(store.registry.PROVIDERS, "테스트", _entry("테스트", lister))
    models, problem = await store.list_models(
        conn, "테스트", Settings(gemini_api_key="키가-있다")
    )

    assert models == ["가장-먼저", "나중-모델", "중간"]
    assert problem == ""


async def test_키가_없으면_사유만_오고_목록은_비어_있다(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """저장을 막지 않는다. 손으로 적는 칸으로 떨어진다."""

    async def lister(client: Any) -> list[str]:  # pragma: no cover - 불려서는 안 된다
        raise AssertionError("키가 없는데 물어보러 갔다")

    monkeypatch.setitem(store.registry.PROVIDERS, "테스트", _entry("테스트", lister))
    models, problem = await store.list_models(conn, "테스트", Settings(gemini_api_key=""))

    assert models == []
    assert "API 키가 없다" in problem


async def test_제공자가_실패해도_세우지_않는다(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """크레딧이 끊긴 제공자를 골라도 화면이 죽지 않는다."""

    async def lister(client: Any) -> list[str]:
        raise RuntimeError("429 크레딧이 없다")

    monkeypatch.setitem(store.registry.PROVIDERS, "테스트", _entry("테스트", lister))
    models, problem = await store.list_models(conn, "테스트", Settings(gemini_api_key="키"))

    assert models == []
    assert "429" in problem


async def test_목록을_주지_않는_제공자(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(store.registry.PROVIDERS, "테스트", _entry("테스트", None))
    models, problem = await store.list_models(conn, "테스트", Settings(gemini_api_key="키"))

    assert models == []
    assert "손으로 적는다" in problem


async def test_모르는_제공자는_거절한다(conn: sqlite3.Connection) -> None:
    with pytest.raises(store.LlmSettingError):
        await store.list_models(conn, "없는이름")


async def test_키는_저장된_값이_환경변수를_이긴다(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """화면에서 키를 넣은 직후에 목록이 와야 한다. 환경변수만 보면 오지 않는다.

    이름을 `gemini` 로 쓰는 것은 `ROWS` 가 임포트 시점에 실제 제공자 목록으로 만들어져서다.
    없는 이름의 행은 `_stored()` 의 `WHERE key IN (...)` 에 걸리지 않는다.
    """
    seen: list[Any] = []

    async def lister(client: Any) -> list[str]:
        seen.append(client)
        return ["모델하나"]

    monkeypatch.setitem(store.registry.PROVIDERS, "gemini", _entry("gemini", lister))
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?, ?)",
        (store.key_row("gemini"), "화면에서-저장한-키"),
    )

    models, problem = await store.list_models(conn, "gemini", Settings(gemini_api_key=""))

    assert models == ["모델하나"]
    assert problem == ""
    assert len(seen) == 1


def test_모든_제공자가_목록_함수를_가진다() -> None:
    """넷 다 `models.list()` 가 있는 것을 SDK 에서 확인했다. 빠뜨리면 그 제공자만 손입력이다."""
    for name, entry in store.registry.PROVIDERS.items():
        assert entry.list_models is not None, name


def test_잘못된_예외는_그대로_올린다() -> None:
    """`LlmCallError` 는 사유가 있는 실패라 문구로 옮긴다. 그 밖은 넓게 받는다."""
    assert issubclass(LlmCallError, RuntimeError)
