"""실제 `migrations/` 를 임시 DB 에 적용·역적용해 스키마를 확인한다."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from app import db

# .claude/docs/data-model.md 의 컬럼. 문서에 없는 컬럼은 늘리지 않는다
EXPECTED_COLUMNS = {
    "crawlers": {
        "id",
        "name",
        "list_url",
        "detail_url",
        "selectors_json",
        "render_mode",
        "status",
        "created_at",
    },
    "workflows": {
        "id",
        "crawler_id",
        "name",
        "interval_minutes",
        "status",
        "success_count",
        "fail_count",
        "last_run_at",
        "auto_stop_threshold",
    },
    "crawl_runs": {
        "id",
        "workflow_id",
        "crawler_id",
        "started_at",
        "finished_at",
        "status",
        "success_count",
        "new_count",
        "fail_count",
        "error_class",
        "error_message",
    },
    "raw_jobs": {
        "id",
        "workflow_id",
        "source_url",
        "raw_data_json",
        "content_hash",
        "crawled_at",
    },
    "normalized_jobs": {
        "id",
        "raw_job_id",
        "company",
        "title",
        "department",
        "deadline",
        "body",
        "requirements",
        "source_url",
        "normalized_at",
        "delivered_at",
    },
    "normalization_rules": {
        "id",
        "field_name",
        "rule_type",
        "rule_config_json",
        "priority",
        "enabled",
    },
    "app_settings": {
        "key",
        "value",
        "updated_at",
    },
}

EXPECTED_INDEXES = {"idx_raw_jobs_content_hash", "idx_normalized_jobs_normalized_at"}

# 지금까지의 마이그레이션. 전부 역적용해야 테이블이 사라진다
ALL_VERSIONS = ["0001", "0002", "0003"]


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "schema.db")
    yield connection
    connection.close()


def _names(connection: sqlite3.Connection, kind: str) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE 'sqlite_%'", (kind,)
    ).fetchall()
    return {row["name"] for row in rows}


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def test_initial_migration_is_the_first_version() -> None:
    migrations = db.load_migrations()

    assert migrations[0].version == "0001"
    assert migrations[0].name == "initial_schema"
    assert [migration.version for migration in migrations] == ALL_VERSIONS


def test_crawl_runs_holds_a_test_run_without_a_workflow(conn: sqlite3.Connection) -> None:
    """승격 전 크롤러의 1회 실행도 행을 남긴다. 어디에도 안 걸린 실행은 막는다."""
    db.migrate_up(conn)
    conn.execute(
        "INSERT INTO crawlers (name, list_url) VALUES (?, ?)", ("테스트", "https://example.test")
    )

    conn.execute("INSERT INTO crawl_runs (crawler_id) VALUES (1)")

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO crawl_runs (workflow_id, crawler_id) VALUES (NULL, NULL)")


def test_down_keeps_workflow_runs_and_drops_test_runs(conn: sqlite3.Connection) -> None:
    """0001 스키마는 workflow_id 가 NULL 인 행을 담지 못한다. 역적용은 그 행을 버린다."""
    db.migrate_up(conn)
    conn.execute(
        "INSERT INTO crawlers (name, list_url) VALUES (?, ?)", ("테스트", "https://example.test")
    )
    conn.execute("INSERT INTO workflows (crawler_id, name) VALUES (1, '워크플로우')")
    conn.execute("INSERT INTO crawl_runs (workflow_id) VALUES (1)")
    conn.execute("INSERT INTO crawl_runs (crawler_id) VALUES (1)")

    # 0002 까지 되돌린다. 뒤에 붙은 마이그레이션 수만큼 steps 가 늘어난다
    db.migrate_down(conn, steps=len(ALL_VERSIONS) - 1)

    rows = conn.execute("SELECT workflow_id FROM crawl_runs").fetchall()
    assert [row["workflow_id"] for row in rows] == [1]


def test_up_creates_the_declared_tables(conn: sqlite3.Connection) -> None:
    db.migrate_up(conn)

    tables = _names(conn, "table")
    assert set(EXPECTED_COLUMNS) <= tables


def test_up_creates_the_two_indexes(conn: sqlite3.Connection) -> None:
    db.migrate_up(conn)

    assert EXPECTED_INDEXES <= _names(conn, "index")


@pytest.mark.parametrize("table", sorted(EXPECTED_COLUMNS))
def test_columns_match_the_data_model(conn: sqlite3.Connection, table: str) -> None:
    db.migrate_up(conn)

    assert _columns(conn, table) == EXPECTED_COLUMNS[table]


def test_foreign_key_is_enforced(conn: sqlite3.Connection) -> None:
    db.migrate_up(conn)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO workflows (crawler_id, name) VALUES (?, ?)", (999, "없는 크롤러"))


def test_status_check_constraints(conn: sqlite3.Connection) -> None:
    db.migrate_up(conn)
    conn.execute(
        "INSERT INTO crawlers (name, list_url) VALUES (?, ?)", ("테스트", "https://example.com")
    )

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE crawlers SET status = 'unknown' WHERE id = 1")


def test_down_removes_the_tables_and_indexes(conn: sqlite3.Connection) -> None:
    db.migrate_up(conn)

    assert db.migrate_down(conn, steps=len(ALL_VERSIONS)) == list(reversed(ALL_VERSIONS))
    assert not set(EXPECTED_COLUMNS) & _names(conn, "table")
    assert not EXPECTED_INDEXES & _names(conn, "index")
    assert db.applied_versions(conn) == []


def test_up_after_down_restores_the_same_schema(conn: sqlite3.Connection) -> None:
    db.migrate_up(conn)
    before = _names(conn, "table") | _names(conn, "index")
    db.migrate_down(conn, steps=len(ALL_VERSIONS))

    db.migrate_up(conn)

    assert _names(conn, "table") | _names(conn, "index") == before
    assert db.applied_versions(conn) == ALL_VERSIONS
