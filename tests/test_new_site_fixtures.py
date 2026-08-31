"""새 다섯 사이트의 2026-08-26 상세 응답 픽스처가 실제로 쓸 수 있는 것인지 본다.

칸을 확정하는 대조(`../.claude/tasks/memos/보류/split-body/tasks-split-body-push1.md` 1.2)가
이 파일들만 보고
"이 사이트가 이 값을 주는가" 를 센다. 그래서 파일이 제자리에 있고, 셀 항목이 실제로 들어
있는지를 먼저 확인한다. 여기가 깨지면 표가 잘못된 입력 위에서 만들어진다.

기존 여섯 사이트는 `tests/test_site_fixtures.py` 가 본다. 상세는 사이트당 1회만 요청했다.

| 사이트 | 크롤러 | 상세 수집 | 픽스처 |
|---|---|---|---|
| 두산 | 31 | static GET | `doosan-detail-1000361539-20260826.html` |
| 네이버 | 32 | static GET | `naver-detail-30005299-20260826.html` |
| 토스 | 33 | static GET | `toss-detail-7827417003-20260826.html` |
| 카카오 | 30 | playwright | `kakao-detail-P-14503-20260826.html` |
| 우아한형제들 | 29 | playwright | `woowa-detail-R2607031-20260826.html` |

목록은 새로 받지 않았다. 카카오·우아한형제들은 목록이 API 라 2026-08-25 픽스처가 그대로 있고
(`kakao-list-api-20260825.json`, `woowa-list-api-20260825.json`), 표는 그 둘도 함께 센다.
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


def text(soup: BeautifulSoup, selector: str) -> str:
    """그 자리가 있고 비어 있지 않은지까지 본다. 없으면 그 이름을 대고 실패한다."""
    node = soup.select_one(selector)
    assert node is not None, selector
    return node.get_text(" ", strip=True)


def labelled(soup: BeautifulSoup, selector: str) -> dict[str, str]:
    """`dt`-`dd` 로 이름표가 붙은 값을 이름표 -> 값으로 모은다."""
    pairs: dict[str, str] = {}
    for node in soup.select(selector):
        label = node.select_one("dt")
        value = node.select_one("dd")
        if label is not None and value is not None:
            pairs[label.get_text(" ", strip=True)] = value.get_text(" ", strip=True)
    return pairs


def test_the_doosan_detail_labels_every_value_it_gives() -> None:
    """`div.view-list-wrap` 의 `li.tb*` 가 이름표와 값을 짝지어 준다."""
    soup = load_html("doosan-detail-1000361539-20260826.html")

    assert text(soup, "h2.h2-title")
    pairs = labelled(soup, "div.view-list-wrap li")
    assert set(pairs) >= {"자회사/BG", "인원", "모집분야", "지역"}
    assert pairs["지역"]
    assert pairs["인원"]

    rows = {
        cells[0].get_text(" ", strip=True): cells[1].get_text(" ", strip=True)
        for cells in (row.select("th, td") for row in soup.select("table tr"))
        if len(cells) >= 2
    }
    assert set(rows) >= {"자격요건", "전형절차", "기타사항", "채용공고"}
    assert " ~ " in rows["채용공고"]


def test_the_naver_detail_gives_its_values_as_labelled_pairs() -> None:
    """`.card_info` 의 `dt` 는 `blind` 라 화면에 안 보이지만 이름표는 거기 있다."""
    soup = load_html("naver-detail-30005299-20260826.html")

    assert text(soup, "h4.card_title")
    labels = [node.get_text(" ", strip=True) for node in soup.select(".card_info dt")]
    values = [node.get_text(" ", strip=True) for node in soup.select(".card_info dd")]
    assert len(labels) == len(values)
    assert {"모집 분야", "모집 경력", "근로 조건", "모집 기간"} <= set(labels)
    assert " ~ " in values[labels.index("모집 기간")]
    assert text(soup, ".detail_wrap")


def test_the_toss_detail_carries_the_body_under_the_generated_class() -> None:
    """레시피가 정한 자리다. 앞의 `.p-container__inner` 는 네비게이션 37자다."""
    soup = load_html("toss-detail-7827417003-20260826.html")

    assert text(soup, "title")
    bodies = soup.select(".p-container.css-6bhaou .p-container__inner")
    assert len(bodies) == 1
    assert len(bodies[0].get_text(strip=True)) > 1000

    badges = [node.get_text(" ", strip=True) for node in soup.select("h5")]
    assert len(badges) >= 2
    assert any("모집 기간" in node.get_text(" ", strip=True) for node in soup.select("blockquote"))


def test_the_kakao_detail_labels_the_values_the_list_api_also_gives() -> None:
    """상세는 `.list_info` 넷뿐이고 본문은 한 덩어리다. 나뉜 값은 목록 API 에 있다."""
    soup = load_html("kakao-detail-P-14503-20260826.html")

    assert text(soup, ".tit_jobs")
    labels = [node.get_text(" ", strip=True) for node in soup.select(".list_info dt")]
    assert {"회사정보", "직원유형", "영입마감일", "근무지 정보"} <= set(labels)
    assert text(soup, ".cont_board")

    entry = load_json("kakao-list-api-20260825.json")["jobList"][0]
    for key in (
        "jobOfferTitle",
        "companyName",
        "jobPartName",
        "locationName",
        "employeeTypeName",
        "introduction",
        "workContentDesc",
        "qualification",
        "jobOfferProcessDesc",
    ):
        assert entry[key], key


def test_the_woowa_detail_gives_flags_but_one_body_blob() -> None:
    """`.flag-*` 셋이 나뉜 값의 전부다. 목록 API 는 코드만 주고 이름을 주지 않는다."""
    soup = load_html("woowa-detail-R2607031-20260826.html")

    assert text(soup, ".recruit-detail-title-inner .title")
    assert text(soup, ".flag-career")
    assert len(soup.select(".flag-type span")) == 2
    assert soup.select(".flag-tag button")
    assert text(soup, ".detail-view")

    entry = load_json("woowa-list-api-20260825.json")["data"]["list"][0]
    assert entry["recruitName"]
    assert entry["recruitOpenDate"]
    # 코드만 오고 이름이 없다. 그래서 직군·고용형태·경력은 상세의 `.flag-*` 에서 읽는다
    assert set(entry["jobGroup"]) == {"recruitItemGroupCode", "recruitItemCode", "primary"}
    assert entry["recruitmentRequestOrganizationName"] == ""
