"""줍은 요청을 상세 설정으로 바꾸는 테스트.

실사이트를 부르지 않는다. 2026-08-25 에 받아 둔 응답 픽스처를 클릭 뒤 나간 요청인 것처럼
넣고, 나온 설정이 `parse_api_config()` 를 통과하는지 본다.
"""

from __future__ import annotations

import json
from pathlib import Path

from bs4 import BeautifulSoup
from bs4.element import Tag

from app.crawler.playwright import ObservedRequest
from app.selector.api_schema import ID_PLACEHOLDER, parse_api_config
from app.selector.detail_path import (
    API,
    FROM_ATTRIBUTE,
    FROM_LINK,
    IdSource,
    id_candidates,
    pick_detail_request,
    propose_detail_config,
)

FIXTURES = Path(__file__).parent / "fixtures"

SAMSUNG_DETAIL_URL = "https://www.samsungcareers.com/recruit/detail.data?seqno=22878&strCode="
LG_DETAIL_URL = "https://api.careers.lg.com/rmk/job/retrieveJobNoticesDetail"

# 삼성 목록 조각의 항목 하나. 번호가 `a[data-value]` 에 천 단위 쉼표와 함께 들어 있다
SAMSUNG_ITEM = """
<li class="list">
  <a href="/#none" data-value="22,878" data-type="recruit">
    <p class="company">삼성전자 DX부문</p>
    <p class="tit">2026년 상반기 3급 신입사원 채용</p>
  </a>
</li>
"""

# 롯데 항목. 상세 주소가 링크 안에 그대로 있다
LOTTE_ITEM = """
<li>
  <a href="/apply/announcement/detail/21931885">롯데케미칼 신입 채용</a>
</li>
"""

# 공고와 무관한 요청. 어느 공고를 눌러도 같은 응답이 온다
COMMON_REQUEST = ObservedRequest(
    method="GET",
    url="https://www.samsungcareers.com/common/config.data",
    status=200,
    content_type="application/json",
    body='{"data":{"theme":"light"}}',
)


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def item(html: str) -> Tag:
    node = BeautifulSoup(html, "html.parser").find(["li", "div"])
    assert isinstance(node, Tag)
    return node


def samsung_request() -> ObservedRequest:
    return ObservedRequest(
        method="GET",
        url=SAMSUNG_DETAIL_URL,
        status=200,
        content_type="application/json;charset=utf-8",
        body=read("samsung-detail-20260825.json"),
    )


def lg_request() -> ObservedRequest:
    return ObservedRequest(
        method="POST",
        url=LG_DETAIL_URL,
        status=200,
        content_type="application/json",
        request_body='{"jobNoticeId":1002099}',
        body=read("lg-detail-20260825.json"),
    )


def test_항목의_데이터_속성에서_공고_번호를_찾는다() -> None:
    found = id_candidates(item(SAMSUNG_ITEM))

    values = [(source.kind, source.detail, source.value) for source in found]
    assert (FROM_ATTRIBUTE, "data-value", "22,878") in values
    assert (FROM_ATTRIBUTE, "data-value", "22878") in values


def test_링크에서_공고_번호를_찾는다() -> None:
    node = item(LOTTE_ITEM)
    found = id_candidates(node, link="/apply/announcement/detail/21931885")

    assert found[0].kind == FROM_LINK
    assert found[0].value == "21931885"


def test_공고_번호가_든_요청만_고른다() -> None:
    node = item(SAMSUNG_ITEM)
    picked = pick_detail_request([COMMON_REQUEST, samsung_request()], id_candidates(node))

    assert picked is not None
    request, source = picked
    assert request.url == SAMSUNG_DETAIL_URL
    assert source.value == "22878"
    assert source.digits is True


def test_공고_번호가_어디에도_없으면_고르지_않는다() -> None:
    node = item(SAMSUNG_ITEM)

    assert pick_detail_request([COMMON_REQUEST], id_candidates(node)) is None


def test_삼성_설정이_형식_검증을_통과한다() -> None:
    node = item(SAMSUNG_ITEM)
    picked = pick_detail_request([samsung_request()], id_candidates(node))
    assert picked is not None

    path = propose_detail_config(*picked)

    assert path.ok is True
    assert path.kind == API
    assert path.api is not None
    detail = parse_api_config(path.api.to_json()).detail_config()
    assert detail.url == "https://www.samsungcareers.com/recruit/detail.data?seqno={id}&strCode="
    assert detail.method == "GET"
    assert detail.fields["title"] == "data.result.title"
    assert detail.fields["body"] == "data.items.*.taskKr"


def test_LG_는_본문의_번호가_자리표시자가_된다() -> None:
    node = item('<li data-id="1002099">공고</li>')
    picked = pick_detail_request([lg_request()], id_candidates(node))
    assert picked is not None

    path = propose_detail_config(*picked)

    assert path.ok is True
    assert path.api is not None
    detail = parse_api_config(path.api.to_json()).detail_config()
    assert detail.url == LG_DETAIL_URL
    assert detail.body == {"jobNoticeId": ID_PLACEHOLDER}
    assert detail.fields["body"] == "data.jobNoticesDetail.recList.*.detailContext"


def test_공고_번호를_어디서_얻는지_같이_남는다() -> None:
    node = item(SAMSUNG_ITEM)
    picked = pick_detail_request([samsung_request()], id_candidates(node))
    assert picked is not None

    path = propose_detail_config(*picked)

    assert path.id_source is not None
    assert path.id_source.detail == "data-value"
    assert path.id_source.digits is True
    assert "22878" in path.notes[0]


def test_못_찾은_필드는_이름으로_남는다() -> None:
    node = item(SAMSUNG_ITEM)
    picked = pick_detail_request([samsung_request()], id_candidates(node))
    assert picked is not None

    path = propose_detail_config(*picked)

    assert "department" in path.missing
    assert path.api is not None
    assert "department" not in (path.api.detail.fields if path.api.detail else {})


def test_응답이_JSON_이_아니면_상세_설정으로_만들지_않는다() -> None:
    request = ObservedRequest(
        method="GET",
        url="https://recruit.lotte.co.kr/apply/announcement/detail/21931885",
        status=200,
        content_type="text/html;charset=utf-8",
        body="<html><body>상세 문서</body></html>",
    )
    source = IdSource(kind=FROM_LINK, detail="마지막", value="21931885")

    path = propose_detail_config(request, source)

    assert path.ok is False
    assert "JSON 이 아니다" in path.reason


def test_폼_본문으로_나가는_상세는_담을_수_없다고_말한다() -> None:
    """상세 설정에는 폼으로 보낼 자리가 없다. 그대로 저장하면 실행이 전부 실패한다."""
    request = ObservedRequest(
        method="POST",
        url="https://example.test/recruit/detail",
        status=200,
        content_type="application/json",
        request_body="seqno=22878&strCode=",
        body='{"data":{"title":"공고","content":"본문이 길게 들어 있다" }}',
    )
    source = IdSource(kind=FROM_ATTRIBUTE, detail="data-value", value="22878")

    path = propose_detail_config(request, source)

    assert path.ok is False
    assert "폼 본문" in path.reason


def test_공고를_지목하지_않는_요청은_설정이_되지_않는다() -> None:
    """`{id}` 가 주소에도 본문에도 없으면 공고가 몇 건이든 같은 상세를 가져온다."""
    request = ObservedRequest(
        method="GET",
        url="https://example.test/recruit/detail",
        status=200,
        content_type="application/json",
        body=json.dumps({"data": {"title": "공고", "content": "본문 " * 20}}, ensure_ascii=False),
    )
    source = IdSource(kind=FROM_ATTRIBUTE, detail="data-value", value="22878")

    path = propose_detail_config(request, source)

    assert path.ok is False
    assert ID_PLACEHOLDER in path.reason
