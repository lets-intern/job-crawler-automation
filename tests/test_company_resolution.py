"""정규화 단계의 회사명 해결 테스트.

확인하는 것은 넷이다.

- 파싱값이 있으면 파싱값이 이기고 `company_source='parsed'` 다
- 파싱값이 없으면 운영자값을 쓰고 `company_source='operator'` 다
- 둘 다 없으면 `company` 와 `company_source` 가 모두 NULL 이다
- 계열사 두 건이 섞인 목록에서 두 건이 서로 다른 회사명을 받는다

픽스처로 돈다. 실사이트에 나가지 않는다.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
from typing import Any

from app.crawler.runner import run_workflow
from app.normalize.engine import COMPANY_SOURCE, OPERATOR, PARSED, normalize_fields, resolve_company
from app.normalize.rules import build_rule
from tests.test_company_selector import (
    WITH_COMPANY,
    WITHOUT_COMPANY,
    make_conn,
    stub_fetcher,
)


def add_rule(
    conn: sqlite3.Connection,
    field_name: str,
    rule_type: str,
    config: dict[str, Any],
    priority: int = 0,
) -> None:
    conn.execute(
        """
        INSERT INTO normalization_rules (field_name, rule_type, rule_config_json, priority)
        VALUES (?, ?, ?, ?)
        """,
        (field_name, rule_type, json.dumps(config), priority),
    )


def companies(conn: sqlite3.Connection) -> list[tuple[str | None, str | None]]:
    rows = conn.execute(
        "SELECT company, company_source FROM normalized_jobs ORDER BY raw_job_id"
    ).fetchall()
    return [(row["company"], row["company_source"]) for row in rows]


def test_parsed_value_wins_over_the_operator_value() -> None:
    assert resolve_company({"company": "삼성SDS"}, "삼성전자") == ("삼성SDS", PARSED)


def test_operator_value_is_used_when_nothing_was_parsed() -> None:
    assert resolve_company({"company": "   "}, "삼성전자") == ("삼성전자", OPERATOR)
    assert resolve_company({}, "삼성전자") == ("삼성전자", OPERATOR)


def test_neither_source_leaves_both_empty() -> None:
    assert resolve_company({}, None) == ("", None)
    assert resolve_company({"company": ""}, "   ") == ("", None)


async def test_two_affiliates_on_one_site_get_different_companies(
    tmp_path: pathlib.Path,
) -> None:
    """이 Push 의 이유다. 사이트 하나에 계열사 공고가 섞여도 공고마다 회사명이 따로 붙는다."""
    conn = make_conn(tmp_path / "jobs.db", WITH_COMPANY, default_company="삼성전자")
    try:
        await run_workflow(conn, 1, fetcher=stub_fetcher(), limit=2)

        assert companies(conn) == [("삼성SDS", PARSED), ("삼성전기(주)", PARSED)]
    finally:
        conn.close()


async def test_operator_value_fills_a_site_without_a_company(tmp_path: pathlib.Path) -> None:
    conn = make_conn(tmp_path / "jobs.db", WITHOUT_COMPANY, default_company="삼성전자")
    try:
        await run_workflow(conn, 1, fetcher=stub_fetcher(), limit=2)

        assert companies(conn) == [("삼성전자", OPERATOR), ("삼성전자", OPERATOR)]
    finally:
        conn.close()


async def test_no_company_anywhere_stays_null(tmp_path: pathlib.Path) -> None:
    """빈 문자열로 채우지 않는다. 빈 문자열은 "회사명이 있다" 와 구분되지 않는다."""
    conn = make_conn(tmp_path / "jobs.db", WITHOUT_COMPANY)
    try:
        await run_workflow(conn, 1, fetcher=stub_fetcher(), limit=2)

        assert companies(conn) == [(None, None), (None, None)]
    finally:
        conn.close()


async def test_rules_apply_to_the_resolved_company(tmp_path: pathlib.Path) -> None:
    """ "삼성전기(주)" 를 "삼성전기" 로 맞추는 것은 mapping 규칙의 일이다."""
    conn = make_conn(tmp_path / "jobs.db", WITH_COMPANY)
    try:
        add_rule(conn, "company", "mapping", {"map": {"삼성전기(주)": "삼성전기"}})

        await run_workflow(conn, 1, fetcher=stub_fetcher(), limit=2)

        assert companies(conn) == [("삼성SDS", PARSED), ("삼성전기", PARSED)]
    finally:
        conn.close()


def test_a_rule_that_empties_the_company_clears_the_source() -> None:
    """남은 값이 없는데 출처만 적혀 있으면 읽는 쪽이 헷갈린다."""
    rule = build_rule("company", "regex", {"pattern": ".*", "replacement": ""})

    fields = normalize_fields({"company": "삼성SDS"}, [rule])

    assert fields["company"] is None
    assert fields[COMPANY_SOURCE] is None
