"""운영 화면의 베이스. 레이아웃·네비게이션과 페이지 라우트가 여기 있다.

서버가 HTML 을 렌더하고 HTMX 가 조각만 갈아 끼운다. 빌드 단계도, 번들러도, 클라이언트 상태
저장소도 없다 (`.claude/docs/tech-stack.md`).

CSS 를 만들지 않는다 (2026-08-22 결정). 스타일시트 파일도, `<style>` 블록도, 인라인 `style`
속성도, 클래스 기반 디자인도 두지 않는다. 구조는 `table`, `form`, `fieldset`, `details`, 제목
레벨 같은 태그 자체로 만든다. 서빙할 자산이 없으니 정적 파일 마운트도 만들지 않는다 —
HTMX 는 CDN 에서 무결성 해시와 함께 받는다.

페이지 라우트는 페이지를, 조각 라우트는 조각만 돌려준다. 한 라우트가 헤더를 보고 둘 중 무엇을
원했는지 추측하게 만들지 않는다 (`.claude/agents/ui-worker.md`).

화면은 이미 있는 API 라우터를 그대로 부른다. 같은 동작을 하는 두 번째 경로를 만들지 않는다 —
그렇게 갈라지면 화면에서 되는 일이 API 에서 안 되는 상태가 생긴다.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 네비게이션. 경로와 이름은 여기 한 곳에서만 정한다
NAV: tuple[tuple[str, str], ...] = (
    ("/", "크롤러 등록"),
    ("/tests", "테스트 실행"),
    ("/workflows", "워크플로우"),
    ("/rules", "정규화 규칙"),
    ("/jobs", "데이터 조회"),
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
        checked_at=datetime.now().strftime("%H:%M:%S"),
    )
