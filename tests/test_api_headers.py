"""API 설정에 담은 헤더가 실제 요청에 실려 나가는지 본다. 픽스처로만 돈다.

현대 목록 API 는 `x-hkmc-service` 와 `referer` 가 없으면 400 을 준다 (2026-08-25 측정,
`.claude/tasks/done/fill-body/tasks-fill-body-push4.md`). 그래서 사이트가 요구하는 기능성
헤더를 설정에 담을 자리가 필요하다.

담을 수 없는 것이 하나 있다. `User-Agent` 는 공용 fetch 클라이언트가 정하고 설정이 덮을 수
없다 — 덮을 수 있으면 브라우저 위장이 크롤러 등록만으로 가능해진다
(`.claude/rules/crawling.md`).
"""

from __future__ import annotations

import json
import pathlib

import httpx
import pytest

from app.config import Settings
from app.crawler.api_source import fetch_detail, fetch_list
from app.crawler.fetcher import Fetcher
from app.selector.api_schema import ApiConfigError, validate_api_config

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
LIST_PAYLOAD = (FIXTURES / "hyundai-list-20260825.json").read_text(encoding="utf-8")
DETAIL_PAYLOAD = (FIXTURES / "hyundai-detail-02800-20260825.json").read_text(encoding="utf-8")

ROBOTS = "User-agent: *\nAllow: /\n"

CONFIG = validate_api_config(
    {
        "list": {
            "url": "https://talent.hyundai.com/api/rec/AP-HM-FO-02730?hgrCd=1&lang=ko",
            "method": "GET",
            "items_path": "data.applyList",
            "fields": {"title": "recuNoticeNm", "date": "appDispEdDt"},
            "id_field": "recuCls",
            "link_template": "https://talent.hyundai.com/apply/applyView.hc?recuCls={id}",
            "headers": {
                "accept": "application/json, text/plain, */*",
                "referer": "https://talent.hyundai.com/theme/hall.hc",
                "x-hkmc-service": "HM",
                "x-hkmc-token": "null",
            },
        },
        "detail": {
            "url": "https://talent.hyundai.com/api/rec/AP-HM-FO-02800?recuCls={id}",
            "method": "GET",
            "fields": {"title": "data.applyInfo.recuNoticeNm", "body": "data.applyInfo.privJdDtl"},
            "headers": {
                "x-hkmc-service": "HM",
                "referer": "https://talent.hyundai.com/apply/applyView.hc",
            },
        },
    }
)


def fetcher_for(seen: list[httpx.Request]) -> Fetcher:
    """헤더가 없으면 실제 사이트처럼 400 을 준다."""

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        if request.headers.get("x-hkmc-service") != "HM":
            return httpx.Response(400, text="bad request")
        body = DETAIL_PAYLOAD if "02800" in request.url.path else LIST_PAYLOAD
        return httpx.Response(200, text=body, headers={"content-type": "application/json"})

    return Fetcher(
        settings=Settings(crawl_delay_seconds=0.0, crawl_max_retries=1),
        transport=httpx.MockTransport(handle),
    )


async def test_the_list_request_carries_the_headers_the_site_demands() -> None:
    """헤더가 실려야 200 이고, 그 응답에서 20건이 나온다."""
    seen: list[httpx.Request] = []
    client = fetcher_for(seen)

    result = await fetch_list(client, CONFIG.list_config())
    await client.aclose()

    sent = [request for request in seen if request.url.path.endswith("AP-HM-FO-02730")]
    assert len(sent) == 1
    assert sent[0].headers["x-hkmc-service"] == "HM"
    assert sent[0].headers["referer"] == "https://talent.hyundai.com/theme/hall.hc"
    assert sent[0].headers["x-hkmc-token"] == "null"
    assert len(result.items) == 20


async def test_the_detail_request_carries_its_own_referer() -> None:
    """상세는 목록과 다른 `referer` 를 요구한다. 두 설정이 갈려 있어야 한다."""
    seen: list[httpx.Request] = []
    client = fetcher_for(seen)

    detail = await fetch_detail(client, CONFIG.detail_config(), "296")
    await client.aclose()

    sent = [request for request in seen if request.url.path.endswith("AP-HM-FO-02800")]
    assert len(sent) == 1
    assert sent[0].headers["referer"] == "https://talent.hyundai.com/apply/applyView.hc"
    assert detail.fields["body"]


async def test_the_shared_user_agent_still_goes_out_with_the_extra_headers() -> None:
    """헤더를 담아도 이름은 공용 클라이언트 것이다."""
    seen: list[httpx.Request] = []
    client = fetcher_for(seen)

    await fetch_list(client, CONFIG.list_config())
    await client.aclose()

    sent = [request for request in seen if request.url.path.endswith("AP-HM-FO-02730")]
    assert sent[0].headers["user-agent"] == client.user_agent


def test_a_config_cannot_dress_the_crawler_up_as_a_browser() -> None:
    """`User-Agent` 를 설정에 담으면 저장 전에 거절된다."""
    with pytest.raises(ApiConfigError) as caught:
        validate_api_config(
            {
                "list": {
                    "url": "https://example.test/jobs",
                    "items_path": "data.list",
                    "fields": {"title": "name"},
                    "id_field": "id",
                    "link_template": "https://example.test/jobs/{id}",
                    "headers": {"User-Agent": "Mozilla/5.0 (Macintosh)"},
                }
            }
        )

    assert caught.value.reason == "unknown_field"
    assert "User-Agent" in str(caught.value)


def test_a_header_value_that_is_not_text_is_refused() -> None:
    """숫자를 담으면 헤더로 나갈 때 무엇이 될지 추측하지 않고 거절한다."""
    with pytest.raises(ApiConfigError) as caught:
        validate_api_config(
            {
                "list": {
                    "url": "https://example.test/jobs",
                    "items_path": "data.list",
                    "fields": {"title": "name"},
                    "id_field": "id",
                    "link_template": "https://example.test/jobs/{id}",
                    "headers": {"x-page": 1},
                }
            }
        )

    assert caught.value.reason == "unparsable"


def test_a_config_without_headers_still_loads() -> None:
    """헤더가 없는 기존 설정은 그대로 돈다. 빈 값이 기본이다."""
    config = validate_api_config(
        json.loads((FIXTURES / "lg-api-config-20260824.json").read_text(encoding="utf-8"))
    )

    assert config.list_config().headers == {}
    assert config.detail_config().headers == {}
