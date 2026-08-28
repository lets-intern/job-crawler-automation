"""부가 워크플로우 저장소. 만들고 읽으면 값이 그대로 오는지 본다.

임시 DB 에 실제 마이그레이션을 적용하고 돈다. 실사이트에도 모델에도 나가지 않는다.

읽기와 쓰기가 다르게 동작하는 것도 여기서 본다 — 없는 것을 읽으면 빈 값이고, 없는 것에
쓰면 예외다 (`app/notify/settings.py` 와 같은 규칙).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from app import db
from app.side import store


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "side.db")
    db.migrate_up(connection)
    try:
        yield connection
    finally:
        connection.close()


def test_a_created_workflow_reads_back_with_the_same_values(conn: sqlite3.Connection) -> None:
    created = store.create(
        conn,
        kind="classify",
        name="분류 주기",
        status="active",
        trigger_kind="interval",
        interval_minutes=30,
        target_scope="recent",
        target_days=7,
        batch_limit=100,
    )

    stored = store.read(conn, created.id)

    assert stored == created
    assert stored is not None
    assert (stored.kind, stored.name, stored.status) == ("classify", "분류 주기", "active")
    assert (stored.trigger_kind, stored.interval_minutes) == ("interval", 30)
    assert (stored.target_scope, stored.target_days, stored.batch_limit) == ("recent", 7, 100)
    assert stored.last_run_at is None
    assert stored.created_at


def test_a_new_workflow_starts_paused_with_its_kind_default_scope(
    conn: sqlite3.Connection,
) -> None:
    """만들자마자 도는 일이 없다. 범위를 주지 않으면 그 종류의 기본값이다."""
    classify = store.create(conn, kind="classify", name="분류")
    deliver = store.create(conn, kind="deliver", name="전달")

    assert (classify.status, classify.target_scope) == ("paused", "unclassified")
    assert (deliver.status, deliver.target_scope) == ("paused", "undelivered")
    assert (classify.trigger_kind, classify.batch_limit) == ("manual", 50)
    assert classify.target_days is None


def test_each_kind_reports_the_scopes_it_takes(conn: sqlite3.Connection) -> None:
    """화면이 고를 것을 그릴 때 쓰는 값이다. 종류마다 다르다."""
    classify = store.create(conn, kind="classify", name="분류")
    deliver = store.create(conn, kind="deliver", name="전달")

    assert classify.scopes == ("unclassified", "empty_fields", "recent", "all")
    assert deliver.scopes == ("undelivered", "recent", "all")


def test_the_list_is_in_creation_order_and_empty_when_nothing_is_stored(
    conn: sqlite3.Connection,
) -> None:
    assert store.list_all(conn) == []

    store.create(conn, kind="classify", name="먼저")
    store.create(conn, kind="deliver", name="나중")

    assert [workflow.name for workflow in store.list_all(conn)] == ["먼저", "나중"]


def test_reading_a_missing_workflow_returns_none(conn: sqlite3.Connection) -> None:
    """읽기는 예외를 던지지 않는다. 목록 화면이 행 하나 때문에 500 이 되지 않는다."""
    assert store.read(conn, 999) is None


def test_update_replaces_every_editable_column(conn: sqlite3.Connection) -> None:
    created = store.create(conn, kind="classify", name="분류")

    updated = store.update(
        conn,
        created.id,
        name="분류 고침",
        status="active",
        trigger_kind="after_crawl",
        interval_minutes=15,
        target_scope="empty_fields",
        target_days=None,
        batch_limit=200,
    )

    assert store.read(conn, created.id) == updated
    assert (updated.name, updated.status, updated.trigger_kind) == (
        "분류 고침",
        "active",
        "after_crawl",
    )
    assert (updated.interval_minutes, updated.target_scope, updated.batch_limit) == (
        15,
        "empty_fields",
        200,
    )
    # 종류와 만든 시각은 고침의 대상이 아니다
    assert (updated.kind, updated.created_at) == (created.kind, created.created_at)


def test_update_of_a_missing_workflow_is_rejected(conn: sqlite3.Connection) -> None:
    with pytest.raises(store.SideWorkflowNotFoundError):
        store.update(
            conn,
            999,
            name="없는 것",
            status="paused",
            trigger_kind="manual",
            interval_minutes=360,
            target_scope="unclassified",
            target_days=None,
            batch_limit=50,
        )


def test_delete_removes_the_workflow_and_its_runs(conn: sqlite3.Connection) -> None:
    """설정이 사라진 실행 기록은 무엇이 돌았는지 알 수 없는 행이다."""
    kept = store.create(conn, kind="classify", name="남는 것")
    removed = store.create(conn, kind="deliver", name="지울 것")
    for side_workflow_id in (kept.id, removed.id):
        conn.execute(
            "INSERT INTO side_runs (side_workflow_id, trigger) VALUES (?, 'manual')",
            (side_workflow_id,),
        )

    store.delete(conn, removed.id)

    assert store.read(conn, removed.id) is None
    assert [workflow.id for workflow in store.list_all(conn)] == [kept.id]
    remaining = conn.execute("SELECT side_workflow_id FROM side_runs").fetchall()
    assert [row["side_workflow_id"] for row in remaining] == [kept.id]


def test_delete_of_a_missing_workflow_is_rejected_and_changes_nothing(
    conn: sqlite3.Connection,
) -> None:
    kept = store.create(conn, kind="classify", name="남는 것")
    conn.execute(
        "INSERT INTO side_runs (side_workflow_id, trigger) VALUES (?, 'manual')", (kept.id,)
    )

    with pytest.raises(store.SideWorkflowNotFoundError):
        store.delete(conn, 999)

    assert [workflow.id for workflow in store.list_all(conn)] == [kept.id]
    assert conn.execute("SELECT count(*) AS n FROM side_runs").fetchone()["n"] == 1
