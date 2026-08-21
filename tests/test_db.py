"""마이그레이션 러너 자체를 검증한다. 실제 스키마가 아니라 임시 마이그레이션으로 돌린다."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from app import db

FIRST = """
-- migrate:up
CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT NOT NULL);

-- migrate:down
DROP TABLE widgets;
"""

SECOND = """
-- migrate:up
CREATE TABLE widget_parts (
    id INTEGER PRIMARY KEY,
    widget_id INTEGER NOT NULL REFERENCES widgets(id)
);

-- migrate:down
DROP TABLE widget_parts;
"""


@pytest.fixture
def migrations_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "0001_widgets.sql").write_text(FIRST, encoding="utf-8")
    (directory / "0002_widget_parts.sql").write_text(SECOND, encoding="utf-8")
    return directory


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "test.db")
    yield connection
    connection.close()


def _tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row["name"] for row in rows}


def test_connect_enables_foreign_keys(conn: sqlite3.Connection) -> None:
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_connect_creates_parent_directory(tmp_path: Path) -> None:
    target = tmp_path / "data" / "jobs.db"
    connection = db.connect(target)
    connection.close()
    assert target.parent.is_dir()


def test_up_applies_in_order_and_records_versions(
    conn: sqlite3.Connection, migrations_dir: Path
) -> None:
    assert db.applied_versions(conn) == []

    applied = db.migrate_up(conn, migrations_dir)

    assert applied == ["0001", "0002"]
    assert db.applied_versions(conn) == ["0001", "0002"]
    assert {"widgets", "widget_parts", db.SCHEMA_TABLE} <= _tables(conn)


def test_up_is_idempotent(conn: sqlite3.Connection, migrations_dir: Path) -> None:
    db.migrate_up(conn, migrations_dir)

    assert db.migrate_up(conn, migrations_dir) == []
    assert db.applied_versions(conn) == ["0001", "0002"]


def test_down_reverts_last_migration_only(conn: sqlite3.Connection, migrations_dir: Path) -> None:
    db.migrate_up(conn, migrations_dir)

    assert db.migrate_down(conn, steps=1, directory=migrations_dir) == ["0002"]
    assert db.applied_versions(conn) == ["0001"]
    assert "widget_parts" not in _tables(conn)
    assert "widgets" in _tables(conn)


def test_down_then_up_returns_to_the_same_state(
    conn: sqlite3.Connection, migrations_dir: Path
) -> None:
    db.migrate_up(conn, migrations_dir)
    db.migrate_down(conn, steps=2, directory=migrations_dir)

    assert db.applied_versions(conn) == []
    assert "widgets" not in _tables(conn)
    assert "widget_parts" not in _tables(conn)
    # 버전 기록 테이블은 남는다. 역적용은 스키마를 되돌리는 것이지 DB 를 지우는 것이 아니다
    assert db.SCHEMA_TABLE in _tables(conn)

    assert db.migrate_up(conn, migrations_dir) == ["0001", "0002"]
    assert db.applied_versions(conn) == ["0001", "0002"]


def test_failed_migration_leaves_no_partial_schema(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    directory = tmp_path / "broken"
    directory.mkdir()
    (directory / "0001_broken.sql").write_text(
        "-- migrate:up\n"
        "CREATE TABLE good (id INTEGER PRIMARY KEY);\n"
        "CREATE TABLE bad (id INTEGER PRIMARY KEY) NOT VALID SQL;\n"
        "-- migrate:down\n"
        "DROP TABLE good;\n",
        encoding="utf-8",
    )

    with pytest.raises(sqlite3.Error):
        db.migrate_up(conn, directory)

    assert db.applied_versions(conn) == []
    assert "good" not in _tables(conn)


def test_missing_marker_is_rejected(conn: sqlite3.Connection, tmp_path: Path) -> None:
    directory = tmp_path / "nodown"
    directory.mkdir()
    (directory / "0001_nodown.sql").write_text(
        "-- migrate:up\nCREATE TABLE t (id INTEGER PRIMARY KEY);\n", encoding="utf-8"
    )

    with pytest.raises(db.MigrationError):
        db.migrate_up(conn, directory)


def test_down_without_applied_migrations_is_a_no_op(
    conn: sqlite3.Connection, migrations_dir: Path
) -> None:
    assert db.migrate_down(conn, steps=1, directory=migrations_dir) == []
