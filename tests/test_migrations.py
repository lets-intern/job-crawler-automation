"""실제 `migrations/` 를 임시 DB 에 적용·역적용해 스키마를 확인한다."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from app import db
from app.normalize.rules import NORMALIZED_FIELDS

# .claude/docs/data-model.md 의 컬럼. 문서에 없는 컬럼은 늘리지 않는다
EXPECTED_COLUMNS = {
    "crawlers": {
        "id",
        "name",
        "list_url",
        "detail_url",
        "selectors_json",
        "list_mode",
        "detail_mode",
        "api_config_json",
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
        "skipped_count",
        "error_class",
        "error_message",
        "trigger",
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
        # 0011 이 더한 열 칸. 넷 이상의 사이트가 주는 것만 골랐다
        "start_date",
        "job_category",
        "employment_type",
        "career_level",
        "work_location",
        "headcount",
        "duties",
        "preferred",
        "hiring_process",
        "etc_info",
    },
    "normalization_rules": {
        "id",
        "field_name",
        "rule_type",
        "rule_config_json",
        "priority",
        "enabled",
        "note",
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
    "crawl_run_failures": {
        "id",
        "run_id",
        "reason",
        "title",
        "source_url",
        "message",
        "created_at",
    },
}

# 사람이 고칠 수 있는 필드. `source_url` 과 `delivered_at` 은 여기에 없다
OVERRIDABLE = ["company", "title", "department", "deadline", "body", "requirements"]

EXPECTED_INDEXES = {
    "idx_raw_jobs_content_hash",
    "idx_normalized_jobs_normalized_at",
    "idx_crawl_run_failures_run_id",
}

# 지금까지의 마이그레이션. 전부 역적용해야 테이블이 사라진다
ALL_VERSIONS = [
    "0001",
    "0002",
    "0003",
    "0004",
    "0005",
    "0006",
    "0007",
    "0008",
    "0009",
    "0010",
    "0011",
    "0012",
    "0013",
    "0014",
    "0015",
]


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

    # 0004 까지 내려가려면 그 뒤에 붙은 것들을 먼저 되돌려야 한다. 개수를 세어 구한다 —
    # 마이그레이션이 하나 붙을 때마다 이 숫자를 손으로 고치면 언젠가 잊는다
    db.migrate_down(conn, steps=len(ALL_VERSIONS) - ALL_VERSIONS.index("0004"))

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

    db.migrate_down(conn, steps=len(ALL_VERSIONS) - ALL_VERSIONS.index("0005"))

    assert "job_field_overrides" not in _names(conn, "table")
    assert conn.execute("SELECT count(*) AS n FROM raw_jobs").fetchone()["n"] == 1


def _at_0007(connection: sqlite3.Connection) -> None:
    """0008 직전 상태로 만든다. `crawlers` 에 `render_mode` 하나만 있는 스키마다."""
    db.migrate_up(connection)
    db.migrate_down(connection, steps=len(ALL_VERSIONS) - ALL_VERSIONS.index("0008"))
    assert "render_mode" in _columns(connection, "crawlers")


def test_collect_modes_copy_the_previous_render_mode(conn: sqlite3.Connection) -> None:
    """0008 은 값을 옮기기만 한다. 렌더로 돌던 크롤러가 적용 후 정적으로 떨어지면 안 된다."""
    _at_0007(conn)
    conn.execute(
        "INSERT INTO crawlers (name, list_url, render_mode) VALUES ('렌더', ?, 'playwright')",
        ("https://example.test",),
    )
    conn.execute(
        "INSERT INTO crawlers (name, list_url, render_mode) VALUES ('정적', ?, 'static')",
        ("https://example.test/2",),
    )

    db.migrate_up(conn)

    rows = conn.execute(
        "SELECT name, list_mode, detail_mode, api_config_json FROM crawlers ORDER BY id"
    ).fetchall()
    assert [(row["list_mode"], row["detail_mode"]) for row in rows] == [
        ("playwright", "playwright"),
        ("static", "static"),
    ]
    # 쓰지 않는 크롤러의 API 설정은 비어 있다. 빈 객체를 넣으면 "설정했다" 와 구분되지 않는다
    assert [row["api_config_json"] for row in rows] == [None, None]
    assert "render_mode" not in _columns(conn, "crawlers")


@pytest.mark.parametrize("column", ["list_mode", "detail_mode"])
def test_collect_mode_rejects_a_value_outside_the_three(
    conn: sqlite3.Connection, column: str
) -> None:
    db.migrate_up(conn)
    conn.execute(
        "INSERT INTO crawlers (name, list_url) VALUES (?, ?)", ("테스트", "https://example.test")
    )

    conn.execute(f"UPDATE crawlers SET {column} = 'api' WHERE id = 1")

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(f"UPDATE crawlers SET {column} = 'selenium' WHERE id = 1")


def test_collect_modes_down_restores_render_mode(conn: sqlite3.Connection) -> None:
    """역적용은 `list_mode` 를 되돌린다. `api` 는 담을 자리가 없어 정적으로 내려온다."""
    db.migrate_up(conn)
    conn.execute(
        """
        INSERT INTO crawlers (name, list_url, list_mode, detail_mode, api_config_json)
        VALUES ('API', ?, 'api', 'playwright', '{}')
        """,
        ("https://example.test",),
    )
    conn.execute(
        """
        INSERT INTO crawlers (name, list_url, list_mode, detail_mode)
        VALUES ('렌더', ?, 'playwright', 'playwright')
        """,
        ("https://example.test/2",),
    )

    db.migrate_down(conn, steps=len(ALL_VERSIONS) - ALL_VERSIONS.index("0008"))

    rows = conn.execute("SELECT name, render_mode FROM crawlers ORDER BY id").fetchall()
    assert [row["render_mode"] for row in rows] == ["static", "playwright"]
    assert "list_mode" not in _columns(conn, "crawlers")


def _rule(conn: sqlite3.Connection, rule_type: str, priority: int = 0) -> None:
    conn.execute(
        """
        INSERT INTO normalization_rules (field_name, rule_type, rule_config_json, priority, note)
        VALUES ('body', ?, '{}', ?, '메모')
        """,
        (rule_type, priority),
    )


def test_html_text_rule_type_is_allowed(conn: sqlite3.Connection) -> None:
    """0009 뒤에는 `html_text` 가 저장된다. 나머지 네 타입도 그대로다."""
    db.migrate_up(conn)

    for index, rule_type in enumerate(("mapping", "regex", "trim", "date_parse", "html_text")):
        _rule(conn, rule_type, priority=index)

    with pytest.raises(sqlite3.IntegrityError):
        _rule(conn, "uppercase")


def test_html_text_migration_keeps_the_rules_it_did_not_add(conn: sqlite3.Connection) -> None:
    """컬럼을 갈아 끼우는 동안 기존 규칙의 id 와 메모가 그대로 남는다."""
    db.migrate_up(conn)
    db.migrate_down(conn, steps=len(ALL_VERSIONS) - ALL_VERSIONS.index("0009"))
    _rule(conn, "trim", priority=7)
    before = conn.execute(
        "SELECT id, rule_type, priority, note FROM normalization_rules"
    ).fetchall()

    db.migrate_up(conn)

    after = conn.execute("SELECT id, rule_type, priority, note FROM normalization_rules").fetchall()
    assert [tuple(row) for row in after] == [tuple(row) for row in before]


def test_html_text_down_drops_only_its_own_rules(conn: sqlite3.Connection) -> None:
    """역적용은 옛 CHECK 에 담을 수 없는 `html_text` 행만 지운다. 나머지는 남는다."""
    db.migrate_up(conn)
    _rule(conn, "trim", priority=0)
    _rule(conn, "html_text", priority=5)

    db.migrate_down(conn, steps=len(ALL_VERSIONS) - ALL_VERSIONS.index("0009"))

    rows = conn.execute("SELECT rule_type FROM normalization_rules").fetchall()
    assert [row["rule_type"] for row in rows] == ["trim"]


def _at_0009(connection: sqlite3.Connection) -> None:
    """0010 직전 상태로 만든다. `crawl_runs` 에 `skipped_count` 가 아직 없는 스키마다."""
    db.migrate_up(connection)
    db.migrate_down(connection, steps=len(ALL_VERSIONS) - ALL_VERSIONS.index("0010"))
    assert "skipped_count" not in _columns(connection, "crawl_runs")


def _seed_run(connection: sqlite3.Connection) -> None:
    """실행 기록 한 행. 크롤러와 워크플로우까지 있어야 외래키가 선다."""
    connection.execute(
        "INSERT INTO crawlers (name, list_url) VALUES (?, ?)", ("테스트", "https://example.test")
    )
    connection.execute("INSERT INTO workflows (crawler_id, name) VALUES (1, '워크플로우')")
    connection.execute(
        """
        INSERT INTO crawl_runs (workflow_id, status, success_count, new_count, fail_count)
        VALUES (1, 'success', 5, 2, 1)
        """
    )


def test_skipped_count_keeps_existing_runs_and_starts_at_zero(conn: sqlite3.Connection) -> None:
    """0010 은 컬럼을 더하기만 한다. 적용 전 실행 기록이 그대로 남고 새 열은 0 이다."""
    _at_0009(conn)
    _seed_run(conn)
    before = conn.execute(
        "SELECT id, status, success_count, new_count, fail_count FROM crawl_runs"
    ).fetchall()

    db.migrate_up(conn)

    after = conn.execute(
        """
        SELECT id, status, success_count, new_count, fail_count, skipped_count
        FROM crawl_runs
        """
    ).fetchall()
    assert [tuple(row)[:5] for row in after] == [tuple(row) for row in before]
    assert [row["skipped_count"] for row in after] == [0]


def test_skipped_count_is_counted_apart_from_fail_count(conn: sqlite3.Connection) -> None:
    """건너뜀과 실패는 다른 열이다. 합치면 전부 걸러진 사이트가 정상 실행으로 보인다."""
    db.migrate_up(conn)
    _seed_run(conn)

    conn.execute("UPDATE crawl_runs SET skipped_count = 83 WHERE id = 1")

    row = conn.execute("SELECT fail_count, skipped_count FROM crawl_runs WHERE id = 1").fetchone()
    assert (row["fail_count"], row["skipped_count"]) == (1, 83)


def test_skipped_count_down_removes_only_its_own_column(conn: sqlite3.Connection) -> None:
    """역적용은 0010 이 더한 열만 지운다. 실행 기록 자체는 그대로 남는다."""
    db.migrate_up(conn)
    _seed_run(conn)
    conn.execute("UPDATE crawl_runs SET skipped_count = 7 WHERE id = 1")

    db.migrate_down(conn, steps=len(ALL_VERSIONS) - ALL_VERSIONS.index("0010"))

    assert "skipped_count" not in _columns(conn, "crawl_runs")
    row = conn.execute("SELECT fail_count, success_count FROM crawl_runs WHERE id = 1").fetchone()
    assert (row["fail_count"], row["success_count"]) == (1, 5)


def _seed_failure(connection: sqlite3.Connection, reason: str = "detail_empty") -> None:
    connection.execute(
        """
        INSERT INTO crawl_run_failures (run_id, reason, title, source_url, message)
        VALUES (1, ?, '2026 상반기 신입 채용', 'https://example.test/list', '본문이 비었다')
        """,
        (reason,),
    )


def test_run_failures_are_deleted_with_the_run_they_explain(conn: sqlite3.Connection) -> None:
    """실패 목록은 그 실행을 설명하는 기록이다. 실행이 지워지면 같이 지워진다."""
    db.migrate_up(conn)
    _seed_run(conn)
    _seed_failure(conn)
    _seed_failure(conn, reason="detail_unreachable")

    assert conn.execute("SELECT count(*) AS n FROM crawl_run_failures").fetchone()["n"] == 2

    conn.execute("DELETE FROM crawl_runs WHERE id = 1")

    assert conn.execute("SELECT count(*) AS n FROM crawl_run_failures").fetchone()["n"] == 0


def test_run_failure_needs_an_existing_run(conn: sqlite3.Connection) -> None:
    """어느 실행에도 걸리지 않은 실패 기록은 아무도 추적하지 못한다."""
    db.migrate_up(conn)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO crawl_run_failures (run_id, reason) VALUES (99, 'detail_empty')")


def test_run_failure_keeps_the_posting_it_missed(conn: sqlite3.Connection) -> None:
    """건수만으로는 고칠 수 없다. 제목과 목록에서 읽은 주소가 같이 남는다."""
    db.migrate_up(conn)
    _seed_run(conn)
    _seed_failure(conn)

    row = conn.execute(
        "SELECT run_id, reason, title, source_url, message, created_at FROM crawl_run_failures"
    ).fetchone()
    assert (row["run_id"], row["reason"]) == (1, "detail_empty")
    assert (row["title"], row["source_url"]) == (
        "2026 상반기 신입 채용",
        "https://example.test/list",
    )
    assert row["message"] == "본문이 비었다"
    assert row["created_at"]


def test_run_failure_down_drops_only_its_own_table(conn: sqlite3.Connection) -> None:
    """역적용은 0010 이 만든 표만 지운다. 실행 기록과 수집 데이터는 그대로다."""
    db.migrate_up(conn)
    _seed_run(conn)
    _seed_failure(conn)

    db.migrate_down(conn, steps=len(ALL_VERSIONS) - ALL_VERSIONS.index("0010"))

    assert "crawl_run_failures" not in _names(conn, "table")
    assert "idx_crawl_run_failures_run_id" not in _names(conn, "index")
    assert conn.execute("SELECT count(*) AS n FROM crawl_runs").fetchone()["n"] == 1


@pytest.mark.parametrize(
    "error_class",
    ["transport", "selector_miss", "parse", "list_empty", "detail_unreachable", "detail_empty"],
)
def test_run_error_class_holds_every_failure_reason(
    conn: sqlite3.Connection, error_class: str
) -> None:
    """`crawl_runs.error_class` 는 `app/crawler/failures.py` 의 `ERROR_CLASSES` 와 같은 값이다."""
    db.migrate_up(conn)
    _seed_run(conn)

    conn.execute("UPDATE crawl_runs SET error_class = ? WHERE id = 1", (error_class,))

    row = conn.execute("SELECT error_class FROM crawl_runs WHERE id = 1").fetchone()
    assert row["error_class"] == error_class


def test_run_error_class_rejects_a_reason_outside_the_six(conn: sqlite3.Connection) -> None:
    db.migrate_up(conn)
    _seed_run(conn)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE crawl_runs SET error_class = 'detail_missing' WHERE id = 1")


def test_error_class_migration_keeps_the_runs_it_did_not_add(conn: sqlite3.Connection) -> None:
    """컬럼을 갈아 끼우는 동안 기존 실행의 id 와 카운트, 옛 분류가 그대로 남는다."""
    _at_0009(conn)
    _seed_run(conn)
    conn.execute("UPDATE crawl_runs SET error_class = 'selector_miss' WHERE id = 1")
    before = conn.execute(
        "SELECT id, status, success_count, fail_count, error_class FROM crawl_runs"
    ).fetchall()

    db.migrate_up(conn)

    after = conn.execute(
        "SELECT id, status, success_count, fail_count, error_class FROM crawl_runs"
    ).fetchall()
    assert [tuple(row) for row in after] == [tuple(row) for row in before]


def test_error_class_down_keeps_the_run_and_clears_only_the_new_reason(
    conn: sqlite3.Connection,
) -> None:
    """역적용은 옛 CHECK 에 담을 수 없는 분류만 비운다. 실행 기록과 사유 문구는 남는다."""
    db.migrate_up(conn)
    _seed_run(conn)
    conn.execute(
        "UPDATE crawl_runs SET error_class = 'detail_empty', error_message = '본문이 비었다'"
    )

    db.migrate_down(conn, steps=len(ALL_VERSIONS) - ALL_VERSIONS.index("0010"))

    row = conn.execute(
        "SELECT id, error_class, error_message, fail_count FROM crawl_runs"
    ).fetchone()
    assert (row["id"], row["error_class"]) == (1, None)
    assert (row["error_message"], row["fail_count"]) == ("본문이 비었다", 1)


# 0011 이 더한 칸. `migrations/0011_split_body_columns.sql` 의 표와 같은 목록이어야 한다
SPLIT_BODY_COLUMNS = [
    "start_date",
    "job_category",
    "employment_type",
    "career_level",
    "work_location",
    "headcount",
    "duties",
    "preferred",
    "hiring_process",
    "etc_info",
]

# 0011 이 건드리지 않는 칸. 소비 측이 읽던 것이라 이름도 뜻도 그대로다
KEPT_COLUMNS = "company, title, department, deadline, body, requirements, source_url"


def _at_0010(connection: sqlite3.Connection) -> None:
    """0011 직전 상태로 만든다. `normalized_jobs` 가 아직 여섯 칸인 스키마다."""
    db.migrate_up(connection)
    db.migrate_down(connection, steps=len(ALL_VERSIONS) - ALL_VERSIONS.index("0011"))
    assert "start_date" not in _columns(connection, "normalized_jobs")


def _seed_normalized(connection: sqlite3.Connection) -> None:
    """정규화된 공고 한 행. 여섯 칸에 값이 다 들어 있다."""
    _seed_raw_job(connection)
    connection.execute(
        """
        INSERT INTO normalized_jobs
               (raw_job_id, company, title, department, deadline, body, requirements,
                source_url)
        VALUES (1, '한화생명', '마케팅 기획', '', '2026-08-25', '본문', '자격요건',
                'https://example.test/1')
        """
    )


def test_split_body_only_adds_columns_and_keeps_the_existing_values(
    conn: sqlite3.Connection,
) -> None:
    """0011 은 더하기만 한다. 적용 전 공고의 여섯 칸이 글자 하나까지 그대로 남는다."""
    _at_0010(conn)
    _seed_normalized(conn)
    before = conn.execute(f"SELECT id, {KEPT_COLUMNS} FROM normalized_jobs").fetchall()

    db.migrate_up(conn)

    after = conn.execute(f"SELECT id, {KEPT_COLUMNS} FROM normalized_jobs").fetchall()
    assert [tuple(row) for row in after] == [tuple(row) for row in before]
    assert set(SPLIT_BODY_COLUMNS) <= _columns(conn, "normalized_jobs")


def test_split_body_leaves_the_new_columns_empty(conn: sqlite3.Connection) -> None:
    """사이트가 주지 않는 칸은 빈 칸이다. 기본값으로 채우지 않는다."""
    _at_0010(conn)
    _seed_normalized(conn)

    db.migrate_up(conn)

    row = conn.execute(f"SELECT {', '.join(SPLIT_BODY_COLUMNS)} FROM normalized_jobs").fetchone()
    assert [row[name] for name in SPLIT_BODY_COLUMNS] == [None] * len(SPLIT_BODY_COLUMNS)


def test_split_body_down_drops_only_the_ten_it_added(conn: sqlite3.Connection) -> None:
    """역적용은 더한 열 칸만 지운다. 공고와 여섯 칸의 값은 그대로다."""
    db.migrate_up(conn)
    _seed_normalized(conn)
    conn.execute("UPDATE normalized_jobs SET work_location = '서울', headcount = '0명'")
    before = conn.execute(f"SELECT id, {KEPT_COLUMNS} FROM normalized_jobs").fetchall()

    db.migrate_down(conn, steps=len(ALL_VERSIONS) - ALL_VERSIONS.index("0011"))

    after = conn.execute(f"SELECT id, {KEPT_COLUMNS} FROM normalized_jobs").fetchall()
    assert [tuple(row) for row in after] == [tuple(row) for row in before]
    assert not set(SPLIT_BODY_COLUMNS) & _columns(conn, "normalized_jobs")


def test_the_override_check_covers_the_new_columns(conn: sqlite3.Connection) -> None:
    """0012 가 넓혔다. 새 칸에 자동으로 뽑은 값이 틀렸을 때 사람이 고칠 수 있어야 한다."""
    db.migrate_up(conn)
    _seed_raw_job(conn)

    for field in NORMALIZED_FIELDS:
        conn.execute(
            "INSERT INTO job_field_overrides (raw_job_id, field_name, value) VALUES (1, ?, ?)",
            (field, "사람이 고친 값"),
        )

    stored = conn.execute("SELECT count(*) AS n FROM job_field_overrides").fetchone()
    assert stored["n"] == len(NORMALIZED_FIELDS)


def test_the_override_check_still_refuses_a_column_that_is_not_normalized(
    conn: sqlite3.Connection,
) -> None:
    """넓어진 것은 `normalized_jobs` 의 칸까지다. `source_url` 은 공고의 신원이라 못 고친다."""
    db.migrate_up(conn)
    _seed_raw_job(conn)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO job_field_overrides (raw_job_id, field_name, value) VALUES (1, ?, ?)",
            ("source_url", "https://example.test/other"),
        )


def test_the_override_migration_keeps_the_rows_it_did_not_add(conn: sqlite3.Connection) -> None:
    """표를 다시 만드는 마이그레이션이다. 있던 보정이 id 까지 그대로 넘어와야 한다."""
    db.migrate_up(conn)
    db.migrate_down(conn, steps=1)
    _seed_raw_job(conn)
    conn.execute(
        "INSERT INTO job_field_overrides (raw_job_id, field_name, value) VALUES (1, ?, ?)",
        ("title", "사람이 고친 제목"),
    )
    before = conn.execute("SELECT id, created_at FROM job_field_overrides").fetchone()

    db.migrate_up(conn)

    after = conn.execute(
        "SELECT id, field_name, value, created_at FROM job_field_overrides"
    ).fetchall()
    assert len(after) == 1
    assert after[0]["id"] == before["id"]
    assert after[0]["value"] == "사람이 고친 제목"
    assert after[0]["created_at"] == before["created_at"]


def test_the_override_down_drops_the_corrections_the_old_check_cannot_hold(
    conn: sqlite3.Connection,
) -> None:
    """되돌리면 새 칸의 보정은 사라진다. 옛 CHECK 에 담을 자리가 없다."""
    db.migrate_up(conn)
    _seed_raw_job(conn)
    conn.executemany(
        "INSERT INTO job_field_overrides (raw_job_id, field_name, value) VALUES (1, ?, ?)",
        [("title", "사람이 고친 제목"), ("work_location", "서울")],
    )

    # 0012 까지 되돌린다. 뒤에 붙은 마이그레이션 수만큼 걸음이 늘어난다
    db.migrate_down(conn, steps=len(ALL_VERSIONS) - ALL_VERSIONS.index("0012"))

    rows = conn.execute("SELECT field_name FROM job_field_overrides").fetchall()
    assert [row["field_name"] for row in rows] == ["title"]
    assert conn.execute("SELECT count(*) AS n FROM raw_jobs").fetchone()["n"] == 1
