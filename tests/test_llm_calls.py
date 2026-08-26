"""모델 호출 기록 테스트 (1.6.V).

셀렉터 생성만 있을 때는 로그 줄 하나로 충분했다. 본문 분류는 공고마다 하나씩 붙어서, 남기지
않으면 "이번 달에 얼마나 썼나" 에 답할 길이 없다 (`migrations/0013_llm_calls.sql`).

여기서 보는 것은 셋이다 — 호출 하나가 행 하나로 남는가, 실패한 호출도 남는가, 그리고
**기록이 실패해도 호출이 실패로 바뀌지 않는가.**
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import db
from app.llm.gemini import PROVIDER, Usage
from app.llm.log import CLASSIFY, SELECTOR_GENERATE, record_call, totals
from tests.test_api_crawlers import (  # noqa: F401  (fixture 를 그대로 쓴다)
    DETAIL_URL,
    GENERATED,
    LIST_URL,
    USAGE,
    client,
    conn,
    result_for,
    use_generator,
)

USAGE_ONE = Usage(
    model="gemini-3.5-flash",
    input_tokens=4321,
    output_tokens=120,
    total_tokens=4441,
    latency_ms=5100,
)
USAGE_TWO = Usage(
    model="gemini-3.5-flash",
    input_tokens=1000,
    output_tokens=50,
    total_tokens=1050,
    latency_ms=900,
)


@pytest.fixture
def logged(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "calls.db")
    db.migrate_up(connection)
    try:
        yield connection
    finally:
        connection.close()


def test_one_call_is_one_row_with_provider_model_feature_tokens_and_latency(
    logged: sqlite3.Connection,
) -> None:
    record_call(logged, feature=CLASSIFY, usage=USAGE_ONE)

    row = logged.execute("SELECT * FROM llm_calls").fetchone()
    assert row["provider"] == PROVIDER
    assert row["model"] == "gemini-3.5-flash"
    assert row["feature"] == CLASSIFY
    assert row["input_tokens"] == 4321
    assert row["output_tokens"] == 120
    assert row["total_tokens"] == 4441
    assert row["latency_ms"] == 5100
    assert row["ok"] == 1
    assert row["error"] == ""
    assert row["called_at"]


def test_a_failed_call_is_recorded_too(logged: sqlite3.Connection) -> None:
    """실패한 호출도 토큰을 쓴다. 빼고 세면 합이 실제와 어긋난다."""
    record_call(
        logged,
        feature=CLASSIFY,
        usage=USAGE_ONE,
        ok=False,
        error="Gemini 호출 실패(429): 분당 한도 초과",
    )

    row = logged.execute("SELECT ok, error FROM llm_calls").fetchone()
    assert row["ok"] == 0
    assert "429" in row["error"]


def test_the_totals_add_up_to_what_was_recorded(logged: sqlite3.Connection) -> None:
    record_call(logged, feature=CLASSIFY, usage=USAGE_ONE)
    record_call(logged, feature=CLASSIFY, usage=USAGE_TWO)
    record_call(logged, feature=SELECTOR_GENERATE, usage=USAGE_TWO)

    everything = totals(logged)
    assert everything["calls"] == 3
    assert everything["total_tokens"] == 4441 + 1050 + 1050

    only_classify = totals(logged, CLASSIFY)
    assert only_classify["calls"] == 2
    assert only_classify["input_tokens"] == 4321 + 1000
    assert only_classify["output_tokens"] == 120 + 50
    assert only_classify["latency_ms"] == 5100 + 900


def test_a_failure_to_record_does_not_become_a_failure_to_classify(
    tmp_path: pathlib.Path,
) -> None:
    """표가 없어도 분류는 계속 가야 한다. 남기지 못한 것은 숫자 한 줄이다."""
    connection = db.connect(tmp_path / "no-schema.db")
    try:
        assert record_call(connection, feature=CLASSIFY, usage=USAGE_ONE) == 0
    finally:
        connection.close()


def test_registering_a_crawler_records_its_generation_call(
    client: TestClient,  # noqa: F811
    conn: sqlite3.Connection,  # noqa: F811
) -> None:
    """지금까지 비싼 호출이던 쪽도 같은 표에 남는다. 둘을 견줄 수 있어야 한다."""
    use_generator(result_for(GENERATED))

    response = client.post(
        "/api/crawlers",
        json={"name": "파이썬", "list_url": LIST_URL, "detail_url": DETAIL_URL},
    )

    assert response.status_code == 201
    row = conn.execute("SELECT feature, model, total_tokens FROM llm_calls").fetchone()
    assert row["feature"] == SELECTOR_GENERATE
    assert row["model"] == USAGE.model
    assert row["total_tokens"] == USAGE.total_tokens
