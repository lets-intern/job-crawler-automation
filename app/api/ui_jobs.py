"""수집 공고 조회 화면의 조각 라우트.

운영자가 "실제로 뭐가 들어왔나" 를 보는 화면이다. 소비 측(채용공고 사이트)이 쓰는 제공 API 와는
목적이 다르다 — 저쪽은 커서로 순서대로 받아 가는 경로고, 여기는 사람이 필터·검색·정렬로 들춰
보는 경로다. 그래서 이 조회는 제공 API 를 재사용하지 않는다.

읽기만 한다. 이 파일의 어떤 경로도 `normalized_jobs` 를 쓰지 않고, 특히 `delivered_at` 은
읽어서 보여주기만 한다 (`.claude/rules/data-safety.md`).

정렬 컬럼과 방향은 표에 있는 값으로만 받는다. 화면에서 온 문자열을 SQL 에 그대로 넣지 않는다.
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.api import crawlers
from app.api.ui import render

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

_BASE = """
    SELECT n.id            AS id,
           n.company       AS company,
           n.title         AS title,
           n.department    AS department,
           n.deadline      AS deadline,
           n.source_url    AS source_url,
           n.normalized_at AS normalized_at,
           n.delivered_at  AS delivered_at,
           r.workflow_id   AS workflow_id,
           w.name          AS workflow_name
      FROM normalized_jobs n
      JOIN raw_jobs r ON r.id = n.raw_job_id
      JOIN workflows w ON w.id = r.workflow_id
"""


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


@router.get("/ui/jobs", response_class=HTMLResponse)
def job_table_fragment(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(crawlers.get_connection)],
    workflow_id: str = "",
    company: str = "",
    q: str = "",
    sort: str = "normalized_at",
    order: str = "desc",
) -> HTMLResponse:
    """필터·검색·정렬 결과. 표 영역만 이 조각으로 갈린다.

    `workflow_id` 를 문자열로 받는 이유는 "전체" 를 고르면 빈 값이 오기 때문이다. 정수 파라미터로
    두면 그 빈 값이 422 가 되어 표가 갱신되지 않는다.
    """
    column = SORTS.get(sort, SORTS["normalized_at"])
    direction = ORDERS.get(order, "DESC")
    selected = int(workflow_id) if workflow_id.strip().isdigit() else None
    where, params = _filters(selected, company.strip(), q.strip())

    rows = conn.execute(
        f"{_BASE}{where} ORDER BY {column} {direction}, n.id {direction} LIMIT ?",
        [*params, ROW_LIMIT],
    ).fetchall()
    total = conn.execute(
        f"SELECT count(*) AS total FROM normalized_jobs n"
        f" JOIN raw_jobs r ON r.id = n.raw_job_id{where}",
        params,
    ).fetchone()

    return render(
        request,
        "fragments/job_table.html",
        jobs=rows,
        total=int(total["total"]) if total is not None else 0,
        shown=len(rows),
        row_limit=ROW_LIMIT,
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
    )


@router.get("/ui/jobs/{job_id}", response_class=HTMLResponse)
def job_detail_fragment(
    request: Request,
    job_id: int,
    conn: Annotated[sqlite3.Connection, Depends(crawlers.get_connection)],
) -> HTMLResponse:
    """공고 한 건. 원문 링크는 수집한 값 그대로다."""
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
