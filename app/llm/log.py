"""모델 호출을 `llm_calls` 에 남긴다.

셀렉터 생성만 있을 때는 로그 줄 하나로 충분했다. 본문 분류는 공고마다 하나씩 붙어서, 로그가
사라지면 "이번 달에 얼마나 썼나" 에 답할 길이 없다 (`migrations/0013_llm_calls.sql`).

**기록 실패가 호출을 실패로 만들지 않는다.** 표가 없거나 DB 가 잠겨 있어도 분류는 계속
가야 한다 — 남기지 못한 것은 숫자 한 줄이고, 멈추면 사라지는 것은 그 공고의 분류다.
못 남긴 사실은 경고 로그로 남는다.

담지 않는 것: 프롬프트와 응답 본문. 비용을 세는 표에 사이트 본문이 한 벌 더 생길 이유가 없다.
"""

from __future__ import annotations

import logging
import sqlite3

from app.llm.gemini import PROVIDER, Usage

logger = logging.getLogger(__name__)

# `llm_calls.feature` 에 들어가는 값. 무엇이 토큰을 썼는지 세는 잣대다
SELECTOR_GENERATE = "selector_generate"
SELECTOR_REPAIR = "selector_repair"
CLASSIFY = "classify"

FEATURES: tuple[str, ...] = (SELECTOR_GENERATE, SELECTOR_REPAIR, CLASSIFY)


def record_call(
    conn: sqlite3.Connection,
    *,
    feature: str,
    usage: Usage,
    ok: bool = True,
    error: str = "",
) -> int:
    """호출 하나를 남긴다. 실패해도 예외를 올리지 않고 0 을 돌려준다.

    실패한 호출도 남긴다. 토큰을 쓰고 실패하는 경우가 있어서 빼고 세면 합이 실제와 어긋난다.
    """
    try:
        cursor = conn.execute(
            """
            INSERT INTO llm_calls
                   (provider, model, feature, input_tokens, output_tokens, total_tokens,
                    latency_ms, ok, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                PROVIDER,
                usage.model,
                feature,
                usage.input_tokens,
                usage.output_tokens,
                usage.total_tokens,
                usage.latency_ms,
                int(ok),
                error[:500],
            ),
        )
    except sqlite3.Error as exc:
        logger.warning("모델 호출 기록을 남기지 못했다 feature=%s: %s", feature, exc)
        return 0
    return int(cursor.lastrowid or 0)


def totals(conn: sqlite3.Connection, feature: str | None = None) -> dict[str, int]:
    """호출 수와 토큰 합. 기능을 주면 그 기능만 센다. 읽기 전용이다."""
    where, params = ("WHERE feature = ?", (feature,)) if feature else ("", ())
    row = conn.execute(
        f"""
        SELECT count(*) AS calls,
               coalesce(sum(input_tokens), 0)  AS input_tokens,
               coalesce(sum(output_tokens), 0) AS output_tokens,
               coalesce(sum(total_tokens), 0)  AS total_tokens,
               coalesce(sum(latency_ms), 0)    AS latency_ms,
               coalesce(sum(ok), 0)            AS ok
          FROM llm_calls {where}
        """,
        params,
    ).fetchone()
    return {name: int(row[name]) for name in row.keys()}
