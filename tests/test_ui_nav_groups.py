"""위 네비게이션이 묶음으로 줄어든 것.

화면이 늘 때마다 위 줄이 계속 길어지지 않게, `NAV` 는 묶음 이름만 놓고 각 묶음의 실제
화면은 두 번째 줄(`group_nav`)에서 고른다 (`app/api/ui.py` 의 `NAV_GROUPS`).
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import rules as rules_api
from app.api.ui import NAV, NAV_GROUPS
from app.main import app


@pytest.fixture
def path(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path / "jobs.db"


@pytest.fixture
def conn(path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(path)
    db.migrate_up(connection)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def client(path: pathlib.Path, conn: sqlite3.Connection) -> Iterator[TestClient]:
    def request_connection() -> Iterator[sqlite3.Connection]:
        connection = db.connect(path)
        try:
            yield connection
        finally:
            connection.close()

    app.dependency_overrides[rules_api.get_connection] = request_connection
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_위_네비게이션은_묶음_셋뿐이다() -> None:
    assert [label for _, label in NAV] == ["수집", "데이터", "운영 설정"]


def test_묶음_안의_화면을_전부_합치면_여덟이다() -> None:
    """줄어든 것은 위 줄뿐이다. 화면 자체는 그대로 여덟이다."""
    grouped = sum(len(members) for _, _, members in NAV_GROUPS)
    assert grouped == 7  # 운영 설정은 묶이지 않는 여덟 번째 화면이다


@pytest.mark.parametrize(
    ("path_", "group_path"),
    [
        ("/", "/"),
        ("/tests", "/"),
        ("/workflows", "/"),
        ("/side", "/"),
        ("/rules", "/rules"),
        ("/review", "/rules"),
        ("/companies", "/rules"),
    ],
)
def test_묶인_화면은_위에서_자기_묶음이_켜진다(
    client: TestClient, path_: str, group_path: str
) -> None:
    """묶음의 대표 주소(`group_path`)가 위 네비게이션에서 `aria-current` 를 받는다."""
    body = client.get(path_).text

    assert f'<a href="{group_path}" aria-current="page"' in body


@pytest.mark.parametrize(
    ("path_", "own_label"),
    [
        ("/", "크롤러 등록"),
        ("/tests", "테스트 실행"),
        ("/workflows", "워크플로우"),
        ("/side", "부가 워크플로우"),
        ("/rules", "정규화 규칙"),
        ("/review", "데이터 검수"),
        ("/companies", "회사"),
    ],
)
def test_묶인_화면은_두_번째_줄에서_자기_자리가_켜진다(
    client: TestClient, path_: str, own_label: str
) -> None:
    body = client.get(path_).text

    assert f'href="{path_}" aria-current="page"' in body
    assert own_label in body


def test_묶음_안의_다른_화면도_두_번째_줄에서_보인다(client: TestClient) -> None:
    """`/` 에 있어도 같은 묶음의 나머지 셋이 눈에 보여야, 늘어난 화면을 찾을 수 있다."""
    body = client.get("/").text

    for member_path, label in next(members for _, name, members in NAV_GROUPS if name == "수집"):
        assert f'href="{member_path}"' in body
        assert label in body


def test_운영_설정은_묶이지_않고_그대로다(client: TestClient) -> None:
    body = client.get("/settings").text

    assert '<a href="/settings" aria-current="page"' in body
    # 운영 설정은 자기 하위 메뉴(SETTINGS_NAV)만 그린다. 두 번째 묶음 줄과 섞이지 않는다
    assert "정규화 규칙" not in body
