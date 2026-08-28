"""분류가 무엇을 읽는지 본다 (9.1.V).

Push 8 이 상세 원문을 `raw_jobs.raw_data_json.source_text` 에 넣었다. 분류는 그것을 읽고,
없으면 본문으로 떨어진다. **폴백이 검사의 요점이다** — 원문은 2026-08-28 이후 수집분에만
있고, 그 전에 쌓인 건에는 키가 아예 없다. 폴백이 없으면 그 공고들이 분류에서 통째로 사라진다
(`.claude/tasks/todo/prd-side-workflows.md` 4절).

제공자를 실제로 부르지 않는다. 어느 값이 갔는지는 가짜 클라이언트가 받은 프롬프트로 본다.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
from collections.abc import Iterator

import pytest

from app import db
from app.classify.batch import ClassifyProgress, classify_ids
from app.classify.schema import RESPONSE_FIELDS
from app.classify.store import read_source
from app.config import Settings
from tests.test_selector_generator import FakeClient

# 본문. 두 건이 같은 본문을 갖는다
BODY = "◆ 업무내용\n제휴사 데이터 연동 구조 기획\n\n◆ 지원자격\n관련 경험 5년 이상이신 분\n"

# 원문에만 있는 줄. 본문 셀렉터 바깥의 이름표 값이고, 실제로 SK·롯데그룹·네이버·카카오·
# 우아한형제들의 조상 1단계가 담은 것이 이것이다 (`.claude/site-recipes/source-text-container.md`)
ONLY_IN_SOURCE = "근무지 성남시 분당구 판교로 235"

SOURCE = f"{ONLY_IN_SOURCE}\n{BODY}"


def settings_with_key() -> Settings:
    return Settings(gemini_api_key="테스트키", gemini_model="gemini-3.5-flash")


def response(**fields: str) -> str:
    return json.dumps({name: fields.get(name, "") for name in RESPONSE_FIELDS})


ANSWER = response(duties="제휴사 데이터 연동 구조 기획")


def insert(conn: sqlite3.Connection, raw_job_id: int, **raw: str) -> None:
    conn.execute(
        """
        INSERT INTO raw_jobs (id, workflow_id, source_url, raw_data_json, content_hash)
        VALUES (?, 1, ?, ?, ?)
        """,
        (
            raw_job_id,
            f"https://example.test/{raw_job_id}",
            json.dumps(raw, ensure_ascii=False),
            f"hash{raw_job_id}",
        ),
    )


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    """원문이 있는 건 하나와, 원문 키가 아예 없는 옛 건 하나."""
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    connection.execute(
        """
        INSERT INTO crawlers (id, name, list_url, status)
        VALUES (1, '테스트', 'https://example.test', 'promoted')
        """
    )
    connection.execute("INSERT INTO workflows (id, crawler_id, name) VALUES (1, 1, '테스트')")
    insert(connection, 1, title="공고 1", body=BODY, source_text=SOURCE)
    insert(connection, 2, title="공고 2", body=BODY)
    try:
        yield connection
    finally:
        connection.close()


def test_원문이_있으면_원문을_읽는다(conn: sqlite3.Connection) -> None:
    assert read_source(conn, 1) == SOURCE


def test_원문이_없으면_본문으로_떨어진다(conn: sqlite3.Connection) -> None:
    """옛 건에는 `source_text` 키가 아예 없다. 여기서 빈 값이 나오면 그 공고는 분류를 못 받는다."""
    assert read_source(conn, 2) == BODY


def test_원문이_빈_문자열이어도_본문으로_떨어진다(conn: sqlite3.Connection) -> None:
    """키는 있는데 값이 빈 경우다. 수집이 원문을 못 뽑으면 이 모양이 될 수 있다."""
    insert(conn, 3, title="공고 3", body=BODY, source_text="")

    assert read_source(conn, 3) == BODY


async def test_실행이_보내는_값도_원문과_본문으로_갈린다(conn: sqlite3.Connection) -> None:
    """읽기만 바꾸고 실행이 옛 함수를 계속 부르면 아무것도 달라지지 않는다."""
    client = FakeClient(ANSWER)

    await classify_ids(
        conn, [1, 2], ClassifyProgress(), client=client, settings=settings_with_key()
    )

    첫_건, 둘째_건 = client.calls[0]["contents"], client.calls[1]["contents"]
    assert ONLY_IN_SOURCE in 첫_건
    assert ONLY_IN_SOURCE not in 둘째_건
    assert "제휴사 데이터 연동 구조 기획" in 둘째_건
