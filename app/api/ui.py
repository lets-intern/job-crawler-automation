"""운영 화면의 베이스. 레이아웃·네비게이션과 페이지 라우트가 여기 있다.

서버가 HTML 을 렌더하고 HTMX 가 조각만 갈아 끼운다. 빌드 단계도, 번들러도, 클라이언트 상태
저장소도 없다 (`.claude/docs/tech-stack.md`).

스타일은 Tailwind 를 CDN 에서 받아 클래스로만 준다 (2026-08-22 결정, Push 9 이 Push 6 의
"CSS 없음" 결정을 대체한다). 빌드 단계를 만들지 않는 제약이 그대로라 CLI·PostCSS 파이프라인은
두지 않는다 (`.claude/rules/core.md`). 서빙할 자산이 없으니 정적 파일 마운트도 없다 —
HTMX 와 Tailwind 둘 다 CDN 에서 받는다.

페이지 라우트는 페이지를, 조각 라우트는 조각만 돌려준다. 한 라우트가 헤더를 보고 둘 중 무엇을
원했는지 추측하게 만들지 않는다 (`.claude/agents/ui-worker.md`).

화면은 이미 있는 API 라우터를 그대로 부른다. 같은 동작을 하는 두 번째 경로를 만들지 않는다 —
그렇게 갈라지면 화면에서 되는 일이 API 에서 안 되는 상태가 생긴다.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, tzinfo
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from app.config import get_settings

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 네비게이션. 경로와 이름은 여기 한 곳에서만 정한다
NAV: tuple[tuple[str, str], ...] = (
    ("/", "크롤러 등록"),
    ("/tests", "테스트 실행"),
    ("/workflows", "워크플로우"),
    ("/rules", "정규화 규칙"),
    ("/jobs", "데이터 조회"),
    ("/review", "데이터 검수"),
    ("/settings", "운영 설정"),
)

router = APIRouter(tags=["ui"], include_in_schema=False)


def render(request: Request, name: str, /, **context: Any) -> HTMLResponse:
    """조각 하나를 렌더한다. 조각은 레이아웃을 상속하지 않는다."""
    return templates.TemplateResponse(request, name, context)


def render_page(request: Request, name: str, /, **context: Any) -> HTMLResponse:
    """페이지 하나를 렌더한다. 네비게이션과 현재 위치는 여기서 채운다."""
    return templates.TemplateResponse(
        request, name, {"nav": NAV, "active": request.url.path, **context}
    )


# 실패 사유별 다음 행동. "500 Internal Server Error" 는 운영자가 할 수 있는 것을 말해 주지
# 않는다. 사유를 아는 만큼은 여기서 다음 수를 적는다
NEXT_STEPS: dict[str, str] = {
    "robots": "robots.txt 가 막은 경로다. 다른 URL 을 쓰거나 사이트에 문의한다",
    "transport": "사이트에 닿지 못했다. URL 과 사이트 상태를 확인하고 다시 시도한다",
    "selector_miss": "가져오기는 됐는데 셀렉터가 아무것도 잡지 못했다. 셀렉터를 손으로 고친다",
    "parse": "잡기는 했는데 값을 읽지 못했다. 그 필드의 셀렉터만 고친다",
    "list_not_found": "정적 HTML 에 목록이 없다. 렌더(Playwright) 방식으로 올려 다시 생성한다",
    "no_api_key": "GEMINI_API_KEY 가 비어 있다. 환경변수를 채우면 생성만 다시 된다",
    "api_error": "생성 모델 호출이 실패했다. 잠시 뒤 다시 생성한다",
    "unparsable": "모델 응답이 JSON 이 아니었다. 셀렉터를 손으로 쓴다",
    "missing_field": "모델 응답에 필요한 필드가 없다. 셀렉터를 손으로 쓴다",
    "unknown_field": "모델이 스키마에 없는 필드를 냈다. 셀렉터를 손으로 쓴다",
    "not_found": "그 행이 없다. 목록을 다시 불러 확인한다",
    "invalid_input": "보낸 값이 형식에 맞지 않는다. 표시된 항목을 고쳐 다시 보낸다",
    "server_error": "서버가 처리하지 못했다. 서버 로그에 자세한 내용이 남는다",
}


@lru_cache(maxsize=8)
def _zone(name: str) -> tzinfo:
    """이름으로 시간대를 찾는다. 못 찾으면 UTC 다 — 화면이 죽는 것보다 낫다."""
    if not name:
        return UTC
    try:
        return ZoneInfo(name)
    except (KeyError, ValueError, OSError):
        # 설정이 틀렸다. 화면은 계속 뜨고, 값 옆의 `UTC` 가 그 사실을 말한다
        logger.warning("DISPLAY_TIMEZONE 을 찾지 못했다: %r. UTC 로 그린다", name)
        return UTC


def display_zone() -> tzinfo:
    """화면에 시각을 그릴 때 쓰는 시간대. 설정에서 오고 기본값은 `Asia/Seoul` 이다."""
    return _zone(get_settings().display_timezone)


def format_time(value: Any) -> str:
    """저장된 UTC 시각을 운영자가 사는 시간대의 문자열로 바꾼다.

    DB 는 `datetime('now')` 로 UTC 를 초까지 넣고(시간대 표시가 없다), 재정규화 진행과
    스케줄러는 시간대가 붙은 ISO 문자열을 넣는다. 둘 다 받아 한 형식으로 낸다.

    저장된 값은 UTC 그대로 둔다. 바꾸는 것은 화면에 그리는 이 순간뿐이다 —
    `normalized_at` 은 제공 API 의 폴링 커서라 값이 밀리면 소비 측의 커서가 어긋난다
    (`.claude/docs/api-contract.md`).

    시간대 약칭(`KST`)을 값에 붙인다. 어느 시간대인지 적혀 있지 않으면 UTC 였던 시절의
    9시간 차이를 볼 때마다 다시 의심하게 된다.

    값이 없으면 빈 문자열이다. 읽지 못한 값은 예외 없이 원문 그대로 돌려준다 — 화면 하나가
    통째로 죽는 것보다 낫다.
    """
    if not value:
        return ""
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text
    if parsed.tzinfo is None:
        # 저장 형식(`YYYY-MM-DD HH:MM:SS`)에는 시간대가 없다. SQLite 가 UTC 로 찍은 값이다
        parsed = parsed.replace(tzinfo=UTC)
    shown = parsed.astimezone(display_zone())
    return f"{shown.strftime('%Y-%m-%d %H:%M:%S')} {shown.strftime('%Z')}".strip()


def next_step(reason: str) -> str:
    """그 실패에서 운영자가 할 수 있는 다음 행동. 모르는 사유면 빈 문자열이다."""
    return NEXT_STEPS.get(reason, "")


# 라우트가 자기 조각에 직접 렌더하는 실패에도 같은 문구가 붙게 한다
templates.env.globals["next_step"] = next_step
templates.env.filters["as_time"] = format_time


def render_error(request: Request, reason: str, message: str) -> HTMLResponse:
    """실패 조각. 200 으로 돌려준다 — 4xx·5xx 는 HTMX 가 갈아 끼우지 않아 화면이 조용해진다."""
    return templates.TemplateResponse(
        request,
        "fragments/error.html",
        {"error": {"reason": reason, "message": message, "next": NEXT_STEPS.get(reason, "")}},
    )


def _detail_text(detail: Any) -> tuple[str, str]:
    if isinstance(detail, dict):
        return str(detail.get("reason", "server_error")), str(detail.get("message", detail))
    return "invalid_input", str(detail)


def install_ui_error_handlers(app: FastAPI) -> None:
    """`/ui/` 조각 요청의 실패를 200 과 오류 조각으로 바꾼다.

    라우트마다 이미 잡아 둔 실패는 그 자리에서 렌더된다. 여기는 그물이다 — 폼 검증(422),
    예상 못 한 예외(500)처럼 라우트를 지나쳐 버리는 실패가 화면에 아무것도 남기지 않는 것을
    막는다. `/api/...` 의 상태 코드는 그대로다. 소비 측과 스크립트가 그것을 읽는다.
    """

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> Response:
        if not request.url.path.startswith("/ui/"):
            return await request_validation_exception_handler(request, exc)
        fields = ", ".join(str(error.get("loc", ("",))[-1]) for error in exc.errors())
        return render_error(request, "invalid_input", f"보낸 값을 읽지 못했다: {fields}")

    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException) -> Response:
        if not request.url.path.startswith("/ui/"):
            return await http_exception_handler(request, exc)
        reason, message = _detail_text(exc.detail)
        return render_error(request, reason, message)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> Response:
        if not request.url.path.startswith("/ui/"):
            raise exc
        # 진짜 서버 결함이다. 화면에는 사유를 남기고, 자세한 것은 로그에 남는다
        return render_error(request, "server_error", f"{type(exc).__name__}: {exc}")


@router.get("/", response_class=HTMLResponse)
def crawlers_page(request: Request) -> HTMLResponse:
    return render_page(request, "pages/crawlers.html")


@router.get("/tests", response_class=HTMLResponse)
def tests_page(request: Request) -> HTMLResponse:
    return render_page(request, "pages/tests.html")


@router.get("/workflows", response_class=HTMLResponse)
def workflows_page(request: Request) -> HTMLResponse:
    return render_page(request, "pages/workflows.html")


@router.get("/rules", response_class=HTMLResponse)
def rules_page(request: Request) -> HTMLResponse:
    return render_page(request, "pages/rules.html")


@router.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request) -> HTMLResponse:
    return render_page(request, "pages/jobs.html")


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request) -> HTMLResponse:
    return render_page(request, "pages/settings.html")


@router.get("/ui/health", response_class=HTMLResponse)
def health_fragment(request: Request) -> HTMLResponse:
    """모든 페이지 하단이 로드 직후 이 조각으로 갈린다. HTMX 가 붙었는지 화면에서 바로 보인다."""
    return render(
        request,
        "fragments/health.html",
        checked_at=datetime.now(UTC),
    )
