"""알림 하나의 제목과 본문을 만든다.

**한 실행에 알림 하나다.** 공고마다 보내지 않는다 — SK 는 한 번에 104건이 들어오고, 그러면
알림이 104개 온다 (`.claude/tasks/todo/tasks-ntfy-notify.md`).

같은 이유로 본문에 104건을 다 넣지 않는다. 앞의 몇 건만 보이고 나머지는 `외 N건` 으로 줄인다.
다 넣은 알림은 읽히지 않고, 읽히지 않는 알림은 안 보낸 것과 같다.

본문은 마크다운이다. 문장에는 그림문자를 넣지 않는다 (`.claude/rules/writing.md`).
상태를 한눈에 보이게 하는 것은 ntfy 태그 쪽이다 (`app/notify/ntfy.py`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.notify.ntfy import NtfyMessage

# 본문에 이름을 적는 공고 수. 나머지는 `외 N건` 이 된다.
# 휴대폰 알림 하나가 펼치지 않고 보여주는 줄 수를 넘지 않는 선이다
PREVIEW_LIMIT = 5

# 제목 한 줄의 상한. 긴 공고 제목 하나가 알림 전체를 밀어내지 않게 한다
TITLE_LIMIT = 60

# 새 공고 알림에 붙는 태그. ntfy 의 이모지 단축이름이다
NEW_JOBS_TAGS: tuple[str, ...] = ("briefcase",)

# 값이 비어 있을 때 그 자리에 적는 말. 빈 줄로 두면 공고가 없는 것으로 읽힌다
_UNTITLED = "제목 없음"


@dataclass(frozen=True)
class NewJob:
    """알림에 한 줄로 들어가는 공고. 이름을 적는 데 필요한 두 값만 든다."""

    company: str
    title: str


def build_new_jobs_message(
    *,
    site_name: str,
    jobs: Sequence[NewJob],
    click: str = "",
) -> NtfyMessage:
    """새 공고 알림 하나. `jobs` 는 이번 실행이 적재한 공고 전부다.

    건수는 `jobs` 의 길이에서 나온다. 건수를 따로 받으면 목록과 숫자가 어긋난 알림이
    나갈 수 있고, 그때 어느 쪽이 맞는지 알 방법이 없다.

    `click` 이 비어 있으면 누를 곳 없는 알림이 된다. 운영 화면 주소를 아직 적지 않은
    상태이고, 알림 자체는 그대로 나간다.
    """
    total = len(jobs)
    return NtfyMessage(
        title=f"{site_name} 새 공고 {total}건",
        body=_body(jobs),
        tags=NEW_JOBS_TAGS,
        click=click,
    )


def _body(jobs: Sequence[NewJob]) -> str:
    """앞의 몇 건은 이름으로, 나머지는 숫자로.

    `외 N건` 은 목록과 빈 줄로 떨어뜨린다. 붙여 두면 마크다운이 마지막 항목의 이어지는
    글로 읽어 목록 안에 들어가 버린다.
    """
    if not jobs:
        # 부르는 쪽이 0건에는 보내지 않는다 (`app/notify/new_jobs.py`). 그래도 여기서
        # 빈 문자열을 내면 본문 없는 알림이 되므로 사실을 적는다
        return "새 공고가 없다"

    lines = [f"- {_line(job)}" for job in jobs[:PREVIEW_LIMIT]]
    remaining = len(jobs) - PREVIEW_LIMIT
    if remaining > 0:
        lines.append("")
        lines.append(f"외 {remaining}건")
    return "\n".join(lines)


def _line(job: NewJob) -> str:
    """공고 한 줄. 회사가 있으면 굵게 앞세우고, 없으면 제목만 적는다."""
    title = _clip(job.title.strip()) or _UNTITLED
    company = job.company.strip()
    if not company:
        return title
    return f"**{_clip(company)}** {title}"


def _clip(text: str) -> str:
    """상한을 넘는 글자는 자른다. 잘렸다는 사실이 보이게 뒤에 표시를 남긴다."""
    if len(text) <= TITLE_LIMIT:
        return text
    return text[:TITLE_LIMIT] + "..."
