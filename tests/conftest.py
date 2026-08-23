"""테스트 공통 설정.

Push 22 에서 운영 화면과 API 에 비밀번호 잠금이 붙었다 (`app/api/auth.py`). 기존 테스트는
30개 파일이 저마다 TestClient 를 만들어 잠긴 경로를 직접 부른다.

테스트에서 잠금을 끄는 스위치를 만들지 않는다. 그런 스위치는 운영에서 켜지는 순간 자물쇠가
통째로 없어지는 길이 되고, 잠금이 평소 동작을 깨는지도 확인하지 못한다. 대신 만들어지는 모든
TestClient 에 정상 서명된 쿠키를 하나 넣어 준다 — 미들웨어와 서명 검사를 전체 스위트가 매번
그대로 지나간다.

잠긴 쪽을 보는 테스트는 `client.cookies.clear()` 로 쿠키를 지우고 부른다
(`tests/test_admin_auth.py`).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import auth


@pytest.fixture(autouse=True)
def admin_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """이 테스트에서 만들어지는 TestClient 에 유효한 세션 쿠키를 붙인다."""
    original_init = TestClient.__init__

    def init_with_session(self: TestClient, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        self.cookies.set(auth.COOKIE_NAME, auth.issue_token())

    monkeypatch.setattr(TestClient, "__init__", init_with_session)
