"""수집 공고 조회 화면의 조각 라우트.

운영자가 "실제로 뭐가 들어왔나" 를 보는 화면이다. 소비 측(채용공고 사이트)이 쓰는 제공 API 와는
목적이 다르다 — 저쪽은 커서로 순서대로 받아 가는 경로고, 여기는 사람이 필터·검색·정렬로 들춰
보는 경로다. 그래서 이 조회는 제공 API 를 재사용하지 않는다.

## 값은 고치지 않는다

이 화면은 좁혀서 보고, 좁힌 것을 지운다. 값을 고치는 것은 검수 화면(`app/api/review.py`)의
일이다. 한 화면이 고치기와 지우기를 같이 들고 있으면 체크박스 옆에서 값을 고치게 되고, 고치려다
지우는 사고가 그 자리에서 난다.

`delivered_at` 은 읽어서 보여주기만 한다. 지우는 경로도 그 값을 고치지 않는다 — 행이 통째로
사라질 뿐이다 (`.claude/rules/data-safety.md`).

## 조건은 화면에서 온 문자열로 조립하지 않는다

정렬 컬럼·방향·상태값은 이 파일이 가진 표에 있는 것만 받는다. 시각 범위는 운영자가 고른 날짜를
표시 시간대의 하루로 읽어 UTC 로 바꿔 넣는다 — 저장된 값이 UTC 라서, 날짜를 그대로 비교하면
자정 근처 9시간이 어긋난다.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.api import crawlers
from app.api.ui import display_zone, render

router = APIRouter(tags=["ui"], include_in_schema=False)

# 화면이 보낼 수 있는 정렬 기준. 값은 SQL 조각이라 표 밖의 값을 받지 않는다
SORTS: dict[str, str] = {
    "normalized_at": "n.normalized_at",
    "company": "n.company",
    "title": "n.title",
    "deadline": "n.deadline",
}
ORDERS: dict[str, str] = {"desc": "DESC", "asc": "ASC"}

# 한 번에 보여줄 최대 행 수. 운영자 화면이라 페이지네이션 대신 상한 하나로 둔다
ROW_LIMIT = 100

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

_BASE = """
    SELECT n.id             AS id,
           n.company         AS company,
           n.company_source  AS company_source,
           n.title           AS title,
           n.department      AS department,
           n.deadline        AS deadline,
           n.source_url      AS source_url,
           n.normalized_at   AS normalized_at,
           n.delivered_at    AS delivered_at,
           r.workflow_id     AS workflow_id,
           w.name            AS workflow_name
      FROM normalized_jobs n
      JOIN raw_jobs r ON r.id = n.raw_job_id
      JOIN workflows w ON w.id = r.workflow_id
"""


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
    crawled_from: str = ""
    crawled_to: str = ""
    normalized_from: str = ""
    normalized_to: str = ""

    def as_form(self) -> dict[str, str]:
        """폼에 다시 실을 값. 지우기 요청이 표와 같은 조건을 들고 가게 한다."""
        return {
            "workflow_id": "" if self.workflow_id is None else str(self.workflow_id),
            "company": self.company,
            "q": self.query,
            "status": self.status,
            "delivered": self.delivered,
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
        crawled_from=crawled_from.strip(),
        crawled_to=crawled_to.strip(),
        normalized_from=normalized_from.strip(),
        normalized_to=normalized_to.strip(),
    )


def _filters(picked: JobFilter) -> tuple[str, list[Any]]:
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


@router.get("/ui/jobs", response_class=HTMLResponse)
def job_table_fragment(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(crawlers.get_connection)],
    picked: Annotated[JobFilter, Depends(read_filter)],
    sort: str = "normalized_at",
    order: str = "desc",
) -> HTMLResponse:
    """필터·검색·정렬 결과. 표 영역만 이 조각으로 갈린다.

    걸린 수(`total`)와 보여준 수(`shown`)를 따로 낸다. 상한이 100건이라 둘이 다를 수 있고,
    지우기가 그 차이를 반드시 글자로 갈라 적어야 한다 — 화면에 보이는 100건인 줄 알고 148건을
    지우는 것이 이 화면에서 제일 다치기 쉬운 자리다.
    """
    column = SORTS.get(sort, SORTS["normalized_at"])
    direction = ORDERS.get(order, "DESC")
    where, params = _filters(picked)

    rows = conn.execute(
        f"{_BASE}{where} ORDER BY {column} {direction}, n.id {direction} LIMIT ?",
        [*params, ROW_LIMIT],
    ).fetchall()

    return render(
        request,
        "fragments/job_table.html",
        jobs=rows,
        total=_count(conn, where, params),
        shown=len(rows),
        row_limit=ROW_LIMIT,
        criteria=picked.as_form(),
    )


@router.get("/ui/jobs/filters", response_class=HTMLResponse)
def job_filters_fragment(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(crawlers.get_connection)],
) -> HTMLResponse:
    """필터에 넣을 선택지. 워크플로우와 회사는 지금 저장된 값에서 만든다."""
    workflows = conn.execute("SELECT id, name FROM workflows ORDER BY id").fetchall()
    companies = conn.execute(
        """
        SELECT DISTINCT company FROM normalized_jobs
         WHERE company IS NOT NULL AND company <> ''
         ORDER BY company
        """
    ).fetchall()
    return render(
        request,
        "fragments/job_filters.html",
        workflows=workflows,
        companies=[row["company"] for row in companies],
        sorts=SORTS,
        deadline_states=DEADLINE_STATES,
        delivery_states=DELIVERY_STATES,
    )


@router.get("/ui/jobs/{job_id}", response_class=HTMLResponse)
def job_detail_fragment(
    request: Request,
    job_id: int,
    conn: Annotated[sqlite3.Connection, Depends(crawlers.get_connection)],
) -> HTMLResponse:
    """공고 한 건. 모달 안을 채우는 조각이고, 원문 링크는 수집한 값 그대로다.

    읽기만 한다. 이 화면에서 값을 고치는 경로는 두지 않는다 — 고치는 것은 검수 화면의 일이다.
    """
    row = conn.execute(
        f"{_BASE} WHERE n.id = ?",
        (job_id,),
    ).fetchone()
    if row is None:
        return render(request, "fragments/job_detail.html", job=None, raw=None, job_id=job_id)

    body = conn.execute(
        """
        SELECT n.body AS body, n.requirements AS requirements, n.raw_job_id AS raw_job_id,
               r.crawled_at AS crawled_at, r.content_hash AS content_hash
          FROM normalized_jobs n
          JOIN raw_jobs r ON r.id = n.raw_job_id
         WHERE n.id = ?
        """,
        (job_id,),
    ).fetchone()
    return render(request, "fragments/job_detail.html", job=row, raw=body, job_id=job_id)
