"""실행이 끝났을 때 부르는 자리. 새 공고가 들어온 것만 알린다.

**건너뜀이나 실패는 알리지 않는다.** 알림이 오는 이유가 하나여야 알림이 읽힌다. 실패는
워크플로우 화면의 실패 배지와 `crawl_runs` 가 이미 들고 있고, 그것을 휴대폰으로 한 번 더
보내면 정작 새 공고 알림이 묻힌다 (`../.claude/tasks/done/ntfy-notify/tasks-ntfy-notify.md`).

**여기서 예외가 나가지 않는다.** 부르는 자리가 `app/crawler/runner.py` 의 실행 끝이라,
알림 쪽 사고 하나가 수집을 실패로 만들면 안 된다. 설정을 읽지 못하든 알림 서버가 죽어 있든
로그 한 줄로 끝내고 실행 결과는 그대로 둔다.

`RunResult` 를 받지 않고 값을 받는다. 이 모듈이 `app.crawler.runner` 를 import 하면 그쪽도
이 모듈을 import 하므로 순환이 된다. 어느 항목이 적재된 것인지 아는 쪽은 실행이다.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Sequence

from app.notify import settings as store
from app.notify.message import NewJob, build_new_jobs_message
from app.notify.ntfy import SendResult, send

logger = logging.getLogger(__name__)

# 워크플로우 이름을 읽지 못했을 때 제목에 쓰는 말. 어느 워크플로우인지는 남는다
_UNNAMED = "이름 없는 워크플로우"


async def notify_new_jobs(
    conn: sqlite3.Connection,
    *,
    workflow_id: int,
    new_count: int,
    jobs: Sequence[NewJob],
) -> SendResult | None:
    """새 공고 알림 하나를 보낸다. 보내지 않았으면 None 이다.

    보내지 않는 경우가 셋이다. 알림이 꺼져 있을 때, 새로 적재된 것이 없을 때, 그리고
    적재는 됐지만 설정한 기준 건수에 못 미칠 때.

    `new_count` 는 실행이 센 값을 그대로 받는다. `jobs` 의 길이로 대신하지 않는다 —
    둘이 어긋난다면 그것 자체가 알아야 할 사실이라 로그에 남긴다.
    """
    try:
        config = store.read_config(conn)
        if not config.enabled:
            return None
        if new_count < config.min_new_count:
            # 0건도 여기서 걸린다. 기준 건수는 1 이상이다
            logger.debug(
                "workflow %s: 새 공고 %s건은 알림 기준 %s건에 못 미친다",
                workflow_id,
                new_count,
                config.min_new_count,
            )
            return None

        if len(jobs) != new_count:
            logger.warning(
                "workflow %s: 적재 %s건인데 알림에 넘어온 공고는 %s건이다",
                workflow_id,
                new_count,
                len(jobs),
            )

        message = build_new_jobs_message(
            site_name=_site_name(conn, workflow_id),
            jobs=jobs,
            click=_list_url(conn, workflow_id) or config.click_url,
        )
        result = await send(config.target, message)
    except Exception as exc:
        # 알림 때문에 수집이 실패하지 않는다. 무엇이 났는지만 남긴다
        logger.warning(
            "workflow %s: 알림을 보내지 못했다: %s: %s", workflow_id, type(exc).__name__, exc
        )
        return None

    if not result.ok:
        logger.warning("workflow %s: 알림을 보내지 못했다: %s", workflow_id, result.detail)
    return result


def _list_url(conn: sqlite3.Connection, workflow_id: int) -> str:
    """알림을 눌렀을 때 열 곳. 그 사이트의 공고 목록 페이지다.

    개별 공고가 아니라 목록인 것은 한 알림에 여러 건이 들어오기 때문이다. 하나만 열면
    나머지를 놓치고, 목록을 열면 방금 들어온 것들이 거기 다 있다.
    """
    row = conn.execute(
        """
        SELECT c.list_url AS list_url
          FROM workflows w
          JOIN crawlers c ON c.id = w.crawler_id
         WHERE w.id = ?
        """,
        (workflow_id,),
    ).fetchone()
    if row is None:
        return ""
    return str(row["list_url"] or "").strip()


def _site_name(conn: sqlite3.Connection, workflow_id: int) -> str:
    """알림 제목에 들어갈 이름. 워크플로우 이름이 운영자가 화면에서 보는 이름이다."""
    row = conn.execute("SELECT name FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
    if row is None or not str(row["name"]).strip():
        return _UNNAMED
    return str(row["name"]).strip()
