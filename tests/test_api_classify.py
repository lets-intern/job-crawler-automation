"""분류 API 테스트.

Gemini 도 실사이트도 부르지 않는다. 확인하는 것은 라우트가 무엇을 돌려주는가와, 이미 돌고
있을 때 두 번 걸리지 않는가다.
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import classify as classify_api
from app.api import rules as rules_api
from app.classify.batch import ClassifyProgress, ClassifyRun
from app.main import app
from tests.test_classify_run import _seed


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    _seed(connection)
    try:
        yield connection
    finally:
        connection.close()


class StubRun(ClassifyRun):
    """스레드를 띄우지 않는다. 무엇으로 불렸는지만 적어 둔다."""

    def __init__(self) -> None:
        super().__init__()
        self.limits: list[int] = []

    def start(self, connect, limit=50):  # type: ignore[no-untyped-def]
        self.limits.append(limit)
        return ClassifyProgress(running=True, started_at="2026-08-26T00:00:00+00:00")


@pytest.fixture
def client(
    tmp_path: pathlib.Path, conn: sqlite3.Connection
) -> Iterator[tuple[TestClient, StubRun]]:
    run = StubRun()

    def request_connection() -> Iterator[sqlite3.Connection]:
        connection = db.connect(tmp_path / "jobs.db")
        try:
            yield connection
        finally:
            connection.close()

    app.dependency_overrides[rules_api.get_connection] = request_connection
    app.dependency_overrides[classify_api.get_classify_run] = lambda: run
    try:
        yield TestClient(app), run
    finally:
        app.dependency_overrides.clear()


def test_it_reports_how_many_are_still_unclassified(
    client: tuple[TestClient, StubRun],
) -> None:
    """화면이 "몇 건 남았나" 로 읽는 값이다 (1.7 이 쓴다)."""
    response = client[0].get("/api/classify")

    assert response.status_code == 200
    body = response.json()
    assert body["pending"] == 3
    assert body["running"] is False


def test_starting_it_answers_that_it_started(client: tuple[TestClient, StubRun]) -> None:
    response = client[0].post("/api/classify?limit=20")

    assert response.status_code == 202
    assert response.json()["running"] is True
    assert client[1].limits == [20]


def test_a_batch_over_the_cap_is_cut_not_refused(client: tuple[TestClient, StubRun]) -> None:
    """640건을 한 번에 달라고 해도 상한까지만 돈다."""
    response = client[0].post("/api/classify?limit=10000")

    assert response.status_code == 202
    assert client[1].limits == [200]


def test_a_second_request_while_it_runs_is_refused(
    tmp_path: pathlib.Path, conn: sqlite3.Connection
) -> None:
    """같은 분류가 둘이면 같은 공고에 두 번 돈을 쓴다."""
    run = ClassifyRun()
    run._progress = ClassifyProgress(running=True)

    def request_connection() -> Iterator[sqlite3.Connection]:
        connection = db.connect(tmp_path / "jobs.db")
        try:
            yield connection
        finally:
            connection.close()

    app.dependency_overrides[rules_api.get_connection] = request_connection
    app.dependency_overrides[classify_api.get_classify_run] = lambda: run
    try:
        response = TestClient(app).post("/api/classify")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "already_running"
