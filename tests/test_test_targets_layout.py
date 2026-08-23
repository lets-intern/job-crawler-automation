"""실행 대상 표가 밀리지 않게 하는 구조 (13.3).

폭과 높이는 브라우저가 정하므로 여기서 재지 않는다. 대신 그 결과를 만드는 구조를 지킨다 —
`.claude/docs/` 가 아니라 `app/templates/base.html` 의 CSS 가 아래 세 가지를 전제로 쓰였고,
조각이 그 전제를 깨면 표가 다시 밀린다.

| 지키는 것 | 깨지면 |
|---|---|
| 대기 문구가 표 안에 있다 | `.data-table .wait-note` 가 안 걸려 흐름에 남고, 그 칸이 넓어진다 |
| 안내 문구가 캡션 안에 있다 | 표 앞에 문단이 생기면서 그 높이만큼 표가 내려간다 |
| URL 이 `cell-url-value` 로 싸여 있다 | 긴 URL 이 열 폭을 밀어내고 이름 열이 접힌다 |

2026-08-22 측정(뷰포트 1440·1024, Chromium): 대기 표시가 들어오기 전후로 열 폭
`[45.38, 144, 100.88, 122.34, 312, 474.89]`, 행 높이 `[71, 71, 71]`, 표 폭 `1199.48` 이
모두 같았다. 긴 URL 행의 이름 열은 144px 한 줄을 유지했다.
"""

from __future__ import annotations

import html as html_escape
import pathlib
import re
import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import crawlers as crawlers_api
from app.main import app

# 열 폭을 밀어내던 길이의 실제 URL 모양
LONG_URL = (
    "https://recruit.example.co.kr/hire/main/list"
    "?srchClassCd=100&srchJobCd=1000&srchCareerCd=all&pageIndex=1&sortColumn=REG_DT"
)


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    connection.execute(
        "INSERT INTO crawlers (name, list_url, list_mode) VALUES ('긴 URL 크롤러', ?, 'static')",
        (LONG_URL,),
    )
    connection.commit()
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

    app.dependency_overrides[crawlers_api.get_connection] = request_connection
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_대기_문구는_표_안에_있다(client: TestClient) -> None:
    """`.data-table .wait-note` 가 흐름에서 빼낸다. 표 밖에 두면 그 규칙이 안 걸린다."""
    html = client.get("/ui/test-targets").text

    table = html[html.index("<table") : html.index("</table>")]
    assert html.count("wait-note") == table.count("wait-note")
    assert table.count("wait-note") == 2  # 저장 모드 전환과 테스트 실행


def test_안내_문구는_캡션_안에_들어간다(client: TestClient) -> None:
    """표 앞에 문단으로 끼워 넣으면 그 높이만큼 표가 내려간다."""
    html = client.put("/ui/test-targets/1/render-mode", data={"render_mode": "playwright"}).text

    caption = re.search(r"<caption>(.*?)</caption>", html, re.S)
    assert caption is not None
    assert "저장 모드를" in caption.group(1)
    # 캡션보다 앞에 오는 것은 표 상자뿐이다
    assert html[: html.index("<caption>")].strip().startswith('<div class="table-scroll">')


def test_긴_URL_은_말줄임_칸에_들어간다(client: TestClient) -> None:
    """전체 값은 title 로 본다. 열 폭 상한은 `.cell-url-value` 가 들고 있다."""
    html = client.get("/ui/test-targets").text

    escaped = html_escape.escape(LONG_URL, quote=True)
    assert f'<span class="cell-url-value" title="{escaped}">{escaped}</span>' in html
