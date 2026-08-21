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

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from app.api import crawlers
from app.api.ui import render, render_page
from app.normalize.engine import OVERRIDABLE_FIELDS

router = APIRouter(tags=["ui"], include_in_schema=False)

# 한 페이지에 보여줄 행 수. 운영자가 고를 수 있는 값만 받는다
PAGE_SIZES: tuple[int, ...] = (20, 50, 100)
DEFAULT_PAGE_SIZE = 20

# 현재 페이지 주변으로 몇 개의 페이지 번호를 직접 누르게 둘지
PAGE_WINDOW = 2

# 고칠 수 있는 필드와 화면에 적을 이름. 키는 `OVERRIDABLE_FIELDS` 와 같아야 한다 —
# 그쪽이 `job_field_overrides.field_name` 의 CHECK 와 이미 맞춰져 있다
FIELD_LABELS: dict[str, str] = {
    "company": "회사",
    "title": "제목",
    "department": "부서",
    "deadline": "마감",
    "body": "본문",
    "requirements": "자격요건",
}

# 여러 줄로 들어오는 필드. 한 줄 입력으로 고치면 줄바꿈이 사라진다
LONG_FIELDS: frozenset[str] = frozenset({"body", "requirements"})

# 모달을 닫으라고 화면에 알리는 이벤트 이름. `base.html` 의 여닫는 스크립트가 이것을 듣는다
MODAL_DONE_EVENT = "app-modal-done"

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


def _cell(
    job: sqlite3.Row,
    field: str,
    overrides: dict[str, str],
) -> dict[str, Any]:
    """셀 하나가 그려지는 데 필요한 전부.

    `rule_value` 는 `normalized_jobs` 컬럼, 즉 규칙이 만든 값이다. 보정이 있으면 화면에 나가는
    값은 사람이 정한 값이고, 규칙값은 무엇에서 고쳤는지 보이도록 함께 남긴다.

    보정 여부를 값의 참·거짓으로 판정하지 않는다. 빈 문자열은 "이 필드는 비어 있는 것이 맞다"
    는 사람의 판단이고, 보정이 없는 것과 다르다 (`migrations/0005_job_field_overrides.sql`).
    """
    overridden = field in overrides
    rule_value = job[field] if field in job.keys() else None
    return {
        "raw_job_id": int(job["raw_job_id"]),
        "field": field,
        "label": FIELD_LABELS[field],
        "rule_value": rule_value,
        "value": overrides[field] if overridden else rule_value,
        "overridden": overridden,
        "long": field in LONG_FIELDS,
        "delivered": bool(job["delivered_at"]),
    }


def _read_overrides(conn: sqlite3.Connection, raw_job_ids: list[int]) -> dict[int, dict[str, str]]:
    """여러 건의 보정을 한 번에 읽는다. 행마다 따로 물으면 한 페이지에 쿼리가 수십 개 붙는다."""
    if not raw_job_ids:
        return {}
    marks = ",".join("?" for _ in raw_job_ids)
    rows = conn.execute(
        f"SELECT raw_job_id, field_name, value FROM job_field_overrides"
        f" WHERE raw_job_id IN ({marks})",
        raw_job_ids,
    ).fetchall()
    found: dict[int, dict[str, str]] = {}
    for row in rows:
        found.setdefault(int(row["raw_job_id"]), {})[str(row["field_name"])] = str(row["value"])
    return found


def _read_job(conn: sqlite3.Connection, raw_job_id: int) -> sqlite3.Row | None:
    """그 수집 건의 확정 행. 재정규화로 여러 번 만들어졌다면 가장 최근 것이 화면의 값이다."""
    return conn.execute(
        f"{_BASE} WHERE n.raw_job_id = ? ORDER BY n.id DESC LIMIT 1", (raw_job_id,)
    ).fetchone()


def _modal_response(
    request: Request,
    conn: sqlite3.Connection,
    raw_job_id: int,
    field: str,
    *,
    saved: str = "",
    error: str = "",
    draft: str | None = None,
    swap_row: bool = False,
) -> HTMLResponse:
    """모달 안의 내용. 저장·삭제 뒤에는 표의 그 칸도 같은 응답에 실어 보낸다.

    표를 다시 그리지 않는다. `swap_row` 가 켜지면 값 칸·보정 개수·전달 칸 세 자리만 OOB 로
    갈린다. 모달을 닫았는데 표에 옛 값이 남아 있으면 운영자는 저장이 안 된 줄 안다.

    실패도 이 조각으로 나간다. 고치다 실패했는데 표 전체가 오류 상자로 바뀌면 운영자는 방금
    어디를 고치고 있었는지부터 다시 찾아야 한다.
    """
    if field not in OVERRIDABLE_FIELDS:
        return render(
            request,
            "fragments/review_modal.html",
            cell=None,
            job=None,
            message=f"고칠 수 없는 필드다: {field} (가능한 값: {', '.join(OVERRIDABLE_FIELDS)})",
        )
    job = _read_job(conn, raw_job_id)
    if job is None:
        return render(
            request,
            "fragments/review_modal.html",
            cell=None,
            job=None,
            message=f"수집 건 {raw_job_id} 의 정규화 행이 없다. 목록을 다시 불러 확인한다",
        )
    overrides = _read_overrides(conn, [raw_job_id]).get(raw_job_id, {})
    response = render(
        request,
        "fragments/review_modal.html",
        cell=_cell(job, field, overrides),
        job=job,
        override_count=len(overrides),
        saved=saved,
        error=error,
        draft=draft,
        swap_row=swap_row,
        message="",
    )
    if swap_row:
        # 설정(settle)까지 끝난 뒤에 닫는다. 먼저 닫으면 표가 갈리기 전 화면이 드러난다
        response.headers["HX-Trigger-After-Settle"] = MODAL_DONE_EVENT
    return response


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
    overrides = _read_overrides(conn, [int(row["raw_job_id"]) for row in rows])
    listed = [
        {
            "job": row,
            "cells": [
                _cell(row, field, overrides.get(int(row["raw_job_id"]), {}))
                for field in OVERRIDABLE_FIELDS
            ],
            "override_count": len(overrides.get(int(row["raw_job_id"]), {})),
        }
        for row in rows
    ]

    criteria = {
        "workflow_id": workflow_id,
        "company": company,
        "q": q,
        "page_size": str(size),
    }
    return render(
        request,
        "fragments/review_table.html",
        jobs=listed,
        fields=OVERRIDABLE_FIELDS,
        labels=FIELD_LABELS,
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


@router.get("/ui/review/modal/{raw_job_id}/{field}", response_class=HTMLResponse)
def review_modal_fragment(
    request: Request,
    raw_job_id: int,
    field: str,
    conn: Annotated[sqlite3.Connection, Depends(crawlers.get_connection)],
) -> HTMLResponse:
    """그 필드를 고치는 모달. 표 안에서 바로 고치는 경로는 두지 않는다.

    본문과 자격요건은 수백 자에 여러 줄인데, 표 칸 폭에 갇힌 입력에서는 고치는 값 전체가 한
    번에 보이지 않는다. 입구를 둘로 두면 어느 쪽이 저장된 값인지 화면에서 알 수 없어, 고치는
    자리를 이 모달 하나로 모은다.
    """
    return _modal_response(request, conn, raw_job_id, field)


@router.put("/ui/review/cells/{raw_job_id}/{field}", response_class=HTMLResponse)
def save_review_cell_fragment(
    request: Request,
    raw_job_id: int,
    field: str,
    conn: Annotated[sqlite3.Connection, Depends(crawlers.get_connection)],
    value: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """사람이 정한 값을 `job_field_overrides` 에 쌓는다.

    `normalized_jobs` 에 쓰지 않는다. 확정 값은 규칙과 보정에서 매번 다시 만들어지는 파생값이고,
    파생값에 손으로 쓰면 다음 재정규화가 그것을 덮어쓴다. `delivered_at` 도 건드리지 않는다 —
    수동 수정이 전달 표시를 되돌리면 소비 측에 같은 데이터가 다시 간다
    (`.claude/rules/data-safety.md`).
    """
    if field not in OVERRIDABLE_FIELDS or _read_job(conn, raw_job_id) is None:
        return _modal_response(request, conn, raw_job_id, field)

    try:
        conn.execute(
            """
            INSERT INTO job_field_overrides (raw_job_id, field_name, value)
                 VALUES (?, ?, ?)
            ON CONFLICT (raw_job_id, field_name)
              DO UPDATE SET value = excluded.value, updated_at = datetime('now')
            """,
            (raw_job_id, field, value),
        )
    except sqlite3.DatabaseError as exc:
        # 실패 사유를 모달 안에 그대로 보여준다. 모달은 닫지 않고 고쳐 쓴 값도 입력에 남긴다
        return _modal_response(request, conn, raw_job_id, field, error=str(exc), draft=value)

    return _modal_response(
        request,
        conn,
        raw_job_id,
        field,
        saved=f"{FIELD_LABELS[field]} 보정을 저장했다",
        swap_row=True,
    )


@router.delete("/ui/review/cells/{raw_job_id}/{field}", response_class=HTMLResponse)
def delete_review_cell_fragment(
    request: Request,
    raw_job_id: int,
    field: str,
    conn: Annotated[sqlite3.Connection, Depends(crawlers.get_connection)],
) -> HTMLResponse:
    """보정을 지운다. 그 필드는 다음 정규화에서 규칙이 만든 값으로 돌아간다."""
    if field not in OVERRIDABLE_FIELDS or _read_job(conn, raw_job_id) is None:
        return _modal_response(request, conn, raw_job_id, field)
    conn.execute(
        "DELETE FROM job_field_overrides WHERE raw_job_id = ? AND field_name = ?",
        (raw_job_id, field),
    )
    return _modal_response(
        request,
        conn,
        raw_job_id,
        field,
        saved=f"{FIELD_LABELS[field]} 보정을 지웠다",
        swap_row=True,
    )
