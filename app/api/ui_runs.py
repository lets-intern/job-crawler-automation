"""실행 하나가 놓친 공고를 보여주는 조각 라우트.

`crawl_run_failures` 는 실행이 목록에서는 잡았는데 본문까지 데려오지 못한 공고를 한 줄씩
들고 있다 (`migrations/0010_run_failures.sql`). 그 행을 그대로 표로 낸다.

## 건수만으로는 고칠 수 없다

`fail_count = 3` 은 무엇을 하라는 말이 아니다. 어느 공고가 어떤 사유로 빠졌는지, 목록에서 읽은
주소가 무엇인지가 있어야 그 주소를 열어 보고 셀렉터를 고칠 수 있다. 그래서 사유·제목·주소·
메시지를 한 줄에 같이 적는다.

사유 이름도 그 자체로는 다음 행동을 말해 주지 않는다. `detail_empty` 를 처음 보는 사람은 목록
셀렉터를 고쳐야 하는지 상세 셀렉터를 고쳐야 하는지 모른다. 사유마다 `app/api/ui.py` 의
`NEXT_STEPS` 에 있는 다음 행동을 같이 적는다.

## 테스트 실행과 워크플로우가 같은 표를 본다

실행 번호 하나로 읽으므로 테스트 실행(`crawl_runs.crawler_id`)이든 주기 실행
(`workflow_id`)이든 같은 조각이 나온다. 화면마다 다른 표를 만들면 같은 실패가 두 화면에서
다르게 읽힌다.
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.api import crawlers
from app.api.ui import next_step, reason_word, render

router = APIRouter(tags=["ui"], include_in_schema=False)

# 한 화면에 그리는 실패의 상한. 이보다 많으면 앞쪽만 그리고 몇 건 중 몇 건인지 적는다.
# 목록 전체가 실패한 실행은 수백 줄이 되고, 그 표는 열자마자 읽기를 포기하게 된다
FAILURE_LIMIT = 50


def run_failures(conn: sqlite3.Connection, run_id: int) -> dict[str, Any]:
    """실행 하나의 실패 목록. 사유마다 다음 행동을 붙여 돌려준다.

    조각 라우트와 테스트 실행 결과가 같은 함수를 쓴다 — 두 화면이 같은 실패를 다르게 적지
    않게 하려는 것이다.
    """
    total = int(
        conn.execute(
            "SELECT COUNT(*) FROM crawl_run_failures WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
    )
    rows = conn.execute(
        """
        SELECT reason, title, source_url, message
          FROM crawl_run_failures
         WHERE run_id = ?
         ORDER BY id
         LIMIT ?
        """,
        (run_id, FAILURE_LIMIT),
    ).fetchall()
    return {
        "run_id": run_id,
        "total": total,
        "limit": FAILURE_LIMIT,
        # `items` 라고 부르지 않는다. Jinja 에서 딕셔너리의 `items` 메서드와 겹친다
        "rows": [
            {
                "reason": str(row["reason"] or ""),
                "reason_word": reason_word(str(row["reason"] or "")),
                # 사유 이름만으로는 무엇을 할지 모른다 (`app/api/ui.py` 의 `NEXT_STEPS`)
                "next": next_step(str(row["reason"] or "")),
                "title": str(row["title"] or ""),
                "source_url": str(row["source_url"] or ""),
                "message": str(row["message"] or ""),
            }
            for row in rows
        ],
    }


@router.get("/ui/runs/{run_id}/failures", response_class=HTMLResponse)
def run_failures_fragment(
    request: Request,
    run_id: int,
    conn: Annotated[sqlite3.Connection, Depends(crawlers.get_connection)],
) -> HTMLResponse:
    """실행 하나가 놓친 공고 표. 워크플로우 카드의 버튼이 이 자리를 채운다.

    실패가 0건이어도 200 이고 빈 상태를 돌려준다. 아무것도 안 돌려주면 버튼을 눌렀는데 화면이
    조용해지고, 운영자는 눌린 것인지 실패가 없는 것인지 알 수 없다.
    """
    return render(request, "fragments/run_failures.html", failures=run_failures(conn, run_id))
