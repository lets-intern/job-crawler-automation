"""레시피에 적은 칸 매핑이 설정과 같은지 대조한다 (1.2.V).

문서에 적는 필드명은 설정에서 복사한다. 기억으로 다시 쓰면 사이트를 고칠 때 문서가 가리키는
자리와 실제로 도는 자리가 갈리고, 그 차이는 크롤링이 깨진 뒤에야 드러난다
(`.claude/rules/writing.md`).

여기서 보는 것은 둘이다 — 열한 레시피에 매핑 절이 다 있는가, 그 절의 자리가
`seeds/site-configs-20260826.json` 의 값과 글자까지 같은가.

2026-08-26 에 수집이 여섯 칸으로 줄면서 이 절도 여섯 줄로 줄었다. 그래서 이 대조가 더
중요해졌다 — 지워진 매핑 하나가 설정에 되살아나면 그 값이 분류 결과를 이긴다.
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any

import pytest

from app.selector.api_schema import LIST_FIELDS
from app.selector.schema import DETAIL_FIELDS

ROOT = pathlib.Path(__file__).parent.parent
RECIPES = ROOT / ".claude" / "site-recipes"
SEEDS = ROOT / "seeds" / "site-configs-20260826.json"

CONFIGS: dict[str, dict[str, Any]] = {
    entry["name"]: entry for entry in json.loads(SEEDS.read_text(encoding="utf-8"))["crawlers"]
}

# 사이트마다 어느 레시피 파일에 적는지
RECIPE_FILE: dict[str, str] = {
    "LG": "careers-lg-com.md",
    "한화": "www-hanwhain-com.md",
    "삼성": "www-samsungcareers-com.md",
    "SK": "www-skcareers-com.md",
    "현대자동차": "talent-hyundai-com.md",
    "롯데그룹": "recruit-lotte-co-kr.md",
    "두산": "career-doosan-com.md",
    "네이버": "recruit-navercorp-com.md",
    "토스": "toss-im.md",
    "카카오": "careers-kakao-com.md",
    "우아한형제들": "career-woowayouths-com.md",
}

HEADING = "## 칸 매핑 (2026-08-26, 수집은 여섯 칸)"

# 표 한 줄에서 백틱 안의 자리만 꺼낸다
PLACE = re.compile(r"`([^`]+)`")

SITES = tuple(RECIPE_FILE)


def recipe_section(site: str) -> str:
    text = (RECIPES / RECIPE_FILE[site]).read_text(encoding="utf-8")
    assert HEADING in text, f"{site} 레시피에 칸 매핑 절이 없다"
    return text.split(HEADING, 1)[1]


def places_in_recipe(site: str) -> set[str]:
    """레시피 표가 적어 둔 자리 전부."""
    found: set[str] = set()
    for line in recipe_section(site).splitlines():
        if not line.startswith("| "):
            continue
        cell = line.rsplit("|", 2)[-2]
        found.update(PLACE.findall(cell))
    return found


def places_in_config(site: str) -> set[str]:
    """설정이 실제로 읽는 자리 전부. 목록 자신의 세 값은 칸이 아니라 세지 않는다."""
    entry = CONFIGS[site]
    api = entry.get("api_config", {})
    sections: list[dict[str, Any]] = []
    detail_fields = (api.get("detail") or {}).get("fields")
    if detail_fields:
        sections.append(detail_fields)
    list_fields = (api.get("list") or {}).get("fields")
    if list_fields:
        sections.append({k: v for k, v in list_fields.items() if k not in LIST_FIELDS})

    found: set[str] = set()
    for fields in sections:
        for path in fields.values():
            found.update(path if isinstance(path, list) else [path])

    selectors = (entry.get("selectors") or {}).get("detail") or {}
    found.update(value for name, value in selectors.items() if name in DETAIL_FIELDS and value)
    return found


@pytest.mark.parametrize("site", SITES)
def test_the_recipe_has_the_mapping_section(site: str) -> None:
    assert recipe_section(site).strip()


@pytest.mark.parametrize("site", SITES)
def test_the_recipe_places_are_the_ones_in_the_config(site: str) -> None:
    """문서가 기억으로 쓰였으면 여기서 갈린다."""
    invented = sorted(places_in_recipe(site) - places_in_config(site))
    assert invented == [], f"{site} 레시피에 설정에 없는 자리가 적혀 있다"


@pytest.mark.parametrize("site", SITES)
def test_the_recipe_does_not_leave_a_mapped_place_out(site: str) -> None:
    """설정이 읽는데 문서에 없는 자리. 다음 사람이 그 값을 어디서 오는지 모른다."""
    missing = sorted(places_in_config(site) - places_in_recipe(site))
    assert missing == [], f"{site} 설정에 있는 자리가 레시피에 없다"


def test_every_site_in_the_seeds_file_has_a_recipe() -> None:
    assert set(CONFIGS) == set(RECIPE_FILE)
