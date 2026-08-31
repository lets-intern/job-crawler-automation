"""대시보드. 처음 들어오면 보이는 화면이다.

무엇을 보여주는가: 오늘 새로 들어온 공고 수와 오늘 완성된 공고 수, 최근 14일간 일별
추이, 최근 완성된 공고 몇 건, 자주 쓰는 화면 바로가기, 그리고 이 프로세스가 방금 낸
로그.

## "완성 시각" 은 근사값이다

`normalized_jobs` 는 "완성" 을 열여섯 칸의 채움 여부로만 판정하고(`app/api/ui_complete.py`
의 `_COMPLETE_WHERE`), 그 상태가 된 시각을 따로 기록하지 않는다. 그래서 하루에 몇 건이
완성됐는지는 그 건을 마지막으로 채운 처리 시각으로 근사한다 —
`job_classifications.classified_at` 이 있으면 그것을, 없으면(분류를 아직 안 돌린 사이트)
`normalized_jobs.normalized_at` 을 쓴다. 재분류나 규칙 변경으로 나중에 완성 여부가
바뀌어도 이 시각은 갱신되지 않는다. 정확한 이벤트 기록이 필요해지면 그때 전용 표를
둔다 — 지금은 근사로 충분하다(2026-08-29, 운영자 확인).

## 새 SQLite 파일을 쓰지 않는다

집계에 필요한 시각 값이 이미 `raw_jobs.crawled_at` / `job_classifications.classified_at` /
`normalized_jobs.normalized_at` 에 있어, 읽기 전용 집계 쿼리로 전부 계산한다. 로그·분석
전용 DB 파일을 따로 두는 안을 검토했지만 새 파일이 더할 수 있는 것이 없고,
`../.claude/rules/core.md` 의 "SQLite in one file" 을 벗어날 이유가 없다(2026-08-29, 운영자
확인).

## 로그는 이 프로세스가 방금 낸 것만이다

`app/log_ring.py` 의 메모리 버퍼를 그대로 읽는다. 재시작하면 비고, 컨테이너 로그
(`docker compose logs`)를 대체하지 않는다 — 화면에서 바로 훑어보는 용도다.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.api.settings import get_connection
from app.api.ui import display_zone, render, render_page
from app.api.ui_complete import _COMPLETE_WHERE, completed_count, recent_completed
from app.llm.log import by_feature
from app.llm.settings import FEATURE_LABELS
from app.log_ring import LogLine
from app.log_ring import handler as _log_handler

router = APIRouter(tags=["ui"], include_in_schema=False)

# 그래프에 보여줄 날짜 수. 너무 길면 막대가 가늘어져 못 읽고, 너무 짧으면 추이가 안 보인다
TREND_DAYS = 14

# 최근 완성 공고 카드 수. 완성 공고 화면과 같은 4열 그리드라 한 줄 분량으로 맞춘다
RECENT_LIMIT = 4

# 자주 쓰는 화면 바로가기. 대시보드에서 한 번에 갈 수 있게 모은다 — 순서는 얼마나 자주
# 쓰는지를 대략 따른다(완성 확인 -> 검수 -> 운영 -> 설정류)
QUICK_LINKS: tuple[tuple[str, str, str], ...] = (
    ("/complete", "완성 공고", "분류까지 끝난 공고를 소비 측 모양 그대로 미리 본다"),
    ("/review", "데이터 확인", "수집된 값을 조회하고 고친다"),
    ("/workflows", "워크플로우", "크롤링 주기 실행을 등록하고 관리한다"),
    ("/side", "부가 워크플로우", "분류·전달 같은 후처리를 등록하고 실행한다"),
    ("/rules", "정규화 규칙", "정규화 규칙을 조회하고 고친다"),
    ("/taxonomy", "직무 분류", "대분류·소분류 체계를 관리한다"),
    ("/companies", "회사 로고", "회사·모회사 로고를 관리한다"),
    ("/crawlers", "크롤러 등록", "새 사이트의 셀렉터를 만들고 등록한다"),
)


def _offset_modifier() -> str:
    """`display_zone()` 의 지금 UTC 오프셋을 SQLite `date()` 보정 문자열로.

    시간 단위가 아닌 시간대는 없다고 본다 — 기본값 `Asia/Seoul` 은 정시 오프셋이고, 있어도
    반올림된 시간 단위로만 하루 경계가 흔들린다.
    """
    offset = datetime.now(display_zone()).utcoffset() or timedelta(0)
    hours = round(offset.total_seconds() / 3600)
    sign = "+" if hours >= 0 else "-"
    return f"{sign}{abs(hours)} hours"


def _day_range(days: int) -> list[date]:
    """오늘을 포함한 최근 `days`일. 오래된 날짜가 먼저다 — 그래프를 왼쪽부터 읽는다."""
    today = datetime.now(display_zone()).date()
    return [today - timedelta(days=i) for i in range(days - 1, -1, -1)]


def _daily_added(conn: sqlite3.Connection, modifier: str) -> dict[str, int]:
    rows = conn.execute(
        "SELECT date(crawled_at, ?) AS day, count(*) AS n FROM raw_jobs GROUP BY day",
        (modifier,),
    ).fetchall()
    return {str(row["day"]): int(row["n"]) for row in rows}


def _daily_completed(conn: sqlite3.Connection, modifier: str) -> dict[str, int]:
    """일별 완성(근사) 건수. `app.api.ui_complete._COMPLETE_WHERE` 와 같은 완성 정의를 쓴다."""
    rows = conn.execute(
        f"""
        SELECT date(
                 COALESCE(
                   (SELECT classified_at FROM job_classifications jc
                     WHERE jc.raw_job_id = n.raw_job_id),
                   n.normalized_at
                 ),
                 ?
               ) AS day,
               count(*) AS cnt
          FROM normalized_jobs n
         WHERE {_COMPLETE_WHERE}
         GROUP BY day
        """,
        (modifier,),
    ).fetchall()
    return {str(row["day"]): int(row["cnt"]) for row in rows}


def _daily_tokens(conn: sqlite3.Connection, modifier: str) -> dict[str, int]:
    """일별 AI 토큰 사용량 합. `llm_calls` 는 성공·실패 호출을 모두 남긴다(`app/llm/log.py`)."""
    rows = conn.execute(
        """
        SELECT date(called_at, ?) AS day, coalesce(sum(total_tokens), 0) AS n
          FROM llm_calls
         GROUP BY day
        """,
        (modifier,),
    ).fetchall()
    return {str(row["day"]): int(row["n"]) for row in rows}


# gemini-3.1-flash-lite 유료 등급 표준 가격, 2026-08-29 ai.google.dev/gemini-api/docs/pricing
# 확인. **실제로 무슨 제공자·모델을 쓰든 이 값 하나로 어림잡는 추정치다** — 실제 호출은
# 운영자가 화면에서 고른 제공자·모델로 나가고 그 가격은 다를 수 있다(`../.claude/rules/llm.md`).
# 가격이 바뀌면 이 상수도 다시 확인해야 한다.
COST_REFERENCE_MODEL = "gemini-3.1-flash-lite"
_INPUT_USD_PER_MILLION = 0.25
_OUTPUT_USD_PER_MILLION = 1.50

# 2026-08-29 확인한 원/달러 환율의 어림값(1,380원). 환율은 매일 바뀌므로 이 값도 대략적인
# 참고치다 — 정확한 원화 청구액이 아니라 "요즘 대략 얼마 나오는지" 를 보는 용도다
_KRW_PER_USD = 1380


def _daily_cost_usd(conn: sqlite3.Connection, modifier: str) -> dict[str, float]:
    """일별 예상 비용(USD). 입력·출력 단가가 달라 `total_tokens` 가 아니라 둘을 따로 곱한다."""
    rows = conn.execute(
        """
        SELECT date(called_at, ?) AS day,
               coalesce(sum(input_tokens), 0)  AS in_tokens,
               coalesce(sum(output_tokens), 0) AS out_tokens
          FROM llm_calls
         GROUP BY day
        """,
        (modifier,),
    ).fetchall()
    return {
        str(row["day"]): row["in_tokens"] / 1_000_000 * _INPUT_USD_PER_MILLION
        + row["out_tokens"] / 1_000_000 * _OUTPUT_USD_PER_MILLION
        for row in rows
    }


@dataclass(frozen=True)
class TrendDay:
    """그래프 한 날짜. `*_pct` 는 0~100 값이다 — 추가·완성 둘은 같은 최댓값을 기준으로
    비율을 맞춰 서로 견줄 수 있게 하고, 토큰은 단위가 전혀 달라(건수가 아니라 토큰 수)
    자기 자신의 최댓값을 기준으로 따로 맞춘다. 선 그래프라 0건은 그대로 0이다 — 막대와
    달리 안 보일 걱정이 없다."""

    label: str
    added: int
    completed: int
    tokens: int
    cost_usd: float
    cost_krw: int
    added_pct: int
    completed_pct: int
    tokens_pct: int


def _pct(count: int, peak: int) -> int:
    return round(count / peak * 100)


def trend(conn: sqlite3.Connection, days: int = TREND_DAYS) -> list[TrendDay]:
    modifier = _offset_modifier()
    added = _daily_added(conn, modifier)
    completed = _daily_completed(conn, modifier)
    tokens = _daily_tokens(conn, modifier)
    cost = _daily_cost_usd(conn, modifier)
    day_list = _day_range(days)
    peak = max([*added.values(), *completed.values(), 1])
    token_peak = max([*tokens.values(), 1])
    result: list[TrendDay] = []
    for d in day_list:
        key = d.isoformat()
        a, c, t = added.get(key, 0), completed.get(key, 0), tokens.get(key, 0)
        cost_usd = cost.get(key, 0.0)
        result.append(
            TrendDay(
                label=d.strftime("%m/%d"),
                added=a,
                completed=c,
                tokens=t,
                cost_usd=cost_usd,
                cost_krw=round(cost_usd * _KRW_PER_USD),
                added_pct=_pct(a, peak),
                completed_pct=_pct(c, peak),
                tokens_pct=_pct(t, token_peak),
            )
        )
    return result


@dataclass(frozen=True)
class ChartPoint:
    """선 그래프 한 점의 SVG 좌표(viewBox `0 0 100 100`). `y_*` 는 100 에서 뺀 값이다 —
    SVG 는 위가 0 이라, 값이 클수록 위로 가려면 빼야 한다. `day` 를 그대로 들고 있어
    템플릿이 툴팁에 실제 값을 적을 수 있다."""

    x: float
    y_added: float
    y_completed: float
    y_tokens: float
    day: TrendDay


def chart_points(days: list[TrendDay]) -> list[ChartPoint]:
    n = len(days)
    step = 100 / (n - 1) if n > 1 else 0.0
    return [
        ChartPoint(
            x=round(i * step, 2),
            y_added=100 - d.added_pct,
            y_completed=100 - d.completed_pct,
            y_tokens=100 - d.tokens_pct,
            day=d,
        )
        for i, d in enumerate(days)
    ]


def polyline(points: list[ChartPoint], attr: str) -> str:
    """SVG `points` 속성 문자열. 점이 하나뿐이면 선을 그릴 수 없어 빈 문자열이다."""
    if len(points) < 2:
        return ""
    return " ".join(f"{p.x},{getattr(p, attr)}" for p in points)


@dataclass(frozen=True)
class Metrics:
    added_today: int
    added_delta: int
    completed_today: int
    completed_delta: int
    completed_total: int
    added_total: int
    tokens_today: int
    tokens_delta: int


def metrics(conn: sqlite3.Connection, days: list[TrendDay]) -> Metrics:
    """지표 다섯. `_delta` 는 어제 대비 오늘 차이다 — 숫자 하나만 보면 늘고 있는지 알 수 없다."""
    total_added = conn.execute("SELECT count(*) AS n FROM raw_jobs").fetchone()["n"]
    today = days[-1] if days else None
    yesterday = days[-2] if len(days) >= 2 else None
    return Metrics(
        added_today=today.added if today else 0,
        added_delta=(today.added - yesterday.added) if today and yesterday else 0,
        completed_today=today.completed if today else 0,
        completed_delta=(today.completed - yesterday.completed) if today and yesterday else 0,
        completed_total=completed_count(conn),
        added_total=int(total_added),
        tokens_today=today.tokens if today else 0,
        tokens_delta=(today.tokens - yesterday.tokens) if today and yesterday else 0,
    )


@dataclass(frozen=True)
class FeatureBar:
    """AI 기능 하나의 토큰 사용량 막대. `pct` 는 셋 중 최댓값 대비 비율(0~100)이고,
    호출이 있는데 반올림으로 안 보일 만큼 작아지지 않게 최소 높이를 얹었다."""

    feature: str
    label: str
    calls: int
    total_tokens: int
    pct: int


# 이 막대 그래프의 높이 하한. 실제 비율이 이보다 낮아도 0이 아니면 이 높이로 그린다 —
# 셋 중 하나가 아주 작으면 그래프에서 아예 안 보이는 막대가 된다. 선 그래프(`_pct`)는
# 점을 이어 읽어서 이 하한이 필요 없다
_MIN_BAR_PCT = 6


def _bar_pct(count: int, peak: int) -> int:
    if count == 0:
        return 0
    return max(round(count / peak * 100), _MIN_BAR_PCT)


def token_usage(conn: sqlite3.Connection) -> list[FeatureBar]:
    """기능별(셀렉터 생성·수정, 분류) 누적 토큰 사용량. `../.claude/rules/llm.md` 가 모든 호출을
    `llm_calls` 에 남기라고 정한 것이 이 그래프가 가능한 이유다."""
    usage = by_feature(conn)
    peak = max([u.total_tokens for u in usage] + [1])
    return [
        FeatureBar(
            feature=u.feature,
            label=FEATURE_LABELS.get(u.feature, u.feature),
            calls=u.calls,
            total_tokens=u.total_tokens,
            pct=_bar_pct(u.total_tokens, peak),
        )
        for u in usage
    ]


@router.get("/", response_class=HTMLResponse)
def dashboard_page(request: Request) -> HTMLResponse:
    return render_page(request, "pages/dashboard.html")


@router.get("/ui/dashboard", response_class=HTMLResponse)
def dashboard_summary_fragment(
    request: Request, conn: Annotated[sqlite3.Connection, Depends(get_connection)]
) -> HTMLResponse:
    days = trend(conn)
    points = chart_points(days)
    return render(
        request,
        "fragments/dashboard_summary.html",
        metrics=metrics(conn, days),
        trend_days=days,
        added_line=polyline(points, "y_added"),
        completed_line=polyline(points, "y_completed"),
        token_line=polyline(points, "y_tokens"),
        cards=recent_completed(conn, RECENT_LIMIT),
        quick_links=QUICK_LINKS,
        token_bars=token_usage(conn),
        cost_reference_model=COST_REFERENCE_MODEL,
    )


def _log_lines() -> list[LogLine]:
    """가장 최근 것이 먼저다. 3초마다 다시 그리는 조각이라, 새 줄이 스크롤 없이 늘
    같은 자리(맨 위)에서 보여야 훑어보기 편하다."""
    return list(reversed(_log_handler.tail()))


@router.get("/ui/dashboard/logs", response_class=HTMLResponse)
def dashboard_logs_fragment(request: Request) -> HTMLResponse:
    """최근 로그. DB 를 보지 않는다 — 이 프로세스 메모리의 버퍼 하나뿐이다."""
    return render(request, "fragments/dashboard_logs.html", lines=_log_lines())
