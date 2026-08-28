"""받은 값에 원문의 근거가 있는지 그 자리에서 본다.

`.claude/rules/llm.md` 는 모델이 낸 것을 그 자리에서 돌려 보라고 한다. 셀렉터는 HTML 에
돌려 보면 되지만 분류에는 돌릴 것이 없다 — 대신 **원문에 근거가 있는지** 를 본다.

근거가 없는 칸은 버린다. 지어낸 값은 소비 측이 그대로 사실로 노출하고, 빈 칸보다 나쁘다
(`.claude/tasks/memos/보류/llm-classify/prd-llm-classify.md`).

## 돌려 보는 원문은 제목과 본문이다

본문만이었다. 직무가 들어오면서 제목이 더해졌다 — `job_role` 은 제목에서 옮기는 값이라
본문에만 돌려 보면 **맞게 뽑은 값이 통째로 버려진다.** 2026-08-28 에 열한 사이트 픽스처로
쟀더니 제목이 직무를 말하는 곳 아홉 중 본문이 같은 글자를 되풀이하는 곳은 셋뿐이었고, 나머지
여섯이 전부 버려졌다 (`tests/test_job_role_source.py`).

칸마다 볼 곳을 가르지 않고 **한 덩어리로 본다.** 가르면 칸이 늘 때마다 어느 칸을 어디에 돌려
보는지가 늘고, 그 표가 프롬프트의 칸 설명과 갈린다. 대신 제목 한 줄이 넓어진 만큼 느슨해진다
— 제목을 그대로 옮겨 적은 한 줄짜리 값이 다른 칸에서도 살아남는다. 프롬프트가 제목을
`job_role` 말고 어느 칸에도 넣지 말라고 적는 자리가 거기다 (`app/classify/classifier.py`).

## 칸에 따라 근거가 다르다

**뽑는 칸**은 값 자체가 원문에 있어야 한다. 원문 글자를 그대로 옮기는 칸이라 그렇다.

**판정하는 칸**은 값이 원문에 글자로 있을 필요가 없다. `백엔드 개발자 채용` 어디에도
"개발·IT" 라고 적혀 있지 않다. 대신 둘을 본다 — 고른 값이 **닫힌 목록 안**인지, 그리고
모델이 함께 낸 **근거 문장이 원문에 있는지.** 근거 문장이 없으면 읽고 고른 것이 아니라
지어낸 것이다. 제목이 근거일 수 있다 — `[채용연계형 인턴]` 은 고용형태의 근거이고, 그것을
버릴 이유가 없다.

## 무엇을 같다고 보는가

비교 전에 양쪽에서 공백과 글머리표·구두점을 걷어내고 소문자로 맞춘다. 원문은 줄바꿈과
글머리표가 사이트마다 다르고, 같은 문장을 옮겨 적기만 해도 `- ` 가 `• ` 로 바뀐다. 거기서
어긋난 것을 지어냈다고 하면 멀쩡한 값이 통째로 버려진다.

**느슨한 것은 비교뿐이고 판정은 엄격하다.** 값이 여러 줄이면 줄마다 따로 보고, 한 줄이라도
원문에서 찾지 못하면 그 칸을 통째로 버린다. 절반만 사실인 값은 읽는 쪽이 어디까지 믿어야
할지 알 수 없다.

글자를 걷어낸 뒤 남는 것이 한 글자 이하인 줄은 세지 않는다. `-` 하나짜리 줄이나 `1.` 같은
번호는 원문 어디에나 있어서 검사가 되지 않는다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.classify.schema import EXTRACT_FIELDS, JUDGE_CHOICES, JUDGE_FIELDS, UNDECIDED

# 비교에서 지우는 글자. 공백, 글머리표, 구두점, 괄호, 따옴표다. 뜻을 나르는 글자는 남는다
_NOISE = re.compile(r"[\s·•·◦○●□■▪▶▷–—\-*_.,;:!?()\[\]{}<>\"'`~/\\|]+")

# 이보다 짧아지는 줄은 검사 대상이 아니다
_MIN_LENGTH = 2


# 버린 이유. 셋을 가르는 것은 고칠 자리가 다르기 때문이다 — 앞은 프롬프트의 "그대로 옮겨라"
# 가 안 먹은 것이고, 가운데는 목록이 좁은 것이고, 뒤는 읽지 않고 고른 것이다.
#
# 앞의 문장이 "본문에 없다" 였다. 검사가 제목까지 보게 되어 바꿨다 — 어디를 봐야 하는지
# 틀리게 적으면 운영자가 본문만 들여다보다 값이 제목에서 온 것을 놓친다
NOT_IN_SOURCE = "제목에도 본문에도 없다"
NOT_IN_LIST = "목록 밖이다"
NO_EVIDENCE = "근거 문장이 제목에도 본문에도 없다"


@dataclass(frozen=True)
class Grounded:
    """근거가 있는 것만 남긴 결과.

    `dropped` 는 버린 칸 이름이고 `reasons` 는 그 이유다. 비어 있는 것이 정상이고, 값이
    있으면 실행 기록에 남는다 — 모델이 무엇을 지어냈는지는 세어 봐야 알 수 있다.

    `evidence` 는 살아남은 판정 칸의 근거 문장이다. 사람이 그 판정을 읽고 검사할 수 있는
    유일한 자리라 결과에 같이 싣는다.
    """

    fields: dict[str, str]
    evidence: dict[str, str] = field(default_factory=dict)
    dropped: list[str] = field(default_factory=list)
    reasons: dict[str, str] = field(default_factory=dict)


def loose(text: str) -> str:
    """비교용 모양. 공백·글머리표·구두점을 걷어내고 소문자로 맞춘다."""
    return _NOISE.sub("", text).lower()


def in_body(value: str, body: str) -> bool:
    """값의 모든 줄이 그 글 안에 있는지. 빈 값은 볼 것이 없어 True 다."""
    return not missing_lines(value, body)


def missing_lines(value: str, body: str) -> list[str]:
    """그 글에서 찾지 못한 줄. 빈 목록이면 그 값은 전부 안에 있다."""
    haystack = loose(body)
    missing: list[str] = []
    for line in value.splitlines():
        needle = loose(line)
        if len(needle) < _MIN_LENGTH:
            continue
        if needle not in haystack:
            missing.append(line.strip())
    return missing


def ground(fields: Mapping[str, str], body: str, title: str = "") -> Grounded:
    """근거가 없는 칸을 버린다. 버린 칸 이름과 이유를 함께 돌려준다.

    받는 것은 응답 전체(뽑는 칸 일곱, 판정 칸 둘, 근거 문장 둘)이고, 돌려주는 `fields` 는
    `normalized_jobs` 로 갈 아홉 칸이다. 근거 문장은 컬럼이 아니라 `evidence` 로 따로 나간다.

    `title` 을 주지 않으면 본문만 본다. 그것이 옛 동작이고, `job_role` 만 그 상태에서 거의
    전부 버려진다 — 부르는 쪽은 제목을 같이 넘긴다 (`app/classify/classifier.py`).
    """
    # 돌려 보는 원문. 제목과 본문을 한 덩어리로 본다
    source = f"{title}\n{body}"
    kept: dict[str, str] = {}
    dropped: list[str] = []
    reasons: dict[str, str] = {}
    evidence: dict[str, str] = {}

    for name in EXTRACT_FIELDS:
        value = fields.get(name, "").strip()
        if not value:
            kept[name] = ""
            continue
        if missing_lines(value, source):
            kept[name] = ""
            dropped.append(name)
            reasons[name] = NOT_IN_SOURCE
            continue
        kept[name] = value

    for name in JUDGE_FIELDS:
        value = fields.get(name, "").strip()
        if not value or value == UNDECIDED:
            # 고르지 않았다는 답이다. 버린 것이 아니라 본문에 근거가 없다는 뜻이라 세지 않는다
            kept[name] = ""
            continue
        if value not in JUDGE_CHOICES[name]:
            # 스키마의 enum 이 이미 막지만, 스키마를 통과하지 않는 경로(손으로 넣은 응답,
            # 모델이 enum 을 무시한 경우)가 남아 있다. 목록 밖 값이 한 번 들어오면 그
            # 칸으로 거르는 소비 측이 조용히 그 건을 놓친다
            kept[name] = ""
            dropped.append(name)
            reasons[name] = NOT_IN_LIST
            continue
        quote = fields.get(f"{name}_evidence", "").strip()
        if not quote or missing_lines(quote, source):
            # 읽고 고른 것이 아니라 지어낸 것이다
            kept[name] = ""
            dropped.append(name)
            reasons[name] = NO_EVIDENCE
            continue
        kept[name] = value
        evidence[name] = quote

    return Grounded(fields=kept, evidence=evidence, dropped=dropped, reasons=reasons)
