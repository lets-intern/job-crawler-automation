"""받은 값이 본문에 실제로 있는지 그 자리에서 본다.

`.claude/rules/llm.md` 는 모델이 낸 것을 그 자리에서 돌려 보라고 한다. 셀렉터는 HTML 에
돌려 보면 되지만 분류에는 돌릴 것이 없다 — 대신 **뽑았다는 값이 본문 안에 있는지** 를 본다.

없는 값을 낸 칸은 버린다. 지어낸 값은 소비 측이 그대로 사실로 노출하고, 빈 칸보다 나쁘다
(`.claude/tasks/todo/prd-llm-classify.md`).

## 무엇을 같다고 보는가

비교 전에 양쪽에서 공백과 글머리표·구두점을 걷어내고 소문자로 맞춘다. 본문은 줄바꿈과
글머리표가 사이트마다 다르고, 같은 문장을 옮겨 적기만 해도 `- ` 가 `• ` 로 바뀐다. 거기서
어긋난 것을 지어냈다고 하면 멀쩡한 값이 통째로 버려진다.

**느슨한 것은 비교뿐이고 판정은 엄격하다.** 값이 여러 줄이면 줄마다 따로 보고, 한 줄이라도
본문에서 찾지 못하면 그 칸을 통째로 버린다. 절반만 사실인 값은 읽는 쪽이 어디까지 믿어야
할지 알 수 없다.

글자를 걷어낸 뒤 남는 것이 한 글자 이하인 줄은 세지 않는다. `-` 하나짜리 줄이나 `1.` 같은
번호는 본문 어디에나 있어서 검사가 되지 않는다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

# 비교에서 지우는 글자. 공백, 글머리표, 구두점, 괄호, 따옴표다. 뜻을 나르는 글자는 남는다
_NOISE = re.compile(r"[\s·•·◦○●□■▪▶▷–—\-*_.,;:!?()\[\]{}<>\"'`~/\\|]+")

# 이보다 짧아지는 줄은 검사 대상이 아니다
_MIN_LENGTH = 2


@dataclass(frozen=True)
class Grounded:
    """본문에 있는 것만 남긴 결과.

    `dropped` 는 본문에서 찾지 못해 버린 칸 이름이다. 비어 있는 것이 정상이고, 값이 있으면
    그 실행 기록에 남는다 — 모델이 무엇을 지어냈는지는 세어 봐야 알 수 있다.
    """

    fields: dict[str, str]
    dropped: list[str] = field(default_factory=list)


def loose(text: str) -> str:
    """비교용 모양. 공백·글머리표·구두점을 걷어내고 소문자로 맞춘다."""
    return _NOISE.sub("", text).lower()


def in_body(value: str, body: str) -> bool:
    """값의 모든 줄이 본문 안에 있는지. 빈 값은 볼 것이 없어 True 다."""
    return not missing_lines(value, body)


def missing_lines(value: str, body: str) -> list[str]:
    """본문에서 찾지 못한 줄. 빈 목록이면 그 값은 전부 본문에 있다."""
    haystack = loose(body)
    missing: list[str] = []
    for line in value.splitlines():
        needle = loose(line)
        if len(needle) < _MIN_LENGTH:
            continue
        if needle not in haystack:
            missing.append(line.strip())
    return missing


def ground(fields: Mapping[str, str], body: str) -> Grounded:
    """본문에 없는 값을 낸 칸을 버린다. 버린 칸 이름을 함께 돌려준다."""
    kept: dict[str, str] = {}
    dropped: list[str] = []
    for name, value in fields.items():
        if not value.strip():
            kept[name] = ""
            continue
        if missing_lines(value, body):
            kept[name] = ""
            dropped.append(name)
            continue
        kept[name] = value.strip()
    return Grounded(fields=kept, dropped=dropped)
