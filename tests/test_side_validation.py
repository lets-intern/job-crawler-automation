"""부가 워크플로우 값 검증. 범위 밖 값이 거절되고 사유가 낱말로 나오는지 본다.

표의 CHECK 가 같은 것을 대부분 막지만 `sqlite3.IntegrityError` 는 어느 칸이 왜 틀렸는지
말해 주지 않는다. 그래서 이 파일은 거절되는 것만이 아니라 **사유 문장에 무엇이 적혀 있는지**
까지 단언한다.

가르는 것이 하나 더 있다. `target_scope` 는 종류마다 받는 값이 다르다 — 분류는 넷,
전달은 셋이다. 합집합으로 두면 전달 워크플로우에 `unclassified` 가 저장되고, 그것은 실행할
때 대상을 못 찾는 것으로 드러난다.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from app import db
from app.classify.batch import MAX_LIMIT
from app.side import store


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "side.db")
    db.migrate_up(connection)
    try:
        yield connection
    finally:
        connection.close()


def rejected(conn: sqlite3.Connection, **overrides: object) -> str:
    """거절 사유 문장. 거절되지 않으면 테스트가 여기서 실패한다."""
    values: dict[str, object] = {"kind": "classify", "name": "분류"}
    values.update(overrides)
    with pytest.raises(store.SideWorkflowError) as caught:
        store.create(conn, **values)  # type: ignore[arg-type]
    return str(caught.value)


@pytest.mark.parametrize("scope", ["unclassified", "empty_fields", "all"])
def test_classify_takes_its_own_scopes(conn: sqlite3.Connection, scope: str) -> None:
    created = store.create(conn, kind="classify", name="분류", target_scope=scope)

    assert created.target_scope == scope


@pytest.mark.parametrize("scope", ["undelivered", "all"])
def test_deliver_takes_its_own_scopes(conn: sqlite3.Connection, scope: str) -> None:
    created = store.create(conn, kind="deliver", name="전달", target_scope=scope)

    assert created.target_scope == scope


def test_deliver_does_not_take_a_classify_scope(conn: sqlite3.Connection) -> None:
    """전달에는 분류할 것이 없다. 사유가 종류와 받는 값을 함께 적는다."""
    message = rejected(conn, kind="deliver", name="전달", target_scope="unclassified")

    assert "unclassified" in message
    assert "deliver" in message
    assert "undelivered, recent, all" in message


def test_classify_does_not_take_a_deliver_scope(conn: sqlite3.Connection) -> None:
    """분류에는 전달 여부라는 것이 없다."""
    message = rejected(conn, target_scope="undelivered")

    assert "undelivered" in message
    assert "classify" in message
    assert "unclassified, empty_fields, recent, all" in message


def test_recent_needs_a_day_count(conn: sqlite3.Connection) -> None:
    message = rejected(conn, target_scope="recent")

    assert "recent" in message
    assert "1 이상" in message


def test_a_day_count_outside_recent_is_rejected(conn: sqlite3.Connection) -> None:
    """`recent` 가 아닌데 일수가 있으면 그 값이 쓰이는 값인지 남은 값인지 알 수 없다."""
    message = rejected(conn, target_scope="unclassified", target_days=7)

    assert "unclassified" in message
    assert "recent" in message


def test_recent_with_a_day_count_is_stored(conn: sqlite3.Connection) -> None:
    created = store.create(conn, kind="classify", name="분류", target_scope="recent", target_days=7)

    assert (created.target_scope, created.target_days) == ("recent", 7)


@pytest.mark.parametrize("batch_limit", [0, -1, MAX_LIMIT + 1])
def test_batch_limit_outside_the_bound_is_rejected(
    conn: sqlite3.Connection, batch_limit: int
) -> None:
    """상한은 `app/classify/batch.py` 의 `MAX_LIMIT` 이다. 여기에 숫자를 다시 적지 않는다."""
    message = rejected(conn, batch_limit=batch_limit)

    assert str(MAX_LIMIT) in message
    assert str(batch_limit) in message


@pytest.mark.parametrize("batch_limit", [1, MAX_LIMIT])
def test_batch_limit_on_the_bound_is_stored(conn: sqlite3.Connection, batch_limit: int) -> None:
    created = store.create(conn, kind="classify", name="분류", batch_limit=batch_limit)

    assert created.batch_limit == batch_limit


def test_a_blank_name_is_rejected(conn: sqlite3.Connection) -> None:
    assert "이름" in rejected(conn, name="   ")


def test_a_name_is_stored_trimmed(conn: sqlite3.Connection) -> None:
    created = store.create(conn, kind="classify", name="  분류 주기  ")

    assert created.name == "분류 주기"


def test_an_unknown_kind_status_or_trigger_is_rejected(conn: sqlite3.Connection) -> None:
    assert "classify" in rejected(conn, kind="정규화")
    assert "active" in rejected(conn, status="돌는중")
    assert "after_crawl" in rejected(conn, trigger_kind="cron")
    assert "1분" in rejected(conn, trigger_kind="interval", interval_minutes=0)


def test_a_rejected_create_stores_nothing(conn: sqlite3.Connection) -> None:
    """하나라도 걸리면 아무것도 저장되지 않는다."""
    rejected(conn, target_scope="undelivered")
    rejected(conn, batch_limit=MAX_LIMIT + 1)

    assert store.list_all(conn) == []


def test_update_checks_the_scope_against_the_stored_kind(conn: sqlite3.Connection) -> None:
    """종류는 저장된 것으로 본다. 고치는 폼이 보낸 종류를 믿지 않는다."""
    created = store.create(conn, kind="deliver", name="전달")

    with pytest.raises(store.SideWorkflowError) as caught:
        store.update(
            conn,
            created.id,
            name="전달",
            status="active",
            trigger_kind="interval",
            interval_minutes=60,
            target_scope="empty_fields",
            target_days=None,
            batch_limit=50,
        )

    assert "deliver" in str(caught.value)
    assert store.read(conn, created.id) == created


def test_a_rejected_update_changes_nothing(conn: sqlite3.Connection) -> None:
    created = store.create(conn, kind="classify", name="분류")

    with pytest.raises(store.SideWorkflowError):
        store.update(
            conn,
            created.id,
            name="고친 이름",
            status="active",
            trigger_kind="interval",
            interval_minutes=60,
            target_scope="recent",
            target_days=None,
            batch_limit=50,
        )

    assert store.read(conn, created.id) == created
