"""회사 화면 (6.1.V, 6.2.V, 6.3.V).

보는 것은 넷이다. 네비게이션에 자리가 생겼는지, 그 주소가 열리면서 목록 조각을 부르는지,
행이 없을 때 화면이 "없음" 으로 끝내지 않고 언제 생기는지 말하는지, 그리고 공고 수가
많은 회사가 앞에 서는지.

조회 조건 둘(`로고 없음`, `공고 N건 이상`)을 함께 걸면 등록할 목록이 나온다. 걸린 회사 수와
공고 합계가 실제와 같은지가 그 조건이 쓸모 있는지를 정한다.

공고는 정규화를 지나 넣는다. 화면이 세는 값과 로고가 실제로 붙는 경로가 같은 이름이라야
숫자가 뜻을 갖는다.
"""

from __future__ import annotations

import json
import pathlib
import re
import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import companies, db
from app.api.settings import get_connection
from app.api.ui import NAV
from app.main import app
from app.normalize.engine import insert_normalized


def add_job(conn: sqlite3.Connection, company: str, seq: int, parent: str = "") -> None:
    """공고 한 건을 정규화까지 넣는다. 없던 회사면 행이 함께 생긴다."""
    record = {"title": f"공고 {seq}", "body": "본문", "company": company}
    if parent:
        record["parent_company"] = parent
    cursor = conn.execute(
        """
        INSERT INTO raw_jobs (workflow_id, source_url, raw_data_json, content_hash)
        VALUES (1, ?, ?, ?)
        """,
        (f"https://x/{seq}", json.dumps(record, ensure_ascii=False), f"hash-{seq}"),
    )
    insert_normalized(conn, int(cursor.lastrowid or 0), [])


def names_in_order(body: str) -> list[str]:
    """표에 그려진 회사명을 나온 순서대로. 정렬을 보는 유일한 방법이다."""
    return re.findall(r'<td class="cell-text font-medium text-slate-900">([^<]+)</td>', body)


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    # `raw_jobs.workflow_id` 가 외래키다. 공고를 넣는 테스트가 여기에 매달린다
    connection.execute(
        "INSERT INTO crawlers (id, name, list_url, status)"
        " VALUES (1, '테스트', 'https://x', 'draft')"
    )
    connection.execute("INSERT INTO workflows (id, crawler_id, name) VALUES (1, 1, '테스트')")
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def client(tmp_path: pathlib.Path, conn: sqlite3.Connection) -> Iterator[TestClient]:
    def request_connection() -> Iterator[sqlite3.Connection]:
        connection = db.connect(tmp_path / "jobs.db")
        try:
            yield connection
        finally:
            connection.close()

    app.dependency_overrides[get_connection] = request_connection
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_네비게이션에_회사가_있다() -> None:
    assert ("/companies", "회사") in NAV


def test_회사_화면이_열리고_네비게이션이_켜진다(client: TestClient) -> None:
    response = client.get("/companies")

    assert response.status_code == 200
    assert '<a href="/companies" aria-current="page"' in response.text


def test_회사_화면이_목록_조각을_부른다(client: TestClient) -> None:
    assert 'hx-get="/ui/companies"' in client.get("/companies").text


def test_목록이_저장된_회사를_그린다(client: TestClient, conn: sqlite3.Connection) -> None:
    companies.ensure(conn, "삼성SDS", "삼성전자")
    companies.set_logo_url(conn, "삼성SDS", "https://cdn.test/sds.png")
    conn.commit()

    body = client.get("/ui/companies").text

    assert "삼성SDS" in body
    assert "삼성전자" in body
    assert "https://cdn.test/sds.png" in body


def test_로고가_없으면_빈_칸으로_두지_않는다(client: TestClient, conn: sqlite3.Connection) -> None:
    companies.ensure(conn, "토스")
    conn.commit()

    assert "로고 없음" in client.get("/ui/companies").text


def test_행이_없으면_언제_생기는지_말한다(client: TestClient) -> None:
    body = client.get("/ui/companies").text

    assert "정규화되면 그 회사명으로 행이 생긴다" in body


def test_공고_수가_그_회사의_공고와_같다(client: TestClient, conn: sqlite3.Connection) -> None:
    add_job(conn, "토스", 1)
    add_job(conn, "토스", 2)
    add_job(conn, "당근", 3)
    conn.commit()

    body = client.get("/ui/companies").text

    assert "2건" in body
    assert "1건" in body


def test_공고가_많은_회사가_앞에_선다(client: TestClient, conn: sqlite3.Connection) -> None:
    """이름 순이면 로고 하나가 몇 건에 붙는지를 화면에서 알 수 없다."""
    for seq in range(1, 4):
        add_job(conn, "카카오", seq)
    add_job(conn, "가나다", 10)
    companies.ensure(conn, "공고없는회사")
    conn.commit()

    assert names_in_order(client.get("/ui/companies").text) == [
        "카카오",
        "가나다",
        "공고없는회사",
    ]


def test_공고가_하나도_없는_회사도_0건으로_남는다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """빠지면 로고를 지울 회사를 화면에서 찾을 수 없다."""
    companies.ensure(conn, "폐업한회사")
    conn.commit()

    body = client.get("/ui/companies").text

    assert "폐업한회사" in body
    assert "0건" in body


def test_로고_없음_조건이_로고를_넣은_회사를_뺀다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    add_job(conn, "토스", 1)
    add_job(conn, "당근", 2)
    companies.set_logo_url(conn, "토스", "https://cdn.test/toss.png")
    conn.commit()

    body = client.get("/ui/companies", params={"no_logo": "on"}).text

    assert names_in_order(body) == ["당근"]


def test_공고_N건_이상_조건이_적은_회사를_뺀다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    for seq in range(1, 4):
        add_job(conn, "카카오", seq)
    add_job(conn, "당근", 10)
    conn.commit()

    body = client.get("/ui/companies", params={"min_jobs": "3"}).text

    assert names_in_order(body) == ["카카오"]


def test_둘을_걸면_등록할_목록만_남는다(client: TestClient, conn: sqlite3.Connection) -> None:
    """로고가 없으면서 공고가 여러 개인 회사. 이것이 먼저 등록할 목록이다."""
    for seq in range(1, 4):
        add_job(conn, "로고없는큰회사", seq)
    for seq in range(4, 7):
        add_job(conn, "로고있는큰회사", seq)
    add_job(conn, "로고없는작은회사", 7)
    companies.set_logo_url(conn, "로고있는큰회사", "https://cdn.test/x.png")
    conn.commit()

    body = client.get("/ui/companies", params={"no_logo": "on", "min_jobs": "2"}).text

    assert names_in_order(body) == ["로고없는큰회사"]


def test_걸린_회사_수와_공고_합계를_적는다(client: TestClient, conn: sqlite3.Connection) -> None:
    """숫자가 실제와 다르면 무엇을 먼저 등록할지를 이 화면으로 정할 수 없다."""
    for seq in range(1, 4):
        add_job(conn, "카카오", seq)
    for seq in range(4, 6):
        add_job(conn, "당근", seq)
    add_job(conn, "작은회사", 6)
    conn.commit()

    body = client.get("/ui/companies", params={"min_jobs": "2"}).text

    assert "조건에 걸린 회사" in body
    assert "2곳, 공고 합계 5건" in body


def test_조건에_걸린_회사가_없으면_조건_탓임을_말한다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    add_job(conn, "토스", 1)
    conn.commit()

    body = client.get("/ui/companies", params={"min_jobs": "9"}).text

    assert "이 조건에 걸린 회사가 없다" in body


def test_숫자_칸을_비워도_조건_없음으로_읽는다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """정수로 받으면 빈 값이 422 가 되어 조건을 지우려던 조작이 오류로 돌아온다."""
    add_job(conn, "토스", 1)
    conn.commit()

    response = client.get("/ui/companies", params={"min_jobs": ""})

    assert response.status_code == 200
    assert names_in_order(response.text) == ["토스"]


def test_화면에_조회_조건_둘이_있다(client: TestClient) -> None:
    body = client.get("/companies").text

    assert 'name="no_logo"' in body
    assert 'name="min_jobs"' in body
