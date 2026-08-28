"""직무 분류 화면의 조각 라우트.

체계 CRUD 는 `app/taxonomy.py` 를 그대로 부른다. 이 파일이 더하는 것은 화면이 필요로 하는
두 가지뿐이다 — 대분류 아래 소분류를 묶어 트리로 그리는 것, 그리고 그 이름으로 이미
분류된 공고 수를 얹는 것.

## 공고 수는 여기서 센다

`app/taxonomy.py` 는 `job_taxonomy` 하나만 읽는다. 공고 수는 `normalized_jobs` 를 함께
읽어야 하고, 그 셈이 저장소 모듈에 들어가면 표 한 행을 고치는 일과 공고를 세는 일이 한
자리에 섞인다(`app/api/ui_companies.py` 와 같은 이유).

이름으로 잇는다. `job_taxonomy` 는 아이디를 갖지만 `normalized_jobs.job_major`/`job_minor`
는 이름을 저장하므로(PRD 1절 — 재정규화로 다시 만들어지는 파생 표라 id 를 넣으면 소비 측이
표를 한 벌 더 갖게 된다), 세는 것도 이름으로 잇는다.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app import taxonomy
from app.api.settings import get_connection
from app.api.ui import render

router = APIRouter(tags=["ui"], include_in_schema=False)


@dataclass(frozen=True)
class TaxonomyRow:
    """화면이 그리는 한 줄. 저장된 노드에 그 이름을 가진 공고 수를 얹은 것이다."""

    node: taxonomy.TaxonomyNode
    job_count: int


def _job_counts(conn: sqlite3.Connection, column: str) -> dict[str, int]:
    """`column`(`job_major` 또는 `job_minor`) 값별 공고 수. 호출부가 고정된 두 이름만 넘긴다."""
    rows = conn.execute(
        f"SELECT {column} AS name, COUNT(*) AS n FROM normalized_jobs"
        f" WHERE {column} IS NOT NULL GROUP BY {column}"
    ).fetchall()
    return {str(row["name"]): int(row["n"]) for row in rows}


def _name_count(conn: sqlite3.Connection, column: str, name: str) -> int:
    """이름 하나의 공고 수. 이름을 고치기 전에 그 값을 화면에 보여줄 때 쓴다."""
    row = conn.execute(
        f"SELECT COUNT(*) AS n FROM normalized_jobs WHERE {column} = ?", (name,)
    ).fetchone()
    return int(row["n"]) if row is not None else 0


def build_tree(conn: sqlite3.Connection) -> list[tuple[TaxonomyRow, list[TaxonomyRow]]]:
    """대분류와 그 아래 소분류를 묶어, 각자의 공고 수와 함께 늘어놓는다."""
    major_counts = _job_counts(conn, "job_major")
    minor_counts = _job_counts(conn, "job_minor")
    tree: list[tuple[TaxonomyRow, list[TaxonomyRow]]] = []
    for major in taxonomy.list_majors(conn):
        major_row = TaxonomyRow(major, major_counts.get(major.name, 0))
        minor_rows = [
            TaxonomyRow(minor, minor_counts.get(minor.name, 0))
            for minor in taxonomy.list_minors(conn, major.id)
        ]
        tree.append((major_row, minor_rows))
    return tree


def _tree(
    request: Request,
    conn: sqlite3.Connection,
    *,
    message: str = "",
    error: dict[str, str] | None = None,
) -> HTMLResponse:
    """트리 조각 하나. 더하기·고치기·켜기끄기·씨앗 넣기가 모두 이 조각으로 돌아온다."""
    return render(
        request,
        "fragments/taxonomy_tree.html",
        tree=build_tree(conn),
        majors=taxonomy.list_majors(conn),
        is_empty=taxonomy.is_empty(conn),
        message=message,
        error=error,
    )


@router.get("/ui/taxonomy", response_class=HTMLResponse)
def taxonomy_tree_fragment(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
) -> HTMLResponse:
    return _tree(request, conn)
