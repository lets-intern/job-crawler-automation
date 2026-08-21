"""데이터 검수 화면의 페이지·조각 라우트.

사람이 수집 결과를 한 건씩 보고 틀린 값을 고치는 자리다. 조회 화면(`app/api/ui_jobs.py`)은
"뭐가 들어왔나" 를 보는 곳이고, 여기는 "이 값이 맞나" 를 판정하는 곳이라 페이징과 편집이
붙는다.

## 페이징은 오프셋 기반이다

제공 API(`app/api/jobs.py`)의 커서와 다르다. 저쪽은 폴링 사이에 삽입된 행 때문에 건너뛰는
건이 생기면 안 되고, 이쪽은 사람이 3페이지를 다시 열고 전체 페이지 수를 봐야 한다. 의도된
차이다.

## 기본 정렬은 미전달 우선이다

이미 전달된 행을 고쳐도 소비 측이 가진 값은 바뀌지 않는다. 수동 수정은 `delivered_at` 을
지우거나 되돌리지 않기 때문이다 (`.claude/rules/data-safety.md`). 그래서 검수는 전달 전에
하는 것이 정상 경로고, 화면이 그 순서로 행을 내놓는다.

## 이 파일은 `normalized_jobs` 를 쓰지 않는다

사람이 고친 값은 `job_field_overrides` 에만 쌓인다. 확정 값은 규칙과 보정에서 매번 다시
만들어지는 파생값이고, 파생값에 손으로 쓰면 다음 재정규화가 그것을 덮어쓴다 (Push 10 의 전제,
`migrations/0005_job_field_overrides.sql`).

표가 보여주는 값은 그래서 두 겹이다. 보정이 있으면 사람이 정한 값을, 없으면 규칙이 만든 값을
보여주고 어느 쪽인지 단어로 적는다. `normalized_jobs` 컬럼 자체는 다음 정규화에서 갱신된다.
"""

from __future__ import annotations

import math
import sqlite3
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.api import crawlers
from app.api.ui import render, render_page

router = APIRouter(tags=["ui"], include_in_schema=False)

# 한 페이지에 보여줄 행 수. 운영자가 고를 수 있는 값만 받는다
PAGE_SIZES: tuple[int, ...] = (20, 50, 100)
DEFAULT_PAGE_SIZE = 20

# 현재 페이지 주변으로 몇 개의 페이지 번호를 직접 누르게 둘지
PAGE_WINDOW = 2

_BASE = """
    SELECT n.id            AS id,
           n.raw_job_id    AS raw_job_id,
           n.company       AS company,
           n.company_source AS company_source,
           n.title         AS title,
           n.department    AS department,
           n.deadline      AS deadline,
           n.body          AS body,
           n.requirements  AS requirements,
           n.source_url    AS source_url,
           n.normalized_at AS normalized_at,
           n.delivered_at  AS delivered_at,
           r.crawled_at    AS crawled_at,
           r.workflow_id   AS workflow_id,
           w.name          AS workflow_name
      FROM normalized_jobs n
      JOIN raw_jobs r ON r.id = n.raw_job_id
      JOIN workflows w ON w.id = r.workflow_id
"""

# 미전달 우선, 그다음 최신 수집 순. `delivered_at IS NULL` 은 미전달일 때 1 이라 내림차순이
# 미전달을 앞으로 보낸다
_ORDER = " ORDER BY (n.delivered_at IS NULL) DESC, r.crawled_at DESC, n.id DESC"


def _filters(workflow_id: int | None, company: str, query: str) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if workflow_id is not None:
        clauses.append("r.workflow_id = ?")
        params.append(workflow_id)
    if company:
        clauses.append("n.company = ?")
        params.append(company)
    if query:
        clauses.append("(n.title LIKE ? OR n.company LIKE ? OR n.department LIKE ?)")
        params.extend([f"%{query}%"] * 3)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def _page_url(criteria: dict[str, str], page: int) -> str:
    """페이지 이동 주소. 지금 걸린 조회 조건을 그대로 달고 페이지 번호만 바꾼다.

    조건을 서버가 붙여 두면 페이지 버튼이 폼을 참조하지 않아도 된다. 참조하게 두면 조건을
    바꾸고 조회를 누르지 않은 상태에서 페이지를 넘길 때, 화면에 보이는 표와 다른 조건으로
    넘어간다.
    """
    return "/ui/review?" + urlencode({**criteria, "page": page})


def _page_numbers(page: int, total_pages: int) -> list[int]:
    """현재 페이지 주변의 번호. 3페이지를 다시 여는 것이 한 번에 되게 한다."""
    start = max(1, page - PAGE_WINDOW)
    end = min(total_pages, page + PAGE_WINDOW)
    return list(range(start, end + 1))


@router.get("/review", response_class=HTMLResponse)
def review_page(request: Request) -> HTMLResponse:
    return render_page(request, "pages/review.html")


@router.get("/ui/review", response_class=HTMLResponse)
def review_table_fragment(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(crawlers.get_connection)],
    workflow_id: str = "",
    company: str = "",
    q: str = "",
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> HTMLResponse:
    """검수 대상 한 페이지. 표 영역만 이 조각으로 갈린다.

    `workflow_id` 를 문자열로 받는 이유는 "전체" 를 고르면 빈 값이 오기 때문이다. 정수
    파라미터로 두면 그 빈 값이 422 가 되어 표가 갱신되지 않는다.

    조회 조건이 폼에서 올 때는 `page` 가 함께 오지 않아 1페이지가 된다. 조건을 바꿨는데 2페이지
    자리가 유지되면 사람이 보고 있는 것과 다른 구간이 나온다.
    """
    size = page_size if page_size in PAGE_SIZES else DEFAULT_PAGE_SIZE
    selected = int(workflow_id) if workflow_id.strip().isdigit() else None
    where, params = _filters(selected, company.strip(), q.strip())

    counted = conn.execute(
        f"SELECT count(*) AS total FROM normalized_jobs n"
        f" JOIN raw_jobs r ON r.id = n.raw_job_id{where}",
        params,
    ).fetchone()
    total = int(counted["total"]) if counted is not None else 0
    total_pages = max(1, math.ceil(total / size))
    # 마지막 페이지 뒤를 요청하면 마지막 페이지를 준다. 빈 표를 주면 사람은 조건이 잘못됐다고
    # 읽는다
    current = min(max(page, 1), total_pages)

    rows = conn.execute(
        f"{_BASE}{where}{_ORDER} LIMIT ? OFFSET ?",
        [*params, size, (current - 1) * size],
    ).fetchall()

    criteria = {
        "workflow_id": workflow_id,
        "company": company,
        "q": q,
        "page_size": str(size),
    }
    return render(
        request,
        "fragments/review_table.html",
        jobs=rows,
        total=total,
        page=current,
        page_size=size,
        total_pages=total_pages,
        first_index=(current - 1) * size + 1 if rows else 0,
        last_index=(current - 1) * size + len(rows),
        page_numbers=_page_numbers(current, total_pages),
        page_url=lambda number: _page_url(criteria, number),
    )


@router.get("/ui/review/filters", response_class=HTMLResponse)
def review_filters_fragment(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(crawlers.get_connection)],
) -> HTMLResponse:
    """조회 조건. 워크플로우와 회사는 지금 저장된 값에서 만든다."""
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
        "fragments/review_filters.html",
        workflows=workflows,
        companies=[row["company"] for row in companies],
        page_sizes=PAGE_SIZES,
        default_page_size=DEFAULT_PAGE_SIZE,
    )
