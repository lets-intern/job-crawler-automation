"""`crawlers.api_config_json` 의 형식 검증.

실제로 쓰는 설정(LG)을 픽스처로 두고, 그것을 조금씩 망가뜨려 무엇이 실패로 잡히는지 본다.
망가진 설정을 조용히 고쳐서 통과시키지 않는 것이 이 스키마의 일이다.
"""

from __future__ import annotations

import copy
import json
import pathlib
from typing import Any

import pytest

from app.selector.api_schema import (
    ApiConfigError,
    parse_api_config,
    validate_api_config,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
LG_CONFIG_TEXT = (FIXTURES / "lg-api-config-20260824.json").read_text(encoding="utf-8")


@pytest.fixture
def config() -> dict[str, Any]:
    """LG 설정 한 벌. 시험마다 복사본을 준다 — 한 시험이 망가뜨린 것이 다음으로 새면 안 된다."""
    return copy.deepcopy(json.loads(LG_CONFIG_TEXT))


def test_the_lg_config_passes(config: dict[str, Any]) -> None:
    """실제로 쓰는 설정이 통과한다. 통과 못 하면 23.5 가 실행될 수 없다."""
    parsed = validate_api_config(config)

    listing = parsed.list_config()
    assert listing.url == "https://api.careers.lg.com/rmk/job/retrieveJobNoticesList"
    assert listing.method == "POST"
    assert listing.items_path == "data.jobNoticeList"
    assert listing.id_field == "jobNoticeId"
    assert listing.body["recDate"] == "POST_START_DATE"
    assert listing.fields["title"] == "jobNoticeName"

    detail = parsed.detail_config()
    assert detail.body == {"jobNoticeId": "{id}"}
    assert detail.fields["body"] == "data.jobNoticesDetail.recList.0.detailContext"


def test_the_saved_text_round_trips(config: dict[str, Any]) -> None:
    """DB 에 넣고 다시 읽어도 같은 설정이다."""
    saved = validate_api_config(config).to_json()

    assert parse_api_config(saved) == validate_api_config(config)


def test_an_empty_column_is_a_config_with_neither_side() -> None:
    """`api` 를 안 쓰는 크롤러는 이 컬럼이 NULL 이다. 그것은 실패가 아니다."""
    empty = parse_api_config(None)

    assert (empty.list, empty.detail) == (None, None)


def test_a_list_only_config_passes(config: dict[str, Any]) -> None:
    """목록만 `api` 인 크롤러가 있다. 상세 설정을 요구하지 않는다."""
    del config["detail"]

    parsed = validate_api_config(config)

    assert parsed.detail is None
    with pytest.raises(ApiConfigError) as caught:
        parsed.detail_config()
    assert caught.value.reason == "missing_field"


def test_a_missing_items_path_names_the_field(config: dict[str, Any]) -> None:
    """`items_path` 가 없으면 응답 어디를 읽을지 모른다. 이름을 대고 거절한다."""
    del config["list"]["items_path"]

    with pytest.raises(ApiConfigError) as caught:
        validate_api_config(config)

    assert caught.value.reason == "missing_field"
    assert "list.items_path" in str(caught.value)


def test_a_blank_items_path_is_the_same_failure(config: dict[str, Any]) -> None:
    config["list"]["items_path"] = "   "

    with pytest.raises(ApiConfigError) as caught:
        validate_api_config(config)

    assert caught.value.reason == "missing_field"
    assert "list.items_path" in str(caught.value)


@pytest.mark.parametrize("section", ["list", "detail"])
def test_empty_fields_name_the_section(config: dict[str, Any], section: str) -> None:
    """읽을 필드가 하나도 없는 설정은 실행해 봐야 빈 공고만 나온다."""
    config[section]["fields"] = {}

    with pytest.raises(ApiConfigError) as caught:
        validate_api_config(config)

    assert caught.value.reason == "missing_field"
    assert f"{section}.fields" in str(caught.value)


@pytest.mark.parametrize("section", ["list", "detail"])
def test_a_missing_fields_key_names_the_section(config: dict[str, Any], section: str) -> None:
    del config[section]["fields"]

    with pytest.raises(ApiConfigError) as caught:
        validate_api_config(config)

    assert caught.value.reason == "missing_field"
    assert f"{section}.fields" in str(caught.value)


def test_an_unknown_field_name_is_refused(config: dict[str, Any]) -> None:
    """스키마에 없는 이름은 무엇을 말하려던 것인지 추측하지 않는다."""
    config["detail"]["fields"]["salary"] = "data.pay"

    with pytest.raises(ApiConfigError) as caught:
        validate_api_config(config)

    assert caught.value.reason == "unknown_field"
    assert "salary" in str(caught.value)


def test_a_link_template_without_the_id_is_refused(config: dict[str, Any]) -> None:
    """이 값이 `raw_jobs.source_url` 이 된다. 공고마다 같으면 링크도 중복 판정도 무너진다."""
    config["list"]["link_template"] = "https://careers.lg.com/apply"

    with pytest.raises(ApiConfigError) as caught:
        validate_api_config(config)

    assert caught.value.reason == "missing_field"
    assert "link_template" in str(caught.value)


def test_a_detail_without_the_id_is_refused(config: dict[str, Any]) -> None:
    """id 가 안 들어가면 공고가 몇 건이든 같은 상세를 가져온다."""
    config["detail"]["body"] = {"jobNoticeId": 1002029}

    with pytest.raises(ApiConfigError) as caught:
        validate_api_config(config)

    assert caught.value.reason == "missing_field"
    assert "{id}" in str(caught.value)


def test_an_unknown_method_is_refused(config: dict[str, Any]) -> None:
    config["list"]["method"] = "PATCH"

    with pytest.raises(ApiConfigError) as caught:
        validate_api_config(config)

    assert caught.value.reason == "unknown_field"


def test_a_non_http_url_is_refused(config: dict[str, Any]) -> None:
    config["list"]["url"] = "api.careers.lg.com/rmk/job/retrieveJobNoticesList"

    with pytest.raises(ApiConfigError) as caught:
        validate_api_config(config)

    assert caught.value.reason == "missing_field"
    assert "list.url" in str(caught.value)


def test_an_unknown_section_is_refused(config: dict[str, Any]) -> None:
    config["pagination"] = {"url": "https://example.test"}

    with pytest.raises(ApiConfigError) as caught:
        validate_api_config(config)

    assert caught.value.reason == "unknown_field"
    assert "pagination" in str(caught.value)


def test_text_that_is_not_json_is_unparsable() -> None:
    with pytest.raises(ApiConfigError) as caught:
        parse_api_config("{목록:")

    assert caught.value.reason == "unparsable"
