"""운영 설정의 하위 메뉴 (2.4.V 의 자동 확인분).

다섯으로 갈렸다 — AI 제공자 / 알림 / 동시 실행 / 스냅샷 내보내기 / 데이터 가져오기.
**자리만 옮겼고 동작은 그대로다.** 그래서 여기서 보는 것은 셋이다. 다섯이 다 열리는가,
각 화면이 옮기기 전과 같은 조각을 부르는가, 그리고 어느 하위 화면에 있든 위 네비게이션이
`운영 설정` 에 머무는가.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.ui import SETTINGS_NAV
from app.main import app

# 하위 화면 하나가 부르는 자리. 옮기면서 잃어버리기 쉬운 문자열이다
CALLS: tuple[tuple[str, str], ...] = (
    ("/settings", 'hx-get="/ui/llm"'),
    ("/settings/notify", 'hx-get="/ui/notify"'),
    ("/settings/runs", 'hx-get="/ui/settings"'),
    ("/settings/export", 'href="/ui/settings/export"'),
    ("/settings/import", 'hx-post="/ui/settings/import"'),
)


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield TestClient(app, follow_redirects=False)


def test_하위_메뉴가_다섯이다() -> None:
    assert [label for _, label in SETTINGS_NAV] == [
        "AI 제공자",
        "알림",
        "동시 실행",
        "스냅샷 내보내기",
        "데이터 가져오기",
    ]


@pytest.mark.parametrize(("path", "call"), CALLS)
def test_하위_화면이_옮기기_전과_같은_자리를_부른다(
    client: TestClient, path: str, call: str
) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert call in response.text


@pytest.mark.parametrize(("path", "_call"), CALLS)
def test_어느_하위_화면에서도_위_네비게이션은_운영_설정이다(
    client: TestClient, path: str, _call: str
) -> None:
    """`active` 를 주소 그대로 두면 하위 화면에서 위 네비게이션이 전부 꺼진다."""
    body = client.get(path).text

    assert '<a href="/settings" aria-current="page"' in body


@pytest.mark.parametrize(("path", "_call"), CALLS)
def test_하위_메뉴_다섯이_모든_화면에_있다(client: TestClient, path: str, _call: str) -> None:
    body = client.get(path).text

    for menu_path, label in SETTINGS_NAV:
        assert f'href="{menu_path}"' in body
        assert label in body
