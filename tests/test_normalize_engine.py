"""규칙 엔진 테스트.

원문 값이 들어가서 어떤 값이 나오는지를 타입별로 단언하고, 같은 필드에 규칙이 여럿일 때의
적용 순서를 확인한다.

원문은 저장된 python.org 픽스처에서 뽑는다. 실사이트에 나가지 않는다.

마지막 테스트가 이 파일의 이유다. 정규화를 돌린 뒤 `raw_jobs` 가 한 바이트도 달라지지
않았는지 본다 (`.claude/rules/data-safety.md`).
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest

from app import db
from app.crawler.parser import parse_detail
from app.normalize.engine import (
    NormalizeError,
    RawJobMissingError,
    insert_normalized,
    load_rules,
    normalize_fields,
)
from app.normalize.rules import build_rule
from app.selector.schema import DetailSelectors

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
DETAIL_HTML = (FIXTURES / "pythonorg-job-detail-20260821.html").read_text(encoding="utf-8")

DETAIL_SELECTORS = DetailSelectors(
    title="h1.listing-company span.company-name",
    body="div.job-description",
    requirements="",
    deadline="",
    department="span.listing-company-category a",
)


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    try:
        yield connection
    finally:
        connection.close()


def fixture_record() -> dict[str, str]:
    """픽스처에서 뽑은 원문 필드. `raw_jobs.raw_data_json` 에 들어가는 모양 그대로다."""
    parsed = parse_detail(DETAIL_HTML, DETAIL_SELECTORS)
    return {"source_url": "https://www.python.org/jobs/7891/", **parsed.fields}


def add_raw(conn: sqlite3.Connection, record: dict[str, Any]) -> int:
    conn.execute(
        "INSERT INTO crawlers (name, list_url) VALUES ('python.org', 'https://www.python.org/jobs/')"
    )
    conn.execute("INSERT INTO workflows (crawler_id, name) VALUES (1, 'python.org')")
    cursor = conn.execute(
        """
        INSERT INTO raw_jobs (workflow_id, source_url, raw_data_json, content_hash)
        VALUES (1, ?, ?, 'hash-1')
        """,
        (record["source_url"], json.dumps(record, ensure_ascii=False)),
    )
    return int(cursor.lastrowid or 0)


def raw_snapshot(conn: sqlite3.Connection) -> str:
    """`raw_jobs` 전체를 바이트로 굳힌 값. 한 글자만 달라져도 해시가 바뀐다."""
    rows = conn.execute(
        """
        SELECT id, workflow_id, source_url, raw_data_json, content_hash, crawled_at
          FROM raw_jobs ORDER BY id
        """
    ).fetchall()
    digest = hashlib.sha256()
    for row in rows:
        for value in tuple(row):
            digest.update(repr(value).encode("utf-8"))
            digest.update(b"\x1f")
        digest.update(b"\x1e")
    return digest.hexdigest()


def test_trim_collapses_whitespace() -> None:
    rule = build_rule("title", "trim", {})
    assert normalize_fields({"title": "  파이썬  \n  백엔드 개발자 "}, [rule]) == {
        "company": None,
        "title": "파이썬 백엔드 개발자",
        "department": None,
        "deadline": None,
        "body": None,
        "requirements": None,
        "company_source": None,
    }


def test_trim_with_strip_chars() -> None:
    rule = build_rule("department", "trim", {"collapse_whitespace": False, "strip_chars": "-· "})
    assert normalize_fields({"department": "-· 개발 ·-"}, [rule])["department"] == "개발"


def test_regex_removes_matched_text() -> None:
    rule = build_rule("title", "regex", {"pattern": r"\[광고\]\s*", "replacement": ""})
    assert normalize_fields({"title": "[광고] 백엔드 개발자"}, [rule])["title"] == "백엔드 개발자"


def test_mapping_replaces_exact_value() -> None:
    rule = build_rule("department", "mapping", {"map": {"Engineering": "개발"}})
    assert normalize_fields({"department": "Engineering"}, [rule])["department"] == "개발"


def test_mapping_keeps_value_without_default() -> None:
    rule = build_rule("department", "mapping", {"map": {"Engineering": "개발"}})
    assert normalize_fields({"department": "Design"}, [rule])["department"] == "Design"


def test_mapping_uses_default_when_missing() -> None:
    rule = build_rule("department", "mapping", {"map": {"Engineering": "개발"}, "default": "기타"})
    assert normalize_fields({"department": "Design"}, [rule])["department"] == "기타"


def test_date_parse_reformats() -> None:
    rule = build_rule("deadline", "date_parse", {"formats": ["%Y년 %m월 %d일", "%Y.%m.%d"]})
    assert normalize_fields({"deadline": "2026.09.30"}, [rule])["deadline"] == "2026-09-30"
    assert normalize_fields({"deadline": "2026년 9월 3일"}, [rule])["deadline"] == "2026-09-03"


def test_date_parse_failure_is_an_error() -> None:
    """읽지 못한 값을 원문 그대로 통과시키지 않는다. deadline 컬럼이 날짜가 아니게 된다."""
    rule = build_rule("deadline", "date_parse", {"formats": ["%Y.%m.%d"]})
    with pytest.raises(NormalizeError) as caught:
        normalize_fields({"deadline": "상시채용"}, [rule])
    assert caught.value.field_name == "deadline"
    assert caught.value.rule_type == "date_parse"


def test_priority_decides_order() -> None:
    """앞 규칙의 결과가 뒤 규칙의 입력이다. 순서가 뒤집히면 결과가 달라진다."""
    strip_prefix = build_rule(
        "deadline", "regex", {"pattern": "^마감\\s*:\\s*", "replacement": ""}, priority=0
    )
    parse = build_rule("deadline", "date_parse", {"formats": ["%Y.%m.%d"]}, priority=1)

    assert (
        normalize_fields({"deadline": "마감: 2026.09.30"}, [parse, strip_prefix])["deadline"]
        == "2026-09-30"
    )

    # 순서를 뒤집으면 날짜로 읽을 수 없다. 우선순위가 실제로 적용된다는 증거다
    flipped = build_rule("deadline", "date_parse", {"formats": ["%Y.%m.%d"]}, priority=-1)
    with pytest.raises(NormalizeError):
        normalize_fields({"deadline": "마감: 2026.09.30"}, [strip_prefix, flipped])


def test_same_priority_falls_back_to_id() -> None:
    first = build_rule("title", "regex", {"pattern": "A", "replacement": "B"}, rule_id=1)
    second = build_rule("title", "regex", {"pattern": "B", "replacement": "C"}, rule_id=2)
    assert normalize_fields({"title": "A"}, [second, first])["title"] == "C"


def test_disabled_rule_is_skipped() -> None:
    off = build_rule(
        "title", "regex", {"pattern": "개발자", "replacement": "엔지니어"}, enabled=False
    )
    on = build_rule("title", "trim", {}, priority=1)
    assert normalize_fields({"title": " 백엔드 개발자 "}, [off, on])["title"] == "백엔드 개발자"


def test_empty_value_skips_rules() -> None:
    """값이 없는 필드에 규칙을 태우지 않는다. 없는 값이 규칙 실패로 둔갑하지 않는다."""
    rule = build_rule("deadline", "date_parse", {"formats": ["%Y.%m.%d"]})
    assert normalize_fields({"deadline": ""}, [rule])["deadline"] is None
    assert normalize_fields({}, [rule])["deadline"] is None


def test_no_rules_passes_values_through() -> None:
    record = fixture_record()
    fields = normalize_fields(record, [])
    assert fields["title"] == record["title"]
    assert fields["body"] == record["body"]
    # 픽스처의 셀렉터가 뽑지 않는 필드는 NULL 이다
    assert fields["company"] is None
    assert fields["deadline"] is None


def test_load_rules_reads_stored_rows(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT INTO normalization_rules (field_name, rule_type, rule_config_json, priority, enabled)
        VALUES ('title', 'trim', '{}', 2, 1), ('title', 'regex', '{"pattern": "x"}', 1, 0)
        """
    )
    rules = load_rules(conn)
    assert [(rule.field_name, rule.rule_type, rule.priority, rule.enabled) for rule in rules] == [
        ("title", "regex", 1, False),
        ("title", "trim", 2, True),
    ]


def test_load_rules_rejects_broken_stored_config(conn: sqlite3.Connection) -> None:
    """손으로 고쳐 넣은 깨진 설정을 조용히 넘기지 않는다."""
    conn.execute(
        """
        INSERT INTO normalization_rules (field_name, rule_type, rule_config_json)
        VALUES ('title', 'regex', '{"pattern": "(["}')
        """
    )
    with pytest.raises(NormalizeError):
        load_rules(conn)


def test_insert_normalized_writes_one_row(conn: sqlite3.Connection) -> None:
    record = fixture_record()
    raw_id = add_raw(conn, record)
    rule = build_rule("title", "trim", {})

    normalized_id = insert_normalized(conn, raw_id, [rule])

    row = conn.execute("SELECT * FROM normalized_jobs WHERE id = ?", (normalized_id,)).fetchone()
    assert row["raw_job_id"] == raw_id
    assert row["source_url"] == record["source_url"]
    # trim 은 양끝을 깎고 연속 공백을 하나로 접는다
    assert row["title"] == " ".join(record["title"].split())
    assert row["normalized_at"]
    # 제공 API 경로만 쓴다. 정규화는 건드리지 않는다
    assert row["delivered_at"] is None


def test_missing_raw_job_is_reported(conn: sqlite3.Connection) -> None:
    with pytest.raises(RawJobMissingError):
        insert_normalized(conn, 999, [])


def test_broken_raw_data_json_fails_that_row(conn: sqlite3.Connection) -> None:
    add_raw(conn, fixture_record())
    conn.execute("UPDATE raw_jobs SET raw_data_json = '{not json' WHERE id = 1")
    with pytest.raises(NormalizeError):
        insert_normalized(conn, 1, [])


def test_raw_jobs_is_untouched_by_normalization(conn: sqlite3.Connection) -> None:
    """정규화 전후로 `raw_jobs` 가 바이트 단위로 같아야 한다.

    성공 경로와 실패 경로를 모두 태운다. 실패한 규칙이 raw 를 되돌리거나 지우지 않는지까지
    보기 위해서다.
    """
    record = fixture_record()
    raw_id = add_raw(conn, record)
    before = raw_snapshot(conn)
    before_json = conn.execute(
        "SELECT raw_data_json FROM raw_jobs WHERE id = ?", (raw_id,)
    ).fetchone()["raw_data_json"]

    insert_normalized(conn, raw_id, [build_rule("title", "trim", {})])
    insert_normalized(
        conn, raw_id, [build_rule("body", "regex", {"pattern": "\\s+", "replacement": " "})]
    )
    with pytest.raises(NormalizeError):
        insert_normalized(
            conn, raw_id, [build_rule("title", "date_parse", {"formats": ["%Y.%m.%d"]})]
        )

    assert raw_snapshot(conn) == before
    after_json = conn.execute(
        "SELECT raw_data_json FROM raw_jobs WHERE id = ?", (raw_id,)
    ).fetchone()["raw_data_json"]
    assert after_json == before_json
    assert after_json.encode("utf-8") == json.dumps(record, ensure_ascii=False).encode("utf-8")
    assert conn.execute("SELECT count(*) AS n FROM raw_jobs").fetchone()["n"] == 1
