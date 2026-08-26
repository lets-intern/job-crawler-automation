"""분류 실행 테스트 (1.5.V).

Gemini 를 실제로 부르지 않는다. 여기서 보는 것은 넷이다 — 이미 분류된 공고를 다시 돌지
않는가, 한 건이 실패해도 나머지가 가는가, **분류 실패가 수집을 실패로 만들지 않는가**,
그리고 한 번에 도는 건수에 상한이 걸리는가.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
from collections.abc import Iterator

import pytest

from app import db
from app.classify.batch import (
    MAX_LIMIT,
    ClassifyProgress,
    bounded,
    classify_ids,
    classify_pending,
    remaining,
)
from app.classify.schema import CLASSIFY_FIELDS
from app.classify.store import pending_ids, read_classification
from app.config import Settings
from tests.test_selector_generator import FakeClient

BODY = (
    "◆ 직원 유형\n정규직\n\n◆ 업무내용\n제휴사 데이터 연동 구조 기획\n\n"
    "◆ 지원자격\n관련 경험 5년 이상이신 분\n"
)


def settings_with_key() -> Settings:
    return Settings(gemini_api_key="테스트키", gemini_model="gemini-3.5-flash")


def response(**fields: str) -> str:
    return json.dumps({name: fields.get(name, "") for name in CLASSIFY_FIELDS})


GOOD = response(
    employment_type="정규직",
    duties="제휴사 데이터 연동 구조 기획",
    requirements="관련 경험 5년 이상이신 분",
)


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    _seed(connection)
    try:
        yield connection
    finally:
        connection.close()


def _seed(conn: sqlite3.Connection, count: int = 3) -> None:
    """크롤러 하나, 워크플로우 하나, 본문이 있는 공고 몇 건."""
    conn.execute(
        """
        INSERT INTO crawlers (id, name, list_url, status)
        VALUES (1, '테스트', 'https://x', 'promoted')
        """
    )
    conn.execute("INSERT INTO workflows (id, crawler_id, name) VALUES (1, 1, '테스트')")
    for index in range(1, count + 1):
        raw = {
            "source_url": f"https://x/{index}",
            "title": f"공고 {index}",
            "body": BODY,
            "requirements": "",
            "deadline": "",
            "department": "",
            "company": "테스트회사",
        }
        conn.execute(
            """
            INSERT INTO raw_jobs (workflow_id, source_url, raw_data_json, content_hash)
            VALUES (1, ?, ?, ?)
            """,
            (raw["source_url"], json.dumps(raw, ensure_ascii=False), f"hash{index}"),
        )


async def run(conn: sqlite3.Connection, *texts: str, limit: int = 10) -> ClassifyProgress:
    progress = ClassifyProgress()
    await classify_pending(
        conn,
        progress,
        limit=limit,
        client=FakeClient(*texts),
        settings=settings_with_key(),
    )
    return progress


async def test_it_classifies_the_postings_that_have_a_body(conn: sqlite3.Connection) -> None:
    progress = await run(conn, GOOD)

    assert progress.total == 3
    assert progress.processed == 3
    assert progress.failed == 0
    stored = read_classification(conn, 1)
    assert stored["employment_type"] == "정규직"
    assert stored["duties"] == "제휴사 데이터 연동 구조 기획"


async def test_an_already_classified_posting_is_not_run_again(conn: sqlite3.Connection) -> None:
    """640건짜리 표에서 이것이 새면 같은 공고에 계속 돈을 쓴다."""
    await run(conn, GOOD)

    assert pending_ids(conn) == []
    assert remaining(conn) == 0

    second = await run(conn, GOOD)
    assert second.total == 0
    assert second.calls == 0


async def test_a_posting_with_no_body_is_never_picked_up(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT INTO raw_jobs (workflow_id, source_url, raw_data_json, content_hash)
        VALUES (1, 'https://x/9', ?, 'hash9')
        """,
        (json.dumps({"source_url": "https://x/9", "title": "본문 없음", "body": ""}),),
    )

    assert 4 not in pending_ids(conn)


async def test_a_failure_stops_at_that_posting(conn: sqlite3.Connection) -> None:
    """한 건이 실패해도 나머지는 간다. 실패한 건은 다음 실행이 다시 집어 든다."""
    progress = await run(conn, "깨진 응답", "여전히 깨진", GOOD)

    assert progress.failed == 1
    assert progress.processed == 2
    # 실패한 공고는 행이 없어서 다음 실행이 다시 본다
    assert pending_ids(conn) == [1]
    assert "raw_jobs 1" in progress.errors[0]


async def test_a_failed_classification_leaves_the_collected_body_alone(
    conn: sqlite3.Connection,
) -> None:
    """분류가 실패해도 수집은 그대로다. 본문이 있으니 나중에 다시 돌린다."""
    before = conn.execute("SELECT raw_data_json FROM raw_jobs ORDER BY id").fetchall()

    await run(conn, "깨진 응답", "여전히 깨진", GOOD)

    after = conn.execute("SELECT raw_data_json FROM raw_jobs ORDER BY id").fetchall()
    assert [row["raw_data_json"] for row in after] == [row["raw_data_json"] for row in before]
    # 크롤링 실행 기록에도 아무것도 쓰지 않는다
    assert conn.execute("SELECT count(*) AS n FROM crawl_runs").fetchone()["n"] == 0


async def test_the_classified_columns_reach_normalized_jobs(conn: sqlite3.Connection) -> None:
    await run(conn, GOOD)

    row = conn.execute(
        """
        SELECT employment_type, duties, requirements, body
          FROM normalized_jobs WHERE raw_job_id = 1
        """
    ).fetchone()
    assert row["employment_type"] == "정규직"
    assert row["requirements"] == "관련 경험 5년 이상이신 분"
    # 수집이 준 본문은 그대로다
    assert row["body"] == BODY


async def test_what_the_site_gave_wins_over_what_the_body_says(conn: sqlite3.Connection) -> None:
    """분류는 빈 칸을 채우는 쪽이지 덮는 쪽이 아니다."""
    conn.execute(
        "UPDATE raw_jobs SET raw_data_json = ? WHERE id = 1",
        (
            json.dumps(
                {
                    "source_url": "https://x/1",
                    "title": "공고 1",
                    "body": BODY,
                    "employment_type": "사이트가 준 값",
                },
                ensure_ascii=False,
            ),
        ),
    )

    await run(conn, GOOD)

    row = conn.execute(
        "SELECT employment_type FROM normalized_jobs WHERE raw_job_id = 1"
    ).fetchone()
    assert row["employment_type"] == "사이트가 준 값"


async def test_every_call_is_recorded_with_its_tokens(conn: sqlite3.Connection) -> None:
    """1.6.V — 토큰 합이 실제 호출과 맞는지. 다시 물은 호출도 한 행이다."""
    progress = await run(conn, "깨진 응답", GOOD)

    rows = conn.execute("SELECT feature, total_tokens, ok FROM llm_calls ORDER BY id").fetchall()
    # 공고 3건 중 첫 건은 두 번 불렀다
    assert len(rows) == 4
    assert {row["feature"] for row in rows} == {"classify"}
    assert progress.calls == 4
    assert progress.total_tokens == sum(row["total_tokens"] for row in rows)


async def test_a_call_that_never_answered_is_recorded_as_failed(
    conn: sqlite3.Connection,
) -> None:
    progress = await run(conn, "깨진 응답", "여전히 깨진", GOOD)

    failed = conn.execute("SELECT ok, error FROM llm_calls WHERE ok = 0").fetchall()
    assert len(failed) == 1
    assert "unparsable" in failed[0]["error"]
    assert progress.failed == 1


async def test_an_invented_value_is_counted_and_left_out(conn: sqlite3.Connection) -> None:
    progress = await run(conn, response(work_location="서울 강남구 테헤란로 123"))

    assert progress.dropped == 3
    assert read_classification(conn, 1)["work_location"] == ""


async def test_the_batch_size_is_capped(conn: sqlite3.Connection) -> None:
    """640건을 한 번에 돌리면 멈출 수가 없다."""
    assert bounded(10_000) == MAX_LIMIT
    assert bounded(0) == 1
    assert bounded(20) == 20

    progress = await run(conn, GOOD, limit=2)
    assert progress.total == 2
    assert remaining(conn) == 1


async def test_a_missing_api_key_fails_the_run_without_touching_anything(
    conn: sqlite3.Connection,
) -> None:
    progress = ClassifyProgress()
    await classify_pending(conn, progress, settings=Settings(gemini_api_key=""))

    assert progress.failed == 1
    assert "GEMINI_API_KEY" in progress.errors[0]
    assert conn.execute("SELECT count(*) AS n FROM job_classifications").fetchone()["n"] == 0


async def test_only_the_ids_it_was_given_are_classified(conn: sqlite3.Connection) -> None:
    """표본 실행이 쓰는 자리. 사이트를 골고루 섞어 고른 목록을 그대로 돈다."""
    progress = ClassifyProgress()
    await classify_ids(
        conn,
        [2],
        progress,
        client=FakeClient(GOOD),
        settings=settings_with_key(),
    )

    assert progress.processed == 1
    assert read_classification(conn, 1) == {}
    assert read_classification(conn, 2)["employment_type"] == "정규직"


def test_the_classification_survives_a_renormalization(conn: sqlite3.Connection) -> None:
    """분류 결과를 normalized_jobs 에만 썼다면 재정규화 한 번에 사라진다."""
    from app.classify.store import save_classification
    from app.normalize.backfill import BackfillProgress, renormalize

    save_classification(conn, 1, {"employment_type": "정규직"}, model="gemini-3.5-flash")

    renormalize(conn, BackfillProgress())

    row = conn.execute(
        "SELECT employment_type FROM normalized_jobs WHERE raw_job_id = 1"
    ).fetchone()
    assert row["employment_type"] == "정규직"


def test_a_human_correction_still_wins_over_the_classification(
    conn: sqlite3.Connection,
) -> None:
    """규칙 -> 분류 -> 사람 보정. 사람이 고친 값이 재분류 뒤에도 살아남는다 (1.7 이 쓴다)."""
    from app.classify.store import save_classification
    from app.normalize.backfill import BackfillProgress, renormalize

    save_classification(conn, 1, {"work_location": "판교"}, model="gemini-3.5-flash")
    conn.execute(
        "INSERT INTO job_field_overrides (raw_job_id, field_name, value) VALUES (1, ?, ?)",
        ("work_location", "사람이 고친 근무지"),
    )

    renormalize(conn, BackfillProgress())

    row = conn.execute("SELECT work_location FROM normalized_jobs WHERE raw_job_id = 1").fetchone()
    assert row["work_location"] == "사람이 고친 근무지"
