"""여섯 사이트의 2026-08-25 응답 픽스처가 실제로 쓸 수 있는 것인지 본다.

Push 4 는 이 픽스처만 보고 설정을 만든다. 그래서 파일이 제자리에 있고, 항목 수가 측정한
숫자와 같고, 설정이 읽을 키가 실제로 들어 있는지를 먼저 확인한다. 여기가 깨지면 뒤의 시험은
전부 잘못된 입력 위에서 도는 것이라 통과해도 의미가 없다.

숫자는 `../.claude/tasks/done/fill-body/tasks-fill-body-push4.md` 의 측정값이다.

| 사이트 | 목록 | 상세 |
|---|---|---|
| LG | 88 (`data.jobNoticeList`) | `data.jobNoticesDetail` |
| 한화 | 20+20+20+8 = 68 (`data.list`) | `data.item` |
| 삼성 | 9+7 = 16 (`li`) | `data.result` |
| SK | 104 (`list`) | 서버 렌더 HTML |
| 현대 | 20 (`data.applyList`) | `data.applyInfo` |
| 롯데 | 8 (`ul.job-card-list > li`) | 서버 렌더 HTML |

`hyundai-detail-20260825.html`(`/apply/applyView.hc`)은 옮기지 않았다. 텍스트가 1,098자뿐인
JS 껍데기라 파싱할 것이 없고, 현대 상세는 `AP-HM-FO-02800` API 가 평문으로 준다.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from bs4 import BeautifulSoup

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_html(name: str) -> BeautifulSoup:
    return BeautifulSoup((FIXTURES / name).read_text(encoding="utf-8"), "html.parser")


def test_the_lg_list_holds_every_posting_with_its_deadline() -> None:
    """88건. 마감일 `recEndDateTime` 이 항목마다 있다."""
    payload = load_json("lg-list-20260825.json")

    entries = payload["data"]["jobNoticeList"]
    assert payload["data"]["listCount"] == 88
    assert len(entries) == 88
    for entry in entries:
        assert entry["jobNoticeId"]
        assert entry["jobNoticeName"]
        assert entry["recEndDateTime"]


def test_the_lg_detail_holds_the_body_of_every_sector() -> None:
    """`recList` 는 모집 부문마다 한 칸이다. 첫 칸만 읽으면 나머지 부문의 본문이 사라진다."""
    detail = load_json("lg-detail-20260825.json")["data"]["jobNoticesDetail"]

    assert detail["jobNoticesDetail"]["jobNoticeName"]
    assert len(detail["recList"]) == 6
    assert all(sector["detailContext"] for sector in detail["recList"])


def test_the_hanwha_list_needs_four_pages_to_reach_sixty_eight() -> None:
    """첫 쪽에만 `totalCount` 가 오고, 마지막 쪽에서 `hasNext` 가 false 가 된다."""
    pages = [load_json(f"hanwha-list-p{index}-20260825.json") for index in range(4)]

    assert pages[0]["data"]["totalCount"] == 68
    assert [len(page["data"]["list"]) for page in pages] == [20, 20, 20, 8]
    assert sum(len(page["data"]["list"]) for page in pages) == 68
    assert [page["data"]["hasNext"] for page in pages] == [True, True, True, False]
    for entry in pages[0]["data"]["list"]:
        assert entry["rtSeq"]
        assert entry["rtNm"]
        assert entry["rtAcptEndDttm"]


def test_the_hanwha_detail_holds_the_job_body() -> None:
    """본문은 `unitDt` 안에 있다. 모집 단위마다 한 칸이다."""
    item = load_json("hanwha-detail-20260825.json")["data"]["item"]

    assert item["rtNm"]
    assert item["rtExmQlf"]
    assert all(unit["ruDtlJob"] for unit in item["unitDt"])


def test_the_samsung_list_needs_two_pages_to_reach_sixteen() -> None:
    """총 수와 쪽 수는 응답 안 `input.divCnt` 에 있다. 공고 번호에는 천 단위 쉼표가 있다."""
    pages = [load_html(f"samsung-list-p{index}-20260825.html") for index in (1, 2)]

    counter = pages[0].select_one("input.divCnt")
    assert counter is not None
    assert counter["data-value"] == "16"
    assert counter["data-max"] == "2"

    assert [len(page.select("li")) for page in pages] == [9, 7]
    assert sum(len(page.select("li")) for page in pages) == 16
    for page in pages:
        for node in page.select("li"):
            link = node.select_one("a[data-value]")
            assert link is not None
            assert str(link["data-value"]).replace(",", "").isdigit()
            assert node.select_one("h3.title") is not None


def test_the_samsung_detail_holds_a_body_per_role() -> None:
    """공고 하나에 모집 직무가 여럿이다. 본문은 `data.items` 쪽에 있다."""
    data = load_json("samsung-detail-20260825.json")["data"]

    assert data["result"]["seq"] == 22878
    assert data["result"]["title"]
    assert len(data["items"]) == 12
    assert all(role["taskKr"] for role in data["items"])


def test_the_sk_list_comes_in_one_page() -> None:
    """104건이 한 번에 온다. 마감일 `end` 는 영어 월 이름이다."""
    payload = load_json("sk-list-20260825.json")

    assert payload["totalCount"] == 104
    assert len(payload["list"]) == 104
    for entry in payload["list"]:
        assert entry["noticeID"]
        assert entry["title"]
        assert entry["end"]
    assert payload["list"][0]["end"] == "August 25, 2026(Tue)"


def test_the_sk_detail_is_server_rendered_html() -> None:
    """상세는 HTML 이다. 지금 셀렉터가 그대로 잡는다."""
    page = load_html("sk-detail-20260825.html")

    assert page.select_one(".box-title") is not None
    assert page.select_one(".detail-content-wrapper") is not None


def test_the_hyundai_list_carries_the_three_detail_parameters() -> None:
    """상세 주소는 한 값이 아니라 세 값으로 만들어진다."""
    payload = load_json("hyundai-list-20260825.json")

    entries = payload["data"]["applyList"]
    assert len(entries) == 20
    for entry in entries:
        assert entry["recuYy"]
        assert entry["recuType"]
        assert entry["recuCls"]
        assert entry["recuNoticeNm"]


def test_the_hyundai_detail_api_gives_plain_text() -> None:
    """`data.applyInfo` 가 평문으로 준다. `applyView.hc` HTML 을 파싱할 이유가 없다."""
    info = load_json("hyundai-detail-02800-20260825.json")["data"]["applyInfo"]

    assert info["recuNoticeNm"]
    assert info["privJdDtl"]
    assert info["privMustReq"]
    assert info["applyEndDt"] == "20260830"


def test_the_lotte_pages_are_static_html() -> None:
    """목록 8건, 상세는 `.board-content` 한 덩어리다."""
    listing = load_html("lotte-list-20260825.html")
    detail = load_html("lotte-detail-20260825.html")

    assert len(listing.select("ul.job-card-list > li")) == 8
    assert detail.select_one(".board-content") is not None
    assert detail.select_one("h4.title") is not None
