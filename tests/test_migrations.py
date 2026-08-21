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
        "default_company",
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
        "company_source",
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
    "job_field_overrides": {
        "id",
        "raw_job_id",
        "field_name",
        "value",
        "created_at",
        "updated_at",
    },
}

# 사람이 고칠 수 있는 필드. `source_url` 과 `delivered_at` 은 여기에 없다
OVERRIDABLE = ["company", "title", "department", "deadline", "body", "requirements"]

EXPECTED_INDEXES = {"idx_raw_jobs_content_hash", "idx_normalized_jobs_normalized_at"}

# 지금까지의 마이그레이션. 전부 역적용해야 테이블이 사라진다
ALL_VERSIONS = ["0001", "0002", "0003", "0004", "0005"]


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


def test_company_columns_start_empty_and_hold_the_two_sources(conn: sqlite3.Connection) -> None:
    """0004 는 컬럼을 더하기만 한다. 기존 행은 NULL 로 남고, 그 NULL 이 "안 적었다" 는 뜻이다."""
    db.migrate_up(conn)
    conn.execute(
        "INSERT INTO crawlers (name, list_url) VALUES (?, ?)", ("이전 행", "https://example.test")
    )

    row = conn.execute("SELECT default_company FROM crawlers WHERE id = 1").fetchone()
    assert row["default_company"] is None

    conn.execute("UPDATE crawlers SET default_company = ? WHERE id = 1", ("삼성전기",))
    saved = conn.execute("SELECT default_company FROM crawlers WHERE id = 1").fetchone()
    assert saved["default_company"] == "삼성전기"


def test_company_source_rejects_a_value_outside_the_two(conn: sqlite3.Connection) -> None:
    db.migrate_up(conn)
    conn.execute(
        "INSERT INTO crawlers (name, list_url) VALUES (?, ?)", ("테스트", "https://example.test")
    )
    conn.execute("INSERT INTO workflows (crawler_id, name) VALUES (1, '워크플로우')")
    conn.execute(
        """
        INSERT INTO raw_jobs (workflow_id, source_url, raw_data_json, content_hash)
        VALUES (1, 'https://example.test/1', '{}', 'hash')
        """
    )

    conn.execute(
        """
        INSERT INTO normalized_jobs (raw_job_id, source_url, company, company_source)
        VALUES (1, 'https://example.test/1', '삼성SDS', 'parsed')
        """
    )

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO normalized_jobs (raw_job_id, source_url, company_source)
            VALUES (1, 'https://example.test/1', '운영자')
            """
        )


def test_company_down_removes_only_the_two_columns(conn: sqlite3.Connection) -> None:
    """역적용은 0004 가 더한 두 컬럼만 지운다. 나머지 컬럼은 그대로다."""
    db.migrate_up(conn)

    # 0005 를 먼저 되돌려야 0004 차례가 온다. 뒤에 마이그레이션이 붙으면 steps 가 늘어난다
    db.migrate_down(conn, steps=2)

    assert "default_company" not in _columns(conn, "crawlers")
    assert "company_source" not in _columns(conn, "normalized_jobs")
    assert "company" in _columns(conn, "normalized_jobs")


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


def _seed_raw_job(connection: sqlite3.Connection) -> None:
    """보정이 매달릴 `raw_jobs` 한 행. 크롤러와 워크플로우까지 있어야 외래키가 선다."""
    connection.execute(
        "INSERT INTO crawlers (name, list_url) VALUES (?, ?)", ("테스트", "https://example.test")
    )
    connection.execute("INSERT INTO workflows (crawler_id, name) VALUES (1, '워크플로우')")
    connection.execute(
        """
        INSERT INTO raw_jobs (workflow_id, source_url, raw_data_json, content_hash)
        VALUES (1, 'https://example.test/1', '{}', 'hash')
        """
    )


def test_one_override_per_field_of_one_job(conn: sqlite3.Connection) -> None:
    """같은 공고의 같은 필드에 보정이 둘이면 어느 쪽이 사람의 뜻인지 알 수 없다."""
    db.migrate_up(conn)
    _seed_raw_job(conn)
    conn.execute(
        """
        INSERT INTO job_field_overrides (raw_job_id, field_name, value)
        VALUES (1, 'title', '고침')
        """
    )

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO job_field_overrides (raw_job_id, field_name, value)
            VALUES (1, 'title', '또 고침')
            """
        )

    conn.execute(
        """
        INSERT INTO job_field_overrides (raw_job_id, field_name, value)
        VALUES (1, 'company', '회사')
        """
    )
    assert conn.execute("SELECT count(*) AS n FROM job_field_overrides").fetchone()["n"] == 2


@pytest.mark.parametrize("field_name", OVERRIDABLE)
def test_override_accepts_every_correctable_field(
    conn: sqlite3.Connection, field_name: str
) -> None:
    db.migrate_up(conn)
    _seed_raw_job(conn)

    conn.execute(
        "INSERT INTO job_field_overrides (raw_job_id, field_name, value) VALUES (1, ?, ?)",
        (field_name, "사람이 고친 값"),
    )

    row = conn.execute("SELECT field_name, value FROM job_field_overrides").fetchone()
    assert (row["field_name"], row["value"]) == (field_name, "사람이 고친 값")


@pytest.mark.parametrize("field_name", ["source_url", "delivered_at", "normalized_at", "id"])
def test_override_rejects_a_field_outside_the_allowlist(
    conn: sqlite3.Connection, field_name: str
) -> None:
    """`source_url` 은 공고의 신원이고, `delivered_at` 은 제공 API 만 쓴다."""
    db.migrate_up(conn)
    _seed_raw_job(conn)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO job_field_overrides (raw_job_id, field_name, value) VALUES (1, ?, ?)",
            (field_name, "값"),
        )


def test_override_needs_an_existing_raw_job(conn: sqlite3.Connection) -> None:
    """보정은 `normalized_jobs` 가 아니라 `raw_jobs` 에 매달린다. 없는 건에는 달 수 없다."""
    db.migrate_up(conn)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO job_field_overrides (raw_job_id, field_name, value)
            VALUES (99, 'title', '값')
            """
        )


def test_override_down_removes_only_its_own_table(conn: sqlite3.Connection) -> None:
    """역적용은 0005 가 만든 테이블만 지운다. 수집·정규화 데이터는 그대로다."""
    db.migrate_up(conn)
    _seed_raw_job(conn)
    conn.execute(
        """
        INSERT INTO job_field_overrides (raw_job_id, field_name, value)
        VALUES (1, 'title', '사람이 고친 값')
        """
    )

    db.migrate_down(conn, steps=1)

    assert "job_field_overrides" not in _names(conn, "table")
    assert conn.execute("SELECT count(*) AS n FROM raw_jobs").fetchone()["n"] == 1
