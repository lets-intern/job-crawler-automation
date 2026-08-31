"""키를 마스킹해서 내보내는지 (2.2.V).

읽기 함수가 화면 쪽으로 돌려주는 것은 있음·없음과 끝 네 자리뿐이다. 네 자리 이하인 값은
끝 네 자리가 곧 전체라서 아무것도 보여주지 않는다.

네 경우를 다 넣어 본다 — 빈 값, 세 자, 네 자, 긴 값. 확인하는 것은 하나다. **어느 경우에도
돌려준 것 안에 키 전체가 없다** (`../.claude/tasks/todo/prd-llm-providers.md` 4번).
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import pytest

from app import db
from app.llm import settings as store
from tests.test_llm_settings import env


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    try:
        yield connection
    finally:
        connection.close()


# 넣어 볼 값과, 화면에 보여도 되는 끝자리
CASES: tuple[tuple[str, str], ...] = (
    ("", ""),
    ("abc", ""),
    ("abcd", ""),
    ("sk-0123456789abcdef", "cdef"),
)


@pytest.mark.parametrize(("value", "tail"), CASES)
def test_끝_네_자리만_돌려준다(value: str, tail: str) -> None:
    assert store.mask(value) == tail


@pytest.mark.parametrize(("value", "tail"), CASES)
def test_읽기_응답에_키_전체가_없다(conn: sqlite3.Connection, value: str, tail: str) -> None:
    base = env(gemini_api_key="")
    store.write_key(conn, "gemini", value, base)

    view = store.read_config(conn, base).key("gemini")

    assert view.tail == tail
    if value:
        assert value not in repr(view)
        assert value not in repr(store.read_config(conn, base))


def test_환경변수에서_온_키도_마스킹된다(conn: sqlite3.Connection) -> None:
    """저장한 적이 없어도 화면에는 그린다. 그릴 때 값이 새면 저장 여부는 상관이 없다."""
    base = env(gemini_api_key="sk-환경변수-키-9999")

    view = store.read_config(conn, base).key("gemini")

    assert view.present is True
    assert view.stored is False
    assert view.tail == "9999"
    assert "sk-환경변수-키-9999" not in repr(view)


def test_키가_없으면_없다고_말한다(conn: sqlite3.Connection) -> None:
    """빈 칸을 "짧아서 가렸다" 와 같은 모양으로 그리면 둘을 구별할 수 없다."""
    view = store.read_config(conn, env(claude_api_key="")).key("claude")

    assert view.present is False
    assert view.tail == ""


def test_짧은_키는_있다고만_말한다(conn: sqlite3.Connection) -> None:
    view = store.read_config(conn, env(claude_api_key="abcd")).key("claude")

    assert view.present is True
    assert view.tail == ""
