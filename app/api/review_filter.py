"""데이터 검수 화면의 조회 조건과 지우기.

한 화면(`/review`)이 좁혀서 보고, 고치고, 좁힌 것을 지운다. 이 파일은 그중 "무엇에 걸리는가"
와 "걸린 것을 지운다" 를 맡는다. 목록과 편집 모달은 `app/api/review.py` 다. 조건을 만드는
곳이 하나여야 표가 센 건수와 지우기가 지우는 행이 같다.

소비 측(채용공고 사이트)이 쓰는 제공 API(`/api/jobs`)와는 목적이 다르다 — 저쪽은 커서로
순서대로 받아 가는 경로고, 여기는 사람이 필터·검색·정렬로 들춰 보는 경로다. 그래서 이 화면은
제공 API 를 재사용하지 않는다.

## 지우는 것과 고치는 것이 한 화면에 있다

Push 30 이전에는 조회(`/jobs`)와 검수(`/review`)가 따로 있었고, 같은 데이터를 두 벌로
보여주면서 목록·상세 모달·시각 표시가 겹쳤다. 하나로 합치면서 지우기는 확인 모달 뒤에 두고,
고치기는 행의 `수정` 이 여는 모달 안에만 둔다. 표 안에서 값을 고치는 입구는 없다.

`delivered_at` 은 읽어서 보여주기만 한다. 지우는 경로도 그 값을 고치지 않는다 — 행이 통째로
사라질 뿐이다 (`.claude/rules/data-safety.md`).

## 조건은 화면에서 온 문자열로 조립하지 않는다

정렬 컬럼·방향·상태값·빈 값 필드는 이 파일이 가진 표에 있는 것만 받는다. 시각 범위는 운영자가
고른 날짜를 표시 시간대의 하루로 읽어 UTC 로 바꿔 넣는다 — 저장된 값이 UTC 라서, 날짜를
그대로 비교하면 자정 근처 9시간이 어긋난다.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.api import crawlers
from app.api.ui import display_zone, render
from app.normalize.engine import OVERRIDABLE_FIELDS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ui"], include_in_schema=False)

# 화면이 보낼 수 있는 정렬 기준. 값은 SQL 조각이라 표 밖의 값을 받지 않는다.
# 기준마다 컬럼을 여럿 둘 수 있고, 방향은 그 전부에 같이 걸린다 — 앞자리만 뒤집히면
# `미전달 먼저` 를 뒤집었을 때 뒷자리가 반대로 남는다
SORTS: dict[str, tuple[str, ...]] = {
    "review": ("(n.delivered_at IS NULL)", "r.crawled_at", "n.id"),
    "crawled_at": ("r.crawled_at", "n.id"),
    "normalized_at": ("n.normalized_at", "n.id"),
    "company": ("n.company", "n.id"),
    "title": ("n.title", "n.id"),
    "deadline": ("n.deadline", "n.id"),
}
SORT_LABELS: dict[str, str] = {
    "review": "검수 순서 (미전달 먼저)",
    "crawled_at": "수집 시각",
    "normalized_at": "정규화 시각",
    "company": "회사",
    "title": "제목",
    "deadline": "마감",
}
ORDERS: dict[str, str] = {"desc": "DESC", "asc": "ASC"}

# 기본 정렬은 미전달 우선이다. 이미 전달된 행을 고쳐도 소비 측이 가진 값은 바뀌지 않으므로
# (`app/api/review.py`), 검수는 전달 전에 하는 것이 정상 경로고 화면이 그 순서로 행을 내놓는다
DEFAULT_SORT = "review"

# 마감일로 가르는 진행 여부. 값은 화면이 보내는 것이고 문구는 화면에 그대로 적힌다
DEADLINE_STATES: dict[str, str] = {
    "open": "진행중",
    "closed": "마감 지남",
    "none": "마감일 없음",
}

# 전달 여부. `delivered_at` 이 찍혔는지만 본다
DELIVERY_STATES: dict[str, str] = {
    "yes": "전달됨",
    "no": "미전달",
}

# 사람이 고칠 수 있는 여섯 필드와 화면에 적을 이름. 키는 `OVERRIDABLE_FIELDS` 와 같아야 한다 —
# 그쪽이 `job_field_overrides.field_name` 의 CHECK 와 이미 맞춰져 있다.
# 지우기의 조건 설명도 이 이름을 쓰기 때문에 `app/api/review.py` 가 아니라 여기 둔다
FIELD_LABELS: dict[str, str] = {
    "company": "회사",
    "title": "제목",
    "department": "부서",
    "deadline": "마감",
    "body": "본문",
    "requirements": "자격요건",
    "start_date": "모집 시작",
    "job_category": "직군",
    "employment_type": "고용형태",
    "career_level": "경력 구분",
    "work_location": "근무지",
    "headcount": "모집인원",
    "duties": "주요 업무",
    "preferred": "우대 조건",
    "hiring_process": "전형 절차",
    "etc_info": "기타",
}

# `빈 값인 필드` 조건에서 "아무 필드나 하나라도 비었다" 를 가리키는 값
EMPTY_ANY = "any"
EMPTY_CHOICES: tuple[str, ...] = (EMPTY_ANY, *OVERRIDABLE_FIELDS)
EMPTY_LABELS: dict[str, str] = {EMPTY_ANY: "아무 필드나", **FIELD_LABELS}

# 빈 값과, 뜻이 있어서 빈 값은 다르다. 구분할 방법이 화면에 없는 필드는 그 사실을 적는다 —
# 마감이 빈 148건을 셀렉터가 놓친 것으로 읽고 셀렉터를 고치러 가는 일이 여기서 난다.
# 여기 없는 필드(회사·제목·본문)는 비어 있으면 놓친 것이다
EMPTY_NOTES: dict[str, str] = {
    "deadline": "상시채용이면 비어 있는 것이 맞다. 저장된 값만으로는 놓친 것과 구분되지 않는다",
    "department": "부서를 적지 않는 공고가 있다. 목록에 부서가 없는 사이트면 전부 빈다",
    "requirements": "본문에 자격요건이 섞여 있는 사이트면 늘 빈다. 그 사이트는 이것이 정상이다",
    # 0011 이 더한 열 칸. 사이트가 그 값을 나눠서 줄 때만 채워지고, 한 덩어리로 주는
    # 사이트에서는 전부 빈다 — 그때 빈 것은 놓친 것이 아니다
    # (`seeds/site-configs-20260826.json` 의 사이트별 note)
    "start_date": "모집 시작일을 적지 않는 사이트가 있다. 그런 사이트는 전부 빈다",
    "job_category": "직군을 따로 주지 않는 사이트면 늘 빈다",
    "employment_type": "정규직/인턴 구분을 따로 주는 사이트가 넷뿐이다. 나머지는 전부 빈다",
    "career_level": "신입/경력 구분을 따로 주는 사이트가 다섯뿐이다. 나머지는 전부 빈다",
    "work_location": "근무지를 따로 주지 않는 사이트면 늘 빈다",
    "headcount": "모집인원을 적지 않는 사이트가 많다. 그런 사이트는 전부 빈다",
    "duties": "본문에 주요 업무가 섞여 있는 사이트면 늘 빈다. 그 사이트는 이것이 정상이다",
    "preferred": "본문에 우대 조건이 섞여 있는 사이트면 늘 빈다. 그 사이트는 이것이 정상이다",
    "hiring_process": "전형 절차를 따로 주지 않는 사이트면 늘 빈다",
    "etc_info": "기타 안내가 없는 공고는 빈다",
}

# 지울 대상을 무엇으로 고른 것인지. "이 페이지의 20건" 과 "필터에 걸린 148건" 이 같은 단추
# 뒤에 숨어 있으면 운영자는 20건인 줄 알고 148건을 지운다. 범위는 이름을 갖고, 화면은 그
# 이름과 건수를 늘 함께 적는다
SCOPE_SELECTED = "selected"
SCOPE_FILTERED = "filtered"
SCOPE_WORKFLOW = "workflow"
SCOPES: tuple[str, ...] = (SCOPE_SELECTED, SCOPE_FILTERED, SCOPE_WORKFLOW)

# 범위를 사람이 읽는 한 줄로. 확인 창의 첫 줄이고 로그에도 같은 문장이 남는다.
# `{workflow}` 는 그 워크플로우의 번호와 이름으로 채워진다
SCOPE_LABELS: dict[str, str] = {
    SCOPE_SELECTED: "표에서 고른 공고",
    SCOPE_FILTERED: "지금 조회 조건에 걸린 전부",
    SCOPE_WORKFLOW: "워크플로우 {workflow} 가 모은 공고 전부",
}

# 표를 다시 부르라고 알리는 이벤트 이름. 지우고 나면 표에 없는 행이 남아 있다
TABLE_RELOAD_EVENT = "jobs-deleted"

# `IN (?, ?, ...)` 에 한 번에 넣을 id 수. SQLite 의 바인딩 개수 상한에 걸리지 않게 끊는다
_ID_CHUNK = 500


def _day_bounds(text: str, *, next_day: bool) -> str | None:
    """운영자가 고른 날짜를 저장된 형식(UTC)의 경계 문자열로.

    `crawled_at` 과 `normalized_at` 은 UTC 를 초까지 적은 문자열이고, 화면은 그것을 표시
    시간대로 바꿔 보여준다 (`app/api/ui.py`). 그래서 고른 날짜도 표시 시간대의 하루로 읽어야
    화면에 보이는 시각과 조건이 같은 것을 가리킨다. 날짜 문자열을 그대로 비교하면 자정 근처
    아홉 시간이 반대쪽 날에 걸린다.

    읽지 못하는 값이면 `None` 이다. 조건에서 빠질 뿐 화면이 422 로 죽지 않는다.
    """
    try:
        picked = date.fromisoformat(text.strip())
    except ValueError:
        return None
    if next_day:
        picked = picked + timedelta(days=1)
    start = datetime(picked.year, picked.month, picked.day, tzinfo=display_zone())
    return start.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    """진행 여부를 가르는 오늘. 마감일은 날짜라 표시 시간대의 오늘과 비교한다."""
    return datetime.now(display_zone()).date().isoformat()


@dataclass(frozen=True)
class JobFilter:
    """조회 조건 한 벌. 표와 지우기가 같은 조건을 본다.

    지우기가 "지금 필터에 걸린 것" 을 대상으로 하기 때문에, 조건을 만드는 곳이 하나여야 한다.
    표는 A 로 세고 지우기는 B 로 지우면 화면에 적힌 건수가 거짓이 된다.
    """

    workflow_id: int | None = None
    company: str = ""
    query: str = ""
    status: str = ""
    delivered: str = ""
    empty: str = ""
    crawled_from: str = ""
    crawled_to: str = ""
    normalized_from: str = ""
    normalized_to: str = ""

    def without_empty(self) -> JobFilter:
        """빈 값 조건만 뺀 같은 조건. 필드별 빈 건수를 세는 데 쓴다.

        건수는 조건을 걸기 전에 어디가 문제인지 보여주는 숫자다. 걸린 조건 안에서 세면
        `마감이 빈 것` 을 고른 순간 마감이 148건, 나머지가 0건이 되어 아무것도 말하지 않는다.
        """
        return replace(self, empty="")

    def as_form(self) -> dict[str, str]:
        """폼에 다시 실을 값. 지우기 요청이 표와 같은 조건을 들고 가게 한다."""
        return {
            "workflow_id": "" if self.workflow_id is None else str(self.workflow_id),
            "company": self.company,
            "q": self.query,
            "status": self.status,
            "delivered": self.delivered,
            "empty": self.empty,
            "crawled_from": self.crawled_from,
            "crawled_to": self.crawled_to,
            "normalized_from": self.normalized_from,
            "normalized_to": self.normalized_to,
        }


def read_filter(
    workflow_id: str = "",
    company: str = "",
    q: str = "",
    status: str = "",
    delivered: str = "",
    empty: str = "",
    crawled_from: str = "",
    crawled_to: str = "",
    normalized_from: str = "",
    normalized_to: str = "",
) -> JobFilter:
    """화면이 보낸 값을 조건 한 벌로. 표에 없는 값은 조건을 걸지 않은 것으로 본다.

    빈 문자열로 받는 이유는 "전체" 를 고르면 빈 값이 오기 때문이다. 정수·열거 파라미터로 두면
    그 빈 값이 422 가 되어 표가 갱신되지 않는다.
    """
    return JobFilter(
        workflow_id=int(workflow_id) if workflow_id.strip().isdigit() else None,
        company=company.strip(),
        query=q.strip(),
        status=status if status in DEADLINE_STATES else "",
        delivered=delivered if delivered in DELIVERY_STATES else "",
        empty=empty if empty in EMPTY_CHOICES else "",
        crawled_from=crawled_from.strip(),
        crawled_to=crawled_to.strip(),
        normalized_from=normalized_from.strip(),
        normalized_to=normalized_to.strip(),
    )


# 빈 값으로 볼 글자. 스페이스·탭·줄바꿈·캐리지리턴이다
_BLANK_CHARS = "' ' || char(9) || char(10) || char(13)"


def empty_condition(field: str) -> str:
    """그 필드가 "화면에 보이는 값 기준으로" 비어 있는지 판정하는 SQL 조각.

    규칙이 만든 값(`normalized_jobs` 컬럼)이 아니라 사람이 정한 값까지 얹은 뒤에 본다.
    보정으로 채워 넣은 필드가 계속 빈 것으로 걸리면 검수한 것이 검수 대상에 남고, 반대로
    사람이 일부러 비운 필드는 비어 있는 것이 맞다 (`migrations/0005_job_field_overrides.sql`).

    공백만 있는 값도 빈 것으로 본다. 셀렉터가 빈 태그를 잡으면 값은 `\n  ` 같은 것이 되는데,
    화면에서는 빈 칸과 구별되지 않는다. `TRIM` 에 지울 글자를 직접 준다 — 인자가 하나면
    SQLite 는 스페이스만 지우고, 줄바꿈만 남은 값이 빈 값이 아닌 것으로 세어진다.

    필드 이름은 이 파일의 `FIELD_LABELS` 에 있는 값만 들어온다 — 화면에서 온 문자열을 그대로
    SQL 에 넣지 않는다.
    """
    return (
        "TRIM(COALESCE((SELECT o.value FROM job_field_overrides o"
        f" WHERE o.raw_job_id = n.raw_job_id AND o.field_name = '{field}'),"
        f" n.{field}, ''), {_BLANK_CHARS}) = ''"
    )


def _empty_clause(picked: str) -> str:
    """빈 값 조건 하나. `아무 필드나` 는 여섯 조건을 OR 로 묶는다."""
    if picked == EMPTY_ANY:
        return "(" + " OR ".join(empty_condition(field) for field in OVERRIDABLE_FIELDS) + ")"
    return empty_condition(picked)


def filter_sql(picked: JobFilter) -> tuple[str, list[Any]]:
    """조건을 `WHERE` 한 줄로. `normalized_jobs n` 과 `raw_jobs r` 이 붙어 있는 것을 전제한다."""
    clauses: list[str] = []
    params: list[Any] = []
    if picked.workflow_id is not None:
        clauses.append("r.workflow_id = ?")
        params.append(picked.workflow_id)
    if picked.company:
        clauses.append("n.company = ?")
        params.append(picked.company)
    if picked.query:
        clauses.append("(n.title LIKE ? OR n.company LIKE ? OR n.department LIKE ?)")
        params.extend([f"%{picked.query}%"] * 3)

    # 마감일은 날짜 문자열이다. `date()` 가 NULL 을 내는 값(빈 값, 날짜가 아닌 값)은 진행중도
    # 마감도 아니라 `마감일 없음` 쪽에 모은다 — 그렇지 않으면 어느 조건에도 걸리지 않는 행이
    # 조용히 생긴다
    if picked.status == "open":
        clauses.append("date(n.deadline) >= ?")
        params.append(_today())
    elif picked.status == "closed":
        clauses.append("date(n.deadline) < ?")
        params.append(_today())
    elif picked.status == "none":
        clauses.append("date(n.deadline) IS NULL")

    # 표에 없는 값은 조건에서 뺀다. 화면에서 온 문자열이 SQL 로 들어가는 유일한 자리다
    if picked.empty and picked.empty in EMPTY_CHOICES:
        clauses.append(_empty_clause(picked.empty))

    if picked.delivered == "yes":
        clauses.append("n.delivered_at IS NOT NULL")
    elif picked.delivered == "no":
        clauses.append("n.delivered_at IS NULL")

    for column, start, end in (
        ("r.crawled_at", picked.crawled_from, picked.crawled_to),
        ("n.normalized_at", picked.normalized_from, picked.normalized_to),
    ):
        lower = _day_bounds(start, next_day=False)
        if lower is not None:
            clauses.append(f"{column} >= ?")
            params.append(lower)
        # 끝나는 날은 그날을 포함한다. 다음 날 0시 앞까지로 잡는다
        upper = _day_bounds(end, next_day=True)
        if upper is not None:
            clauses.append(f"{column} < ?")
            params.append(upper)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def _count(conn: sqlite3.Connection, where: str, params: list[Any]) -> int:
    """조건에 걸린 정규화 행 수. 표의 머리글도 지우기의 확인 창도 이 수를 쓴다."""
    row = conn.execute(
        f"SELECT count(*) AS total FROM normalized_jobs n"
        f" JOIN raw_jobs r ON r.id = n.raw_job_id{where}",
        params,
    ).fetchone()
    return int(row["total"]) if row is not None else 0


def count(conn: sqlite3.Connection, picked: JobFilter) -> int:
    """조건에 걸린 정규화 행 수. 표도 지우기도 이 함수를 쓴다."""
    where, params = filter_sql(picked)
    return _count(conn, where, params)


def order_clause(sort: str, order: str) -> str:
    """정렬 한 줄. 표 밖의 값이 오면 기본 정렬로 되돌린다."""
    columns = SORTS.get(sort) or SORTS[DEFAULT_SORT]
    direction = ORDERS.get(order, "DESC")
    return " ORDER BY " + ", ".join(f"{column} {direction}" for column in columns)


def empty_counts(conn: sqlite3.Connection, picked: JobFilter) -> list[dict[str, Any]]:
    """지금 조건에 걸린 행 중 필드마다 몇 건이 비었는지.

    빈 값 조건 자체는 빼고 센다 (`JobFilter.without_empty`). 조건을 걸기 전에 어디가 문제인지
    보여주는 숫자라서, 걸린 조건 안에서 세면 방금 고른 필드만 보이고 나머지가 0이 된다.

    필드마다 "비어 있는 것이 정상일 수 있는가" 를 함께 낸다. 마감이 빈 것은 상시채용일 수
    있고, 그것을 셀렉터가 놓친 것으로 읽으면 멀쩡한 셀렉터를 고치게 된다.
    """
    where, params = filter_sql(picked.without_empty())
    picks = ", ".join(
        f"SUM(CASE WHEN {empty_condition(field)} THEN 1 ELSE 0 END) AS {field}"
        for field in OVERRIDABLE_FIELDS
    )
    row = conn.execute(
        f"SELECT count(*) AS total, {picks},"
        f" SUM(CASE WHEN {_empty_clause(EMPTY_ANY)} THEN 1 ELSE 0 END) AS any_empty"
        f"  FROM normalized_jobs n JOIN raw_jobs r ON r.id = n.raw_job_id{where}",
        params,
    ).fetchone()

    def counted(name: str) -> int:
        value = row[name] if row is not None else None
        return int(value) if value is not None else 0

    found = [
        {
            "field": field,
            "label": FIELD_LABELS[field],
            "count": counted(field),
            "note": EMPTY_NOTES.get(field, ""),
            # 색이 아니라 낱말이 판정이다 (`.claude/rules/writing.md`)
            "normal": "있을 수 있음" if field in EMPTY_NOTES else "아니오",
        }
        for field in OVERRIDABLE_FIELDS
    ]
    found.append(
        {
            "field": EMPTY_ANY,
            "label": EMPTY_LABELS[EMPTY_ANY],
            "count": counted("any_empty"),
            "note": "여섯 필드 중 하나라도 빈 공고",
            "normal": "",
        }
    )
    return found


def _chunks(ids: Sequence[int]) -> Iterator[tuple[list[int], str]]:
    """id 목록을 바인딩 가능한 크기로 끊는다. 묶음마다 물음표 자리도 함께 낸다."""
    for start in range(0, len(ids), _ID_CHUNK):
        part = list(ids[start : start + _ID_CHUNK])
        yield part, ",".join("?" for _ in part)


def _existing_ids(conn: sqlite3.Connection, ids: Sequence[int]) -> tuple[int, ...]:
    """받은 id 중 지금도 `raw_jobs` 에 있는 것. 이미 사라진 id 는 그 자리에서 떨어뜨린다."""
    wanted = list(dict.fromkeys(int(value) for value in ids))
    found: list[int] = []
    for part, marks in _chunks(wanted):
        found.extend(
            int(row["id"])
            for row in conn.execute(
                f"SELECT id FROM raw_jobs WHERE id IN ({marks})", part
            ).fetchall()
        )
    return tuple(sorted(found))


def _count_ids(conn: sqlite3.Connection, sql: str, ids: Sequence[int]) -> int:
    """id 묶음에 걸리는 행 수. 묶음을 끊어 세고 더한다."""
    total = 0
    for part, marks in _chunks(ids):
        row = conn.execute(sql.format(marks=marks), part).fetchone()
        total += int(row[0]) if row is not None else 0
    return total


def workflow_label(conn: sqlite3.Connection, workflow_id: int | None) -> str:
    """워크플로우를 번호와 이름으로. 고르지 않았으면 빈 문자열이다."""
    if workflow_id is None:
        return ""
    found = conn.execute("SELECT name FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
    return f"{workflow_id} - {found['name']}" if found else str(workflow_id)


def _describe(conn: sqlite3.Connection, picked: JobFilter, scope: str) -> str:
    """지우는 데 실제로 걸린 조건을 한 줄로. 비어 있는 조건도 `전체` 라고 적는다.

    확인 창에 적히고 로그에도 같은 문장이 남는다. 무엇을 지웠는지 나중에 묻는 사람은 건수가
    아니라 이 줄을 본다.

    워크플로우 범위는 나머지 조건을 보지 않으므로 그 조건들을 적지 않는다. 걸리지도 않는
    `회사 D&D Property Solution` 이 지우기 건수 바로 옆에 적혀 있으면, 그 회사 것만 지워지는
    줄로 읽힌다.
    """
    workflow = workflow_label(conn, picked.workflow_id) or "전체"
    if scope == SCOPE_WORKFLOW:
        return f"워크플로우 {workflow} · 나머지 조건은 걸리지 않는다"

    def span(start: str, end: str) -> str:
        if not start and not end:
            return "전체"
        return f"{start or '처음'} ~ {end or '지금'}"

    return " · ".join(
        (
            f"워크플로우 {workflow}",
            f"회사 {picked.company or '전체'}",
            f"진행 여부 {DEADLINE_STATES.get(picked.status, '전체')}",
            f"전달 여부 {DELIVERY_STATES.get(picked.delivered, '전체')}",
            f"빈 값 {EMPTY_LABELS.get(picked.empty, '안 걸림')}",
            f"수집 {span(picked.crawled_from, picked.crawled_to)}",
            f"정규화 {span(picked.normalized_from, picked.normalized_to)}",
            f"검색어 {picked.query or '없음'}",
        )
    )


@dataclass(frozen=True)
class DeleteTarget:
    """지울 대상 한 묶음. 세 표에서 각각 몇 행이 사라지는지까지 들고 있다.

    건수를 화면이 아니라 서버가 낸다. 확인 창이 보여준 숫자와 실제로 지워지는 행이 다르면,
    `raw_jobs` 는 다시 만들 수 없으므로 되돌릴 방법이 없다.
    """

    scope: str
    label: str
    criteria: str
    picked: JobFilter
    raw_job_ids: tuple[int, ...]
    normalized: int
    overrides: int
    delivered: int

    @property
    def raw(self) -> int:
        return len(self.raw_job_ids)


def _build_target(
    conn: sqlite3.Connection,
    *,
    scope: str,
    ids: Sequence[int],
    picked: JobFilter,
    resolve: bool = True,
) -> DeleteTarget:
    """범위를 실제 `raw_jobs.id` 목록으로 바꾸고, 세 표에서 사라질 행을 센다.

    `resolve` 를 끄면 범위를 다시 풀지 않고 받은 id 만 쓴다. 확인 창을 지나온 요청이 그렇다 —
    확인 창이 148건이라고 적었는데 그 사이 크롤이 한 번 더 돌아 160건을 지우면, `raw_jobs` 는
    다시 만들 수 없으므로 되돌릴 방법이 없다. 지우는 것은 사람이 보고 승낙한 그 목록이다.
    """
    if resolve and scope == SCOPE_FILTERED:
        where, params = filter_sql(picked)
        rows = conn.execute(
            f"SELECT DISTINCT r.id AS id FROM normalized_jobs n"
            f" JOIN raw_jobs r ON r.id = n.raw_job_id{where} ORDER BY r.id",
            params,
        ).fetchall()
        raw_job_ids = tuple(int(row["id"]) for row in rows)
    elif resolve and scope == SCOPE_WORKFLOW:
        # 그 워크플로우가 모은 전부다. 나머지 조회 조건은 걸지 않는다 — 한 사이트의 수집분을
        # 통째로 비우는 자리고, 조건이 섞이면 무엇이 남는지 화면에서 알 수 없다.
        # `raw_jobs` 에서 바로 고른다. 표는 정규화된 것만 보여주는데, 정규화되지 않은 수집 건을
        # 남겨 두면 다음 재정규화에서 지운 공고가 되살아난다
        rows = conn.execute(
            "SELECT id FROM raw_jobs WHERE workflow_id = ? ORDER BY id", (picked.workflow_id,)
        ).fetchall()
        raw_job_ids = tuple(int(row["id"]) for row in rows)
    else:
        raw_job_ids = _existing_ids(conn, ids)

    return DeleteTarget(
        scope=scope,
        label=SCOPE_LABELS[scope].format(
            workflow=workflow_label(conn, picked.workflow_id) or "고르지 않음"
        ),
        criteria=_describe(conn, picked, scope),
        picked=picked,
        raw_job_ids=raw_job_ids,
        normalized=_count_ids(
            conn,
            "SELECT count(*) FROM normalized_jobs WHERE raw_job_id IN ({marks})",
            raw_job_ids,
        ),
        overrides=_count_ids(
            conn,
            "SELECT count(*) FROM job_field_overrides WHERE raw_job_id IN ({marks})",
            raw_job_ids,
        ),
        delivered=_count_ids(
            conn,
            "SELECT count(*) FROM normalized_jobs"
            " WHERE delivered_at IS NOT NULL AND raw_job_id IN ({marks})",
            raw_job_ids,
        ),
    )


def _form_ids(values: Sequence[Any]) -> list[int]:
    """체크박스가 보낸 id. 숫자가 아닌 값은 버린다."""
    found: list[int] = []
    for value in values:
        text = str(value).strip()
        if text.isdigit():
            found.append(int(text))
    return found


async def _delete_request(request: Request) -> tuple[str, list[int], JobFilter]:
    """지우기 폼 한 벌. 확인 창과 실제 삭제가 같은 폼을 읽는다."""
    form = await request.form()
    scope = str(form.get("scope") or "").strip()
    if scope not in SCOPES:
        # 범위를 따로 싣지 않으면 `필터 전체` 체크박스가 정한다
        scope = SCOPE_FILTERED if form.get("all_filtered") else SCOPE_SELECTED
    picked = read_filter(
        **{
            name: str(form.get(name) or "")
            for name in (
                "workflow_id",
                "company",
                "q",
                "status",
                "delivered",
                "empty",
                "crawled_from",
                "crawled_to",
                "normalized_from",
                "normalized_to",
            )
        }
    )
    return scope, _form_ids(form.getlist("raw_job_id")), picked


def _delete_rows(conn: sqlite3.Connection, raw_job_ids: Sequence[int]) -> tuple[int, int, int]:
    """세 표를 한 트랜잭션으로, 외래키 순서대로 비운다.

    `job_field_overrides` -> `normalized_jobs` -> `raw_jobs` 순이다. 거꾸로 지우면 외래키가
    막고, 막히지 않는다면 그것대로 문제다 — 가리키는 곳이 없는 보정이 남는다.

    한 트랜잭션인 이유는 절반만 지워진 상태를 운영자가 손으로 풀 수 없어서다. 정규화 행만
    사라지고 수집 건이 남으면 그 건은 어느 화면에도 나오지 않는데 표에는 있다.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        overrides = normalized = raw = 0
        for part, marks in _chunks(raw_job_ids):
            overrides += conn.execute(
                f"DELETE FROM job_field_overrides WHERE raw_job_id IN ({marks})", part
            ).rowcount
            normalized += conn.execute(
                f"DELETE FROM normalized_jobs WHERE raw_job_id IN ({marks})", part
            ).rowcount
            raw += conn.execute(f"DELETE FROM raw_jobs WHERE id IN ({marks})", part).rowcount
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return raw, normalized, overrides


@router.post("/ui/review/delete/confirm", response_class=HTMLResponse)
async def job_delete_confirm_fragment(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(crawlers.get_connection)],
) -> HTMLResponse:
    """지우기 전에 무엇이 몇 건 사라지는지 보여주는 모달.

    브라우저 `confirm()` 을 쓰지 않는다. 저장소의 다른 확인과 같은 `<dialog>` 다 — 여기에
    적어야 하는 것이 한 줄로 끝나지 않아서다. 세 표에서 각각 몇 행이 사라지는지, 그중 이미
    전달된 것이 몇 건인지, 되돌릴 수 없다는 것까지 들어간다.

    GET 이 아니라 POST 로 받는다. 고른 id 가 백 개를 넘으면 주소에 실을 수 없다.
    """
    scope, ids, picked = await _delete_request(request)
    target = _build_target(conn, scope=scope, ids=ids, picked=picked)
    return render(request, "fragments/review_delete.html", target=target, done=None)


@router.post("/ui/review/delete", response_class=HTMLResponse)
async def job_delete_fragment(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(crawlers.get_connection)],
) -> HTMLResponse:
    """확인 창이 보여준 그 목록을 지운다.

    범위를 여기서 다시 풀지 않는다. 확인 창이 실어 보낸 id 만 지운다 — 그래야 사람이 보고
    승낙한 숫자와 사라진 행이 같다.

    모달은 닫지 않고 결과를 그 자리에 적는다. 되돌릴 수 없는 일이라 몇 건이 지워졌는지가
    화면에 남아야 한다. 표는 `jobs-deleted` 를 받아 스스로 다시 그린다.
    """
    scope, ids, picked = await _delete_request(request)
    target = _build_target(conn, scope=scope, ids=ids, picked=picked, resolve=False)
    if target.raw == 0:
        return render(request, "fragments/review_delete.html", target=target, done=None)

    raw, normalized, overrides = _delete_rows(conn, target.raw_job_ids)
    # 요청자를 남긴다. 계정이 없는 단일 운영자라 남길 수 있는 것은 어디서 왔는지뿐이다
    # (`app/api/auth.py`). 되돌릴 수 없는 일이라 이 줄이 유일한 기록이다
    client = request.client.host if request.client is not None else "알 수 없음"
    logger.info(
        "검수 화면에서 공고를 지웠다: 범위=%s(%s), 조건=%s,"
        " raw_jobs=%d, normalized_jobs=%d, job_field_overrides=%d, 전달됐던 행=%d, 요청=%s",
        target.scope,
        target.label,
        target.criteria,
        raw,
        normalized,
        overrides,
        target.delivered,
        client,
    )
    done = DeleteTarget(
        scope=target.scope,
        label=target.label,
        criteria=target.criteria,
        picked=picked,
        raw_job_ids=target.raw_job_ids[:raw],
        normalized=normalized,
        overrides=overrides,
        delivered=target.delivered,
    )
    response = render(request, "fragments/review_delete.html", target=target, done=done)
    # 설정(settle) 뒤에 표를 다시 부른다. 모달은 열어 둔 채다
    response.headers["HX-Trigger-After-Settle"] = TABLE_RELOAD_EVENT
    return response
