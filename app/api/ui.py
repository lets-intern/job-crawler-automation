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

import json
import logging
from dataclasses import dataclass
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
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.crawler.collect import API
from app.crawler.playwright import PLAYWRIGHT, STATIC
from app.selector.api_schema import ApiConfig, ApiConfigError, parse_api_config
from app.selector.schema import SelectorSchemaError, SelectorSet, validate_selectors

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 네비게이션. 경로와 이름은 여기 한 곳에서만 정한다
NAV: tuple[tuple[str, str], ...] = (
    ("/", "크롤러 등록"),
    ("/tests", "테스트 실행"),
    ("/workflows", "워크플로우"),
    ("/rules", "정규화 규칙"),
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
    "list_empty": "목록에서 반복 항목을 하나도 잡지 못했다. 목록 셀렉터를 고친다",
    "detail_unreachable": "상세에 가지 못했다. 크롤러를 다시 등록해 상세로 가는 길을 찾는다",
    "detail_empty": "상세는 열렸는데 본문이 비었다. 상세의 본문 셀렉터만 고친다",
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


# 실패 사유를 사람이 읽는 낱말로. 저장값은 그대로 영어다 (`.claude/rules/writing.md`).
# 사유를 모르는 실패는 `분류 없음` 이다 — 모르는 실패를 아는 실패로 위장하면 그 사이트를
# 계속 잘못 고치게 된다 (`migrations/0010_run_failures.sql`)
REASON_WORDS: dict[str, str] = {
    "transport": "사이트에 못 닿음",
    "selector_miss": "셀렉터가 빗나감",
    "parse": "값을 못 읽음",
    "list_empty": "목록이 비었음",
    "detail_unreachable": "상세에 못 감",
    "detail_empty": "본문이 비었음",
}
UNKNOWN_REASON_WORD = "분류 없음"


def reason_word(reason: str) -> str:
    """실패 사유 하나의 낱말. 모르는 값이면 `분류 없음` 이다."""
    return REASON_WORDS.get(reason, UNKNOWN_REASON_WORD)


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


# 사람이 읽는 자리에는 단어로 적는다. 저장값은 그대로 영어다 (`.claude/rules/writing.md`).
# 크롤러 등록 화면과 테스트 실행 화면이 같은 값을 다른 말로 적던 자리라, 매핑을 여기 하나만
# 두고 모든 템플릿이 쓰게 한다
MODE_WORDS: dict[str, str] = {STATIC: "정적", PLAYWRIGHT: "렌더"}


def mode_word(mode: str) -> str:
    """모드 이름 하나. 모르는 값이면 저장된 값을 그대로 보여준다."""
    return MODE_WORDS.get(mode, mode)


# 크롤러 하나가 어떤 방식으로 도는지를 적는 낱말. 저장값(`static`/`api`/`playwright`)은 그대로
# 두고 사람이 읽는 자리에만 이 말을 쓴다 (`.claude/tasks/done/fill-body/prd-fill-body.md` 5절).
LIST_WORDS: dict[str, str] = {API: "목록 API", PLAYWRIGHT: "목록 렌더", STATIC: "정적 목록"}
DETAIL_API_WORD = "상세 API"
# 항목의 `a[href]` 를 그대로 따라간다
DETAIL_LINK_WORD = "링크"
# 항목의 값으로 주소를 조립한다 (`link_template` 의 `{id}` 나 `{속성이름}`)
DETAIL_TEMPLATE_WORD = "항목 속성"
# 목록 항목에 상세로 갈 값이 없다. 실패가 아니라 그런 크롤러라는 사실이다
DETAIL_NONE_WORD = "상세 없음"
UNKNOWN_PATH_WORD = "알 수 없음"


@dataclass(frozen=True)
class PathView:
    """크롤러 하나가 목록과 상세를 얻는 법. 판정은 여기 오기 전에 끝나 있다.

    `*_note` 는 낱말 옆에 적는 실제 값이다 — 엔드포인트, 주소 형식, 셀렉터. 낱말만 적으면
    두 크롤러가 같은 낱말을 달고도 서로 다른 곳을 부르는 것을 화면에서 구분할 수 없다.

    `checked_at` 은 저장된 UTC 문자열 그대로다. 시간대 변환은 템플릿의 `as_time` 이 한다.
    """

    list_mode: str
    list_word: str
    list_note: str
    detail_mode: str
    detail_word: str
    detail_note: str
    checked_at: str = ""
    checked_note: str = ""


def _api_endpoint(section: Any) -> str:
    return f"{section.method} {section.url}"


def _list_path(list_mode: str, list_url: str, config: ApiConfig | None) -> str:
    """목록을 어디서 얻는지 한 줄. `api` 면 엔드포인트, 아니면 목록 주소다."""
    if list_mode != API:
        return list_url
    if config is None or config.list is None:
        return "목록 API 설정이 없다. 이 크롤러는 목록을 가져오지 못한다"
    return _api_endpoint(config.list)


def _detail_path(
    detail_mode: str,
    config: ApiConfig | None,
    selectors: SelectorSet | None,
    list_mode: str,
) -> tuple[str, str]:
    """상세로 가는 법. 낱말과 그 근거가 되는 실제 값을 함께 돌려준다."""
    if detail_mode == API:
        if config is None or config.detail is None:
            return DETAIL_API_WORD, "상세 API 설정이 없다. 이 크롤러는 상세를 가져오지 못한다"
        return DETAIL_API_WORD, _api_endpoint(config.detail)

    # 상세가 문서다. 그 주소를 항목에서 어떻게 얻는지가 남은 갈림길이다
    if list_mode == API:
        if config is None or config.list is None:
            return UNKNOWN_PATH_WORD, "목록 API 설정이 없어 상세 주소를 만들 수 없다"
        return DETAIL_TEMPLATE_WORD, config.list.link_template
    if selectors is None:
        return UNKNOWN_PATH_WORD, "셀렉터를 읽지 못했다. 셀렉터 편집에서 확인한다"
    if selectors.list.link_template.strip():
        return DETAIL_TEMPLATE_WORD, selectors.list.link_template
    if selectors.list.link.strip():
        return DETAIL_LINK_WORD, f"항목의 {selectors.list.link} 가 가리키는 주소"
    return DETAIL_NONE_WORD, "목록 항목에 상세로 갈 값이 없다. 본문은 채워지지 않는다"


def describe_path(
    *,
    list_mode: str,
    detail_mode: str,
    list_url: str = "",
    api_config_json: str | None = None,
    selectors_json: str | None = None,
    checked_at: str = "",
    checked_note: str = "",
) -> PathView:
    """저장된 값 하나로 경로를 낱말로 옮긴다. 읽지 못한 설정은 그 사실을 적는다.

    설정이 깨져 있어도 화면은 뜬다. 못 읽었다는 사실이 낱말 자리에 그대로 적히고, 그것이
    "설정이 없다" 와 "화면이 안 그린다" 를 가른다.
    """
    try:
        config: ApiConfig | None = parse_api_config(api_config_json)
    except ApiConfigError as exc:
        config = None
        broken = f"API 설정을 읽지 못했다: {exc}"
        return PathView(
            list_mode=list_mode,
            list_word=LIST_WORDS.get(list_mode, list_mode),
            list_note=broken if list_mode == API else list_url,
            detail_mode=detail_mode,
            detail_word=UNKNOWN_PATH_WORD,
            detail_note=broken,
            checked_at=checked_at,
            checked_note=checked_note,
        )

    selectors: SelectorSet | None = None
    if selectors_json:
        try:
            selectors = validate_selectors(json.loads(selectors_json))
        except (json.JSONDecodeError, SelectorSchemaError):
            selectors = None

    detail_word, detail_note = _detail_path(detail_mode, config, selectors, list_mode)
    return PathView(
        list_mode=list_mode,
        list_word=LIST_WORDS.get(list_mode, list_mode),
        list_note=_list_path(list_mode, list_url, config),
        detail_mode=detail_mode,
        detail_word=detail_word,
        detail_note=detail_note,
        checked_at=checked_at,
        checked_note=checked_note,
    )


# 라우트가 자기 조각에 직접 렌더하는 실패에도 같은 문구가 붙게 한다
templates.env.globals["next_step"] = next_step
templates.env.globals["mode_word"] = mode_word
templates.env.globals["reason_word"] = reason_word
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


@router.get("/jobs")
def jobs_page() -> RedirectResponse:
    """옛 데이터 조회 주소. 합쳐진 데이터 검수 화면으로 보낸다 (Push 30).

    두 화면이 같은 데이터를 두 벌로 보여주던 것을 하나로 합쳤다. 주소를 없애 404 로 두면
    운영자의 북마크와 지난 작업 기록의 링크가 전부 죽는다.

    영구 이동(301·308)으로 두지 않는다. 브라우저가 그것을 캐시하면 주소를 되돌릴 때 사용자
    쪽에서 지울 방법이 없다.
    """
    return RedirectResponse("/review", status_code=307)


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
