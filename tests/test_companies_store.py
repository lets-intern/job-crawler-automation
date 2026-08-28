"""회사 저장소 테스트. 넣은 값이 그대로 나오는지와, 없는 행에 쓰지 않는지를 본다.

이 표를 쓰는 코드는 `app/companies.py` 하나다. 그래서 여기서 확인하는 것이 곧 표에 들어갈
수 있는 값 전부다.
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import pytest

from app import companies, db


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    try:
        yield connection
    finally:
        connection.close()


def test_a_new_row_comes_back_with_what_went_in(conn: sqlite3.Connection) -> None:
    assert companies.ensure(conn, "삼성SDS", "삼성전자") is True

    stored = companies.read(conn, "삼성SDS")

    assert stored is not None
    assert (stored.name, stored.parent_name, stored.logo_url) == ("삼성SDS", "삼성전자", None)


def test_the_second_ensure_makes_nothing_and_changes_nothing(conn: sqlite3.Connection) -> None:
    """정규화가 공고마다 부르는 함수다. 있는 행을 덮으면 운영자가 고친 값이 도로 덮인다."""
    companies.ensure(conn, "삼성SDS", "삼성전자")
    companies.set_parent_name(conn, "삼성SDS", "삼성")

    assert companies.ensure(conn, "삼성SDS", "삼성전자") is False

    stored = companies.read(conn, "삼성SDS")
    assert stored is not None and stored.parent_name == "삼성"
    assert len(companies.list_all(conn)) == 1


def test_a_blank_name_is_refused(conn: sqlite3.Connection) -> None:
    """이름이 신원이다. 빈 이름의 행은 어느 공고와도 이어지지 않는다."""
    with pytest.raises(companies.CompanyNameError):
        companies.ensure(conn, "   ")

    assert companies.list_all(conn) == []


def test_the_logo_url_is_written_and_cleared(conn: sqlite3.Connection) -> None:
    companies.ensure(conn, "토스")

    saved = companies.set_logo_url(conn, "토스", "https://cdn.test/toss.png")
    assert saved.logo_url == "https://cdn.test/toss.png"

    cleared = companies.set_logo_url(conn, "토스", "  ")
    assert cleared.logo_url is None


def test_the_parent_name_is_written_and_cleared(conn: sqlite3.Connection) -> None:
    companies.ensure(conn, "토스")

    saved = companies.set_parent_name(conn, "토스", " 비바리퍼블리카 ")
    assert saved.parent_name == "비바리퍼블리카"

    cleared = companies.set_parent_name(conn, "토스", None)
    assert cleared.parent_name is None


def test_writing_to_a_name_that_has_no_row_says_so(conn: sqlite3.Connection) -> None:
    """행을 만드는 것은 정규화다. 쓰기가 없는 이름을 만들면 오타가 회사로 남는다."""
    with pytest.raises(companies.CompanyNotFoundError):
        companies.set_logo_url(conn, "없는회사", "https://cdn.test/x.png")

    with pytest.raises(companies.CompanyNotFoundError):
        companies.set_parent_name(conn, "없는회사", "그룹")

    assert companies.read(conn, "없는회사") is None


def test_the_list_is_by_name(conn: sqlite3.Connection) -> None:
    for name in ("토스", "삼성SDS", "LG전자"):
        companies.ensure(conn, name)

    assert [company.name for company in companies.list_all(conn)] == ["LG전자", "삼성SDS", "토스"]


def test_a_write_moves_updated_at_and_leaves_created_at(conn: sqlite3.Connection) -> None:
    """언제 만들어졌는지는 로고를 올려도 그대로다. 화면이 "언제부터 로고가 없었나" 를 읽는다."""
    companies.ensure(conn, "토스")
    before = conn.execute(
        "SELECT created_at, updated_at FROM companies WHERE name = '토스'"
    ).fetchone()
    conn.execute("UPDATE companies SET updated_at = '2000-01-01 00:00:00' WHERE name = '토스'")

    companies.set_logo_url(conn, "토스", "https://cdn.test/toss.png")

    after = conn.execute(
        "SELECT created_at, updated_at FROM companies WHERE name = '토스'"
    ).fetchone()
    assert after["created_at"] == before["created_at"]
    assert after["updated_at"] != "2000-01-01 00:00:00"
