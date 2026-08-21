"""제공 API 테스트. 계약은 `.claude/docs/api-contract.md` 다.

실사이트에 나가지 않는다. `normalized_jobs` 에 시드를 직접 넣고 응답만 본다.

핵심 단언은 하나다. 커서를 따라 끝까지 받은 id 집합이 시드 전체와 정확히 같아야 한다.
누락은 소비 측이 영영 못 받는 공고고, 중복은 같은 공고가 두 번 올라가는 것이다.

시드의 `normalized_at` 은 일부러 겹치게 넣는다. 실제 저장 형식이 초 단위라 한 번의 실행에서
적재된 행 수십 개가 같은 값을 갖는다. 그 상태에서 페이지 경계가 걸리는 것이 정상 상황이고,
`(normalized_at, id)` 쌍이 아니면 그때 행이 잘리거나 겹친다.
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import jobs as jobs_api
from app.main import app

# 같은 초에 적재된 것처럼 보이게 하는 값. 페이지 경계가 이 안쪽에 걸린다
BULK_AT = "2026-08-21 10:00:00"


def seed(conn: sqlite3.Connection, count: int, normalized_at: str | None = None) -> list[int]:
    """`normalized_jobs` 에 `count` 건을 넣고 id 목록을 돌려준다."""
    ids: list[int] = []
    for index in range(count):
        raw = conn.execute(
            """
            INSERT INTO raw_jobs (workflow_id, source_url, raw_data_json, content_hash)
            VALUES (1, ?, '{}', ?)
            """,
            (f"https://example.test/jobs/{index}", f"hash-{index}"),
        )
        raw_id = int(raw.lastrowid or 0)
        # 같은 초에 적재된 행이 뭉치도록 값을 직접 넣는다
        stamp = normalized_at if normalized_at is not None else BULK_AT
        cursor = conn.execute(
            """
            INSERT INTO normalized_jobs
                   (raw_job_id, company, title, department, deadline, body, requirements,
                    source_url, normalized_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                raw_id,
                f"회사{index}",
                f"공고 {index}",
                "개발",
                "2026-09-30",
                "본문",
                "자격요건",
                f"https://example.test/jobs/{index}",
                stamp,
            ),
        )
        ids.append(int(cursor.lastrowid or 0))
    return ids


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    connection.execute(
        "INSERT INTO crawlers (name, list_url, status)"
        " VALUES ('시드', 'https://example.test/', 'promoted')"
    )
    connection.execute("INSERT INTO workflows (crawler_id, name) VALUES (1, '시드')")
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

    app.dependency_overrides[jobs_api.get_connection] = request_connection
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def collect(client: TestClient, params: dict[str, Any] | None = None) -> list[int]:
    """`has_more` 가 꺼질 때까지 커서를 따라가며 받은 id 를 순서대로 모은다."""
    query: dict[str, Any] = dict(params or {})
    seen: list[int] = []
    for _ in range(50):  # 커서가 제자리를 돌면 여기서 멈춘다
        response = client.get("/api/jobs", params=query)
        assert response.status_code == 200
        payload = response.json()
        seen.extend(item["id"] for item in payload["items"])
        if not payload["has_more"]:
            return seen
        query["cursor"] = payload["next_cursor"]
    raise AssertionError("페이지를 50번 넘겨도 끝나지 않았다")


def test_two_pages_cover_every_row_exactly_once(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """limit 보다 많은 시드를 두 페이지로 이어 받으면 id 집합이 전체와 같아야 한다."""
    total = jobs_api.DEFAULT_LIMIT + 50
    expected = seed(conn, total)

    first = client.get("/api/jobs").json()
    assert len(first["items"]) == jobs_api.DEFAULT_LIMIT
    assert first["has_more"] is True

    second = client.get("/api/jobs", params={"cursor": first["next_cursor"]}).json()
    assert len(second["items"]) == 50
    assert second["has_more"] is False

    received = [item["id"] for item in first["items"]] + [item["id"] for item in second["items"]]
    assert len(received) == total
    assert len(set(received)) == total  # 중복 없음
    assert set(received) == set(expected)  # 누락 없음
    assert received == sorted(expected)


def test_cursor_walk_matches_full_set(client: TestClient, conn: sqlite3.Connection) -> None:
    """여러 페이지를 끝까지 따라가도 같다. 마지막 페이지에서 has_more 가 꺼진다."""
    expected = seed(conn, jobs_api.DEFAULT_LIMIT * 2 + 7)
    assert collect(client) == sorted(expected)


def test_row_inserted_between_polls_is_not_skipped(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """폴링 사이에 행이 들어와도 앞 페이지가 밀리지 않는다. 오프셋 기반이면 여기서 건너뛴다."""
    first_batch = seed(conn, jobs_api.DEFAULT_LIMIT + 10)

    first = client.get("/api/jobs").json()
    assert first["has_more"] is True
    # 첫 페이지보다 앞선 시각으로 한 건 삽입. 오프셋이면 두 번째 페이지가 한 건 건너뛴다
    inserted = seed(conn, 1, normalized_at="2026-08-21 09:00:00")

    rest = collect(client, {"cursor": first["next_cursor"]})
    received = [item["id"] for item in first["items"]] + rest
    # 앞에 끼어든 행은 커서보다 뒤라 이번 회차에서는 오지 않는다. 중요한 것은 나머지가 온전한 것
    assert set(received) == set(first_batch)
    assert len(received) == len(set(received))
    assert inserted[0] not in received


def test_empty_table_returns_empty_page(client: TestClient) -> None:
    payload = client.get("/api/jobs").json()
    assert payload == {"items": [], "next_cursor": None, "has_more": False}


def test_item_shape_matches_contract(client: TestClient, conn: sqlite3.Connection) -> None:
    """계약이 정한 필드만, 정한 이름으로 나간다. delivered_at 은 응답에 없다."""
    seed(conn, 1)
    item = client.get("/api/jobs").json()["items"][0]
    assert set(item) == {
        "id",
        "company",
        "title",
        "department",
        "deadline",
        "body",
        "requirements",
        "source_url",
        "normalized_at",
    }
    assert item["normalized_at"] == "2026-08-21T10:00:00Z"


def test_broken_cursor_is_rejected(client: TestClient, conn: sqlite3.Connection) -> None:
    """망가진 커서를 처음부터로 돌리면 소비 측이 같은 데이터를 다시 받는다."""
    seed(conn, 3)
    assert client.get("/api/jobs", params={"cursor": "!!not-base64!!"}).status_code == 400


# --- 8.2 updated_after 와 limit ---


def test_limit_slices_pages_and_cursor_covers_all(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """limit 을 줄여도 커서로 이어 받으면 누락·중복이 없다."""
    expected = seed(conn, 7)

    first = client.get("/api/jobs", params={"limit": 3}).json()
    assert [item["id"] for item in first["items"]] == sorted(expected)[:3]
    assert first["has_more"] is True

    second = client.get("/api/jobs", params={"limit": 3, "cursor": first["next_cursor"]}).json()
    assert [item["id"] for item in second["items"]] == sorted(expected)[3:6]
    assert second["has_more"] is True

    walked = collect(client, {"limit": 3})
    assert walked == sorted(expected)
    assert len(set(walked)) == len(expected)


def test_limit_over_cap_is_clipped_to_500(client: TestClient, conn: sqlite3.Connection) -> None:
    """limit=1000 은 500 으로 잘린다. 거절이 아니라 절삭이고, 나머지는 커서로 이어 받는다."""
    seed(conn, jobs_api.MAX_LIMIT + 20)

    payload = client.get("/api/jobs", params={"limit": 1000}).json()
    assert len(payload["items"]) == jobs_api.MAX_LIMIT
    assert payload["has_more"] is True

    rest = client.get("/api/jobs", params={"limit": 1000, "cursor": payload["next_cursor"]}).json()
    assert len(rest["items"]) == 20
    assert rest["has_more"] is False


def test_default_limit_is_100(client: TestClient, conn: sqlite3.Connection) -> None:
    seed(conn, 120)
    payload = client.get("/api/jobs").json()
    assert len(payload["items"]) == jobs_api.DEFAULT_LIMIT


def test_updated_after_boundary_excludes_the_instant_itself(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """경계값 앞뒤. 경계 시각과 같은 건은 오지 않고, 그 뒤만 온다."""
    before = seed(conn, 2, normalized_at="2026-08-21 09:59:59")
    at = seed(conn, 2, normalized_at="2026-08-21 10:00:00")
    after = seed(conn, 2, normalized_at="2026-08-21 10:00:01")

    received = collect(client, {"updated_after": "2026-08-21T10:00:00Z"})
    assert set(received) == set(after)
    assert not set(received) & (set(before) | set(at))

    everything = collect(client, {"updated_after": "2026-08-21T09:00:00Z"})
    assert set(everything) == set(before) | set(at) | set(after)


def test_updated_after_uses_normalized_at_not_crawled_at(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """수집은 옛날에 했어도 정규화가 최근이면 온다. 커서가 걸린 값은 normalized_at 이다."""
    kept = seed(conn, 1, normalized_at="2026-08-21 10:00:05")
    conn.execute("UPDATE raw_jobs SET crawled_at = '2020-01-01 00:00:00'")

    received = collect(client, {"updated_after": "2026-08-21T10:00:00Z"})
    assert received == kept


def test_updated_after_accepts_offset_and_naive_forms(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """+09:00 은 UTC 로 옮겨 비교한다. 로컬 시각으로 해석하면 시차만큼 못 받는 구간이 생긴다."""
    seed(conn, 1, normalized_at="2026-08-21 02:00:00")
    late = seed(conn, 1, normalized_at="2026-08-21 04:00:00")

    # 2026-08-21T12:00:00+09:00 == 2026-08-21T03:00:00Z
    by_offset = collect(client, {"updated_after": "2026-08-21T12:00:00+09:00"})
    assert by_offset == late
    # 타임존이 없으면 UTC 로 본다
    by_naive = collect(client, {"updated_after": "2026-08-21T03:00:00"})
    assert by_naive == late


def test_broken_updated_after_is_rejected(client: TestClient) -> None:
    response = client.get("/api/jobs", params={"updated_after": "어제"})
    assert response.status_code == 422
