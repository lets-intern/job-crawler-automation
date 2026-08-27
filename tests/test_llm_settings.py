"""제공자 설정 저장소 (2.1.V).

확인하는 것은 넷이다. 저장 전에는 환경변수 값이 나오는지, 저장한 뒤에는 DB 값이 이기는지,
환경변수를 나중에 고쳐도 저장된 값을 덮지 않는지, 그리고 키가 없는 제공자를 기능에 지정하면
거절하는지.

**모델이 제공자가 아니라 기능에 붙는다**는 것도 여기서 확인한다. 같은 제공자를 쓰는 두 기능이
다른 모델을 쓰지 못하면 이 저장소의 모양을 이렇게 잡은 이유가 없어진다 (2026-08-27 결정).
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest

from app import db
from app.config import Settings
from app.llm import settings as store
from app.llm.log import CLASSIFY, SELECTOR_GENERATE, SELECTOR_REPAIR


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    try:
        yield connection
    finally:
        connection.close()


def env(**overrides: str) -> Settings:
    """네 제공자 키를 다 채운 설정. 키 때문에 거절되는 경우를 따로 만들 때만 비운다."""
    values: dict[str, Any] = {
        "gemini_api_key": "환경변수-gemini-키",
        "claude_api_key": "환경변수-claude-키",
        "gpt_api_key": "환경변수-gpt-키",
        "qwen_api_key": "환경변수-qwen-키",
        **overrides,
    }
    return Settings(**values)


def rows(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        str(row["key"]): str(row["value"])
        for row in conn.execute("SELECT key, value FROM app_settings")
    }


def test_저장_전에는_환경변수_값이_나온다(conn: sqlite3.Connection) -> None:
    base = env(classify_provider="qwen", qwen_model="qwen3.7-plus")

    config = store.read_config(conn, base)

    classify = next(view for view in config.features if view.feature == CLASSIFY)
    assert classify.provider == "qwen"
    assert classify.model == "qwen3.7-plus"
    assert classify.stored is False
    assert config.key("qwen").present is True
    assert config.key("qwen").stored is False


def test_읽기가_저장을_하지_않는다(conn: sqlite3.Connection) -> None:
    """`app/settings.py` 와 다른 점이다. 지킬 값이 없으므로 읽는 김에 채우지 않는다."""
    store.read_config(conn, env())

    assert rows(conn) == {}


def test_저장하면_DB_값이_이긴다(conn: sqlite3.Connection) -> None:
    base = env(classify_provider="gemini", gemini_model="gemini-3.5-flash")

    config = store.write_feature(conn, CLASSIFY, "qwen", "qwen3.8-flash", base)

    classify = next(view for view in config.features if view.feature == CLASSIFY)
    assert classify.provider == "qwen"
    assert classify.model == "qwen3.8-flash"
    assert classify.stored is True
    assert store.settings_for(conn, CLASSIFY, base).classify_provider == "qwen"
    assert store.settings_for(conn, CLASSIFY, base).qwen_model == "qwen3.8-flash"


def test_저장한_키가_호출에_실린다(conn: sqlite3.Connection) -> None:
    base = env(classify_provider="qwen")

    store.write_key(conn, "qwen", "저장한-qwen-키", base)

    assert store.settings_for(conn, CLASSIFY, base).qwen_api_key == "저장한-qwen-키"


def test_환경변수를_바꿔도_저장된_값을_덮지_않는다(conn: sqlite3.Connection) -> None:
    """배포가 값을 고쳐도 화면에서 정한 것이 이긴다 (`app/settings.py` 와 같은 규칙)."""
    store.write_key(conn, "gemini", "화면에서-넣은-키", env())
    store.write_feature(conn, CLASSIFY, "gemini", "gemini-3.6-flash", env())

    나중 = env(gemini_api_key="배포가-바꾼-키", gemini_model="gemini-3.1-pro-preview")
    resolved = store.settings_for(conn, CLASSIFY, 나중)

    assert resolved.gemini_api_key == "화면에서-넣은-키"
    assert resolved.gemini_model == "gemini-3.6-flash"


def test_지운_키는_환경변수로_돌아간다(conn: sqlite3.Connection) -> None:
    store.write_key(conn, "gemini", "화면에서-넣은-키", env())

    store.write_key(conn, "gemini", "   ", env())

    assert store.settings_for(conn, CLASSIFY, env()).gemini_api_key == "환경변수-gemini-키"
    assert store.key_row("gemini") not in rows(conn)


def test_키_없는_제공자를_기능에_지정하면_거절한다(conn: sqlite3.Connection) -> None:
    """조용히 다른 제공자로 넘어가지 않는다 (`.claude/rules/llm.md`)."""
    base = env(claude_api_key="")

    with pytest.raises(store.LlmSettingError) as caught:
        store.write_feature(conn, CLASSIFY, "claude", "", base)

    assert "claude" in str(caught.value)
    assert rows(conn) == {}


def test_모르는_제공자는_거절한다(conn: sqlite3.Connection) -> None:
    with pytest.raises(store.LlmSettingError):
        store.write_feature(conn, CLASSIFY, "llama", "", env())


def test_스키마를_강제하지_못하는_모델은_분류에_지정할_수_없다(conn: sqlite3.Connection) -> None:
    """별칭은 `json_object` 까지만 된다. 판정 칸의 닫힌 목록이 여기 걸려 있다."""
    with pytest.raises(store.LlmSettingError) as caught:
        store.write_feature(conn, CLASSIFY, "qwen", "qwen-plus", env())

    assert "qwen-plus" in str(caught.value)
    # 같은 조합이라도 셀렉터 생성에는 쓸 수 있다. 거기에는 거절할 길이 있다
    store.write_feature(conn, SELECTOR_GENERATE, "qwen", "qwen-plus", env())


def test_같은_제공자를_쓰는_두_기능이_다른_모델을_쓴다(conn: sqlite3.Connection) -> None:
    """모델을 제공자가 아니라 기능에 붙인 이유가 이것이다 (2026-08-27 결정)."""
    base = env()
    store.write_feature(conn, SELECTOR_GENERATE, "gemini", "gemini-3.1-pro-preview", base)
    store.write_feature(conn, CLASSIFY, "gemini", "gemini-3.6-flash", base)

    생성 = store.settings_for(conn, SELECTOR_GENERATE, base)
    분류 = store.settings_for(conn, CLASSIFY, base)

    assert 생성.gemini_model == "gemini-3.1-pro-preview"
    assert 분류.gemini_model == "gemini-3.6-flash"
    assert 생성.selector_generate_provider == "gemini"
    assert 분류.classify_provider == "gemini"


def test_모델을_비우면_그_제공자의_환경변수_모델을_따라간다(conn: sqlite3.Connection) -> None:
    """지금 값을 베껴 두면 배포가 모델을 올려도 이 기능만 옛 모델에 남는다."""
    store.write_feature(conn, SELECTOR_REPAIR, "gemini", "gemini-3.6-flash", env())

    store.write_feature(conn, SELECTOR_REPAIR, "gemini", "", env())

    올린_뒤 = env(gemini_model="gemini-3.1-pro-preview")
    assert store.settings_for(conn, SELECTOR_REPAIR, 올린_뒤).gemini_model == (
        "gemini-3.1-pro-preview"
    )
    assert store.model_row(SELECTOR_REPAIR) not in rows(conn)


def test_값은_app_settings_에_들어간다(conn: sqlite3.Connection) -> None:
    """새 표도 새 마이그레이션도 만들지 않았다 (`app/notify/settings.py` 와 같다)."""
    store.write_key(conn, "qwen", "sk-저장", env())
    store.write_feature(conn, CLASSIFY, "qwen", "qwen3.8-flash", env())

    assert rows(conn) == {
        "llm_key_qwen": "sk-저장",
        "llm_provider_classify": "qwen",
        "llm_model_classify": "qwen3.8-flash",
    }


def test_연결이_없으면_환경변수_그대로다(conn: sqlite3.Connection) -> None:
    """저장소를 몰래 열지 않는다. 부르는 쪽이 준 연결만 읽는다."""
    store.write_feature(conn, CLASSIFY, "qwen", "qwen3.8-flash", env())

    base = env(classify_provider="gemini")
    assert store.settings_for(None, CLASSIFY, base).classify_provider == "gemini"


def test_표가_없어도_읽기는_서지_않는다(tmp_path: pathlib.Path) -> None:
    """읽기가 분류를 멈추게 두지 않는다. 못 읽은 값은 환경변수로 떨어진다."""
    connection = db.connect(tmp_path / "빈.db")
    base = env(classify_provider="gemini")
    try:
        assert store.settings_for(connection, CLASSIFY, base).classify_provider == "gemini"
        assert store.read_config(connection, base).key("gemini").present is True
    finally:
        connection.close()
