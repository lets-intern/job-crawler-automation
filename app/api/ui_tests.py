"""테스트 실행 결과 화면의 조각 라우트.

실행은 `app/api/crawlers.py` 의 test-run 라우트를 그대로 부른다. 화면 전용 실행 경로를 따로
만들지 않는다 — 그러면 화면에서 통과한 셀렉터가 API 에서는 다르게 도는 상태가 생긴다.

## 무엇을 보여주는가

운영자가 이 화면을 여는 이유는 "어느 필드가 왜 비었나" 하나다. 그래서 실행 요약보다 필드별
표가 먼저 온다. 실패한 필드에는 사유를 같이 적는다.

| 화면에 적는 사유 | 판정 근거 |
|---|---|
| `셀렉터 없음` | 셀렉터가 빈 문자열이다. 사이트에 그 항목이 없다는 뜻이라 실패가 아니다 |
| `selector_miss` | 셀렉터는 있는데 어느 항목에서도 값을 찾지 못했다 |
| `parse` | 일부 항목에서만 값을 읽었다 |

실행 전체가 실패한 경우의 사유는 `crawl_runs.error_class` 그대로다. 항목별 실패는
`RunResult.failures` 가 들고 있는 것을 그대로 표로 옮긴다 — 이 값은 `crawl_runs` 에 남지
않으므로, 실행 직후 이 화면이 유일하게 보여줄 수 있는 자리다.

상태는 단어로만 적는다. 아이콘·이모지를 쓰지 않는다 (`.claude/rules/writing.md`).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.api import crawlers
from app.api.ui import render
from app.api.ui_crawlers import crawler_rows, error_detail
from app.crawler.fetcher import Fetcher
from app.crawler.runner import KNOWN
from app.selector.schema import SelectorSchemaError, validate_selectors

router = APIRouter(tags=["ui"], include_in_schema=False)

# 미리보기 표의 열 순서. `app/crawler/runner.py` 의 `_record()` 가 만드는 키 그대로다
FIELDS: tuple[tuple[str, str], ...] = (
    ("list_title", "list.title"),
    ("list_date", "list.date"),
    ("title", "detail.title"),
    ("body", "detail.body"),
    ("requirements", "detail.requirements"),
    ("deadline", "detail.deadline"),
    ("department", "detail.department"),
)

# 값이 길면 표가 읽히지 않는다. 자른 자리는 화면에 표시한다
PREVIEW_LIMIT = 120


def _selector_of(selectors: Any, path: str) -> str:
    """`list.title` 같은 경로로 저장된 셀렉터를 꺼낸다. 없으면 빈 문자열."""
    if selectors is None:
        return ""
    section, _, name = path.partition(".")
    return str(getattr(getattr(selectors, section), name, "") or "")


def _saved_selectors(conn: sqlite3.Connection, crawler_id: int) -> Any:
    """저장된 셀렉터. 읽을 수 없으면 None — 그 사유는 실행 결과가 이미 말한다."""
    row = conn.execute("SELECT selectors_json FROM crawlers WHERE id = ?", (crawler_id,)).fetchone()
    if row is None or not row["selectors_json"]:
        return None
    try:
        return validate_selectors(json.loads(row["selectors_json"]))
    except (json.JSONDecodeError, SelectorSchemaError):
        return None


def _field_report(items: list[Any], selectors: Any) -> list[dict[str, Any]]:
    """필드별 판정. 값이 있는 항목 수와 실패 사유를 함께 만든다."""
    counted = [item for item in items if item.state != KNOWN]
    total = len(counted)
    report: list[dict[str, Any]] = []

    for key, path in FIELDS:
        selector = _selector_of(selectors, path)
        filled = sum(1 for item in counted if item.fields.get(key, "").strip())

        if not selector:
            state, reason = "해당 없음", "셀렉터 없음 (사이트에 그 항목이 없다)"
        elif total == 0:
            state, reason = "실패", "판정할 항목이 없다"
        elif filled == 0:
            state, reason = "실패", "selector_miss — 어느 항목에서도 값을 찾지 못했다"
        elif filled < total:
            state, reason = "실패", f"parse — {total - filled}건에서 값을 읽지 못했다"
        else:
            state, reason = "성공", ""

        report.append(
            {
                "path": path,
                "selector": selector,
                "filled": filled,
                "total": total,
                "state": state,
                "reason": reason,
            }
        )
    return report


@router.get("/ui/test-targets", response_class=HTMLResponse)
def test_targets_fragment(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(crawlers.get_connection)],
) -> HTMLResponse:
    """실행할 크롤러 목록. 등록 화면과 같은 목록을 읽는다."""
    return render(request, "fragments/test_targets.html", crawlers=crawler_rows(conn))


@router.post("/ui/crawlers/{crawler_id}/test-run", response_class=HTMLResponse)
async def test_run_fragment(
    request: Request,
    crawler_id: int,
    conn: Annotated[sqlite3.Connection, Depends(crawlers.get_connection)],
    fetcher: Annotated[Fetcher, Depends(crawlers.get_crawl_fetcher)],
    limit: Annotated[int, Form()] = 3,
) -> HTMLResponse:
    """저장된 셀렉터로 1회 실행하고 결과 영역만 갈아 끼운다."""
    if not 1 <= limit <= 20:
        return render(
            request,
            "fragments/test_result.html",
            error={"reason": "invalid_limit", "message": "상세 건수는 1 이상 20 이하여야 한다"},
        )

    try:
        result = await crawlers.test_run(crawler_id, conn, fetcher, limit)
    except HTTPException as exc:
        return render(request, "fragments/test_result.html", error=error_detail(exc))

    return render(
        request,
        "fragments/test_result.html",
        result=result,
        fields=FIELDS,
        report=_field_report(result.items, _saved_selectors(conn, crawler_id)),
        preview_limit=PREVIEW_LIMIT,
        targets=crawler_rows(conn),
    )
