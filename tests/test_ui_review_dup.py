"""데이터 검수 화면의 중복 조건 (dup-filter 1.1).

실사이트에 나가지 않는다. 저장된 행을 넣고 조건 함수와 화면 경로로만 확인한다.

픽스처는 운영 DB 640건을 손으로 센 결과와 같은 모양이다. 제목만 같은 것이 7묶음 22건
(여분 15), 제목과 회사가 함께 같은 것이 1묶음 5건(여분 4)이다. 계열사가 나눠 올린
`R&D분야 외국인 경력사원 채용` 7건은 회사가 전부 달라 제목 기준에만 걸린다 — 그것이 이
조건을 좁게도 넓게도 고를 수 있어야 하는 이유다.

| 확인 | 깨지면 |
|---|---|
| 기준마다 묶음 수와 여분 수가 손으로 센 값과 같다 | 화면에 적힌 중복 건수가 거짓이 된다 |
| 여분이 아니라 묶음 전체가 걸린다 | 짝이 안 보여 어느 쪽을 지울지 정할 수 없다 |
| 다른 조건과 AND 로 겹친다 | `SK 안에서만 중복 찾기` 가 전체 중복을 보여준다 |
| 중복은 좁힌 조건 안에서 다시 센다 | 좁힌 뒤 짝을 잃은 한 건이 중복으로 남는다 |
| 빈 값끼리는 묶이지 않는다 | 셀렉터가 놓친 40건이 `중복 40건` 으로 읽힌다 |
| 같은 묶음이 붙어 나온다 | 페이지를 넘기면 짝이 다른 페이지로 갈라진다 |
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import pytest

from app import db
from app.api.review_filter import (
    DUP_SOURCE_URL,
    DUP_TITLE,
    DUP_TITLE_COMPANY,
    JobFilter,
    count,
    dup_columns,
    dup_groups,
    filter_sql,
    order_clause,
)

LIST_URL = "https://www.python.org/jobs/"

# 제목이 같고 회사가 다른 7건. 삼성 계열사가 각각 올린 공고다 — 진짜 중복이 아닐 수 있어서
# 자동으로 지우지 않고 보여주기만 한다
SAMSUNG = "R&D분야 외국인 경력사원 채용"
SAMSUNG_COMPANIES = (
    "삼성중공업",
    "삼성바이오에피스",
    "삼성바이오로직스",
    "삼성SDS",
    "삼성전기",
    "삼성SDI",
    "삼성디스플레이",
)

# 제목도 회사도 같은 5건. 제목+회사 기준에 걸리는 유일한 묶음이다
POOL = "상시 인재 Pool 등록"
POOL_COMPANY = "D&O"

# 제목만 같은 두 건짜리 다섯 묶음. 회사는 서로 다르다
PAIRS = (
    "Business Operations Manager",
    "IT Manager",
    "기술연구분야 외국인 경력사원 채용",
    "설계/시공분야 외국인 계약직 채용",
    "해외영업분야 외국인 경력사원 채용",
)

# 어느 기준에도 걸리지 않는 행. 조건이 이것들까지 끌고 오면 묶음 수가 맞아도 건수가 틀린다
SINGLES = (
    ("에스케이하이닉스", "백엔드 개발자"),
    ("에스케이텔레콤", "데이터 엔지니어"),
    ("엘지전자", "iOS 개발자"),
)


def _rows() -> list[tuple[int, str, str]]:
    """(raw_job_id, company, title) 한 벌. 워크플로우는 회사 첫 글자로 갈린다."""
    found: list[tuple[int, str, str]] = []
    for company in SAMSUNG_COMPANIES:
        found.append((len(found) + 1, company, SAMSUNG))
    for _ in range(5):
        found.append((len(found) + 1, POOL_COMPANY, POOL))
    for title in PAIRS:
        found.append((len(found) + 1, f"한화{title[:2]}", title))
        found.append((len(found) + 1, f"한화솔루션{title[:2]}", title))
    for company, title in SINGLES:
        found.append((len(found) + 1, company, title))
    # 제목이 비어 있는 두 건. 셀렉터가 놓친 것이지 중복이 아니다
    found.append((len(found) + 1, "에스케이온", ""))
    found.append((len(found) + 1, "에스케이스퀘어", "   "))
    return found


ROWS = _rows()


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    connection.execute(
        "INSERT INTO crawlers (name, list_url, status) VALUES ('samsung', ?, 'promoted')",
        (LIST_URL,),
    )
    connection.execute(
        "INSERT INTO crawlers (name, list_url, status) VALUES ('sk', ?, 'promoted')",
        ("https://example.com/jobs/",),
    )
    connection.execute("INSERT INTO workflows (crawler_id, name) VALUES (1, '대기업')")
    connection.execute("INSERT INTO workflows (crawler_id, name) VALUES (2, 'SK')")
    for raw_job_id, company, title in ROWS:
        workflow_id = 2 if company.startswith("에스케이") else 1
        connection.execute(
            """
            INSERT INTO raw_jobs (id, workflow_id, source_url, raw_data_json, content_hash,
                                  crawled_at)
            VALUES (?, ?, ?, '{}', ?, '2026-08-20 01:00:00')
            """,
            (raw_job_id, workflow_id, f"{LIST_URL}{raw_job_id}/", f"hash-{raw_job_id}"),
        )
        connection.execute(
            """
            INSERT INTO normalized_jobs (raw_job_id, company, title, source_url, normalized_at)
            VALUES (?, ?, ?, ?, '2026-08-20 02:00:00')
            """,
            (raw_job_id, company, title, f"{LIST_URL}{raw_job_id}/"),
        )
    try:
        yield connection
    finally:
        connection.close()


def measured(conn: sqlite3.Connection, picked: JobFilter) -> tuple[int, int, int]:
    """(묶음 수, 걸린 건수, 여분). 화면 머리글에 적히는 세 숫자와 같은 계산이다."""
    groups = dup_groups(conn, picked)
    total = count(conn, picked)
    return len(groups), total, total - len(groups)


def test_기준마다_묶음_수가_손으로_센_값과_같다(conn: sqlite3.Connection) -> None:
    """운영 DB 640건에서 센 값과 같은 모양이다."""
    assert measured(conn, JobFilter(dup=DUP_TITLE_COMPANY)) == (1, 5, 4)
    assert measured(conn, JobFilter(dup=DUP_TITLE)) == (7, 22, 15)
    # 원본 주소가 겹치는 것은 중복 판정이 고장 났을 때만 나온다. 지금은 0이다
    assert measured(conn, JobFilter(dup=DUP_SOURCE_URL)) == (0, 0, 0)


def test_조건을_고르지_않으면_전부_나온다(conn: sqlite3.Connection) -> None:
    assert count(conn, JobFilter()) == len(ROWS)
    assert dup_groups(conn, JobFilter()) == []


def test_여분이_아니라_묶음_전체가_걸린다(conn: sqlite3.Connection) -> None:
    """일곱 건짜리 묶음에서 여섯 건만 보이면 어느 쪽을 지울지 정할 수 없다."""
    groups = dup_groups(conn, JobFilter(dup=DUP_TITLE))
    assert [group["count"] for group in groups] == [7, 5, 2, 2, 2, 2, 2]
    assert groups[0]["parts"] == [("제목", SAMSUNG)]
    assert groups[0]["number"] == 1


def test_제목이_같아도_회사가_다르면_좁은_기준에는_안_걸린다(conn: sqlite3.Connection) -> None:
    """계열사가 각각 올린 공고다. 좁은 기준을 따로 두는 이유가 이것이다."""
    groups = dup_groups(conn, JobFilter(dup=DUP_TITLE_COMPANY))
    assert [group["parts"] for group in groups] == [[("제목", POOL), ("회사", POOL_COMPANY)]]


def test_다른_조건과_함께_걸면_그_안에서만_센다(conn: sqlite3.Connection) -> None:
    """`SK 안에서만 중복 찾기` 다. SK 워크플로우에는 짝이 없다."""
    assert measured(conn, JobFilter(dup=DUP_TITLE, workflow_id=2)) == (0, 0, 0)
    assert measured(conn, JobFilter(dup=DUP_TITLE, workflow_id=1)) == (7, 22, 15)
    assert measured(conn, JobFilter(dup=DUP_TITLE, company=POOL_COMPANY)) == (1, 5, 4)


def test_좁힌_뒤에_짝을_잃은_한_건은_중복이_아니다(conn: sqlite3.Connection) -> None:
    """전체에서 센 묶음을 나중에 거르면 이 한 건이 `중복` 으로 남는다."""
    picked = JobFilter(dup=DUP_TITLE, company="삼성SDI")
    assert measured(conn, picked) == (0, 0, 0)


def test_빈_값끼리는_묶지_않는다(conn: sqlite3.Connection) -> None:
    """제목이 비었거나 공백뿐인 두 건은 셀렉터가 놓친 것이지 중복이 아니다."""
    titles = {
        value for group in dup_groups(conn, JobFilter(dup=DUP_TITLE)) for _, value in group["parts"]
    }
    assert "" not in titles
    assert count(conn, JobFilter(dup=DUP_TITLE)) == 22


def test_같은_묶음이_붙어_나오고_큰_묶음이_먼저다(conn: sqlite3.Connection) -> None:
    """짝이 흩어지면 페이지를 넘길 때 갈라진다. 묶음이 정렬의 앞자리다."""
    picked = JobFilter(dup=DUP_TITLE)
    where, params = filter_sql(picked)
    rows = conn.execute(
        f"SELECT n.title AS title{dup_columns(picked.dup)}"
        f"  FROM normalized_jobs n JOIN raw_jobs r ON r.id = n.raw_job_id{where}"
        f"{order_clause('review', 'desc', picked.dup)}",
        params,
    ).fetchall()
    sizes = [int(row["dup_size"]) for row in rows]
    assert sizes[:12] == [7] * 7 + [5] * 5
    # 같은 제목이 한 자리에 모여 있다
    titles = [str(row["title"]) for row in rows]
    assert titles[:7] == [SAMSUNG] * 7
    assert len(set(titles)) == 7


def test_표에_없는_기준은_조건을_걸지_않는다(conn: sqlite3.Connection) -> None:
    """화면에서 온 문자열이 SQL 로 새지 않는다. 표가 갱신되지 않는 것이 제일 나쁜 실패다."""
    assert JobFilter(dup="'; DROP TABLE raw_jobs; --").dup == "'; DROP TABLE raw_jobs; --"
    where, params = filter_sql(JobFilter(dup="'; DROP TABLE raw_jobs; --"))
    assert where == ""
    assert params == []


def test_보정으로_고친_제목이_중복_판정에_쓰인다(conn: sqlite3.Connection) -> None:
    """화면에 보이는 값이 판정 기준이다. 규칙값만 보면 사람이 고친 뒤에도 안 걸린다."""
    before = measured(conn, JobFilter(dup=DUP_TITLE_COMPANY))
    assert before == (1, 5, 4)
    # 삼성SDI 한 건의 회사를 삼성전기로 고치면 그 둘이 제목+회사로 같아진다
    sdi = conn.execute(
        "SELECT raw_job_id FROM normalized_jobs WHERE company = '삼성SDI'"
    ).fetchone()
    conn.execute(
        "INSERT INTO job_field_overrides (raw_job_id, field_name, value) VALUES (?, 'company', ?)",
        (int(sdi["raw_job_id"]), "삼성전기"),
    )
    assert measured(conn, JobFilter(dup=DUP_TITLE_COMPANY)) == (2, 7, 5)
