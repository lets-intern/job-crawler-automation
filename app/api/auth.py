"""운영 화면과 API 에 거는 자물쇠 하나.

계정도 사용자도 역할도 만들지 않는다. PRD 비목표의 "다중 사용자 권한/인증 체계" 는 그대로
비목표다 (`.claude/rules/core.md`). 운영자 한 명이 쓰는 화면에 비밀번호 하나를 받는 잠금을
달 뿐이다 — 공개 URL 에 떠 있는 동안 주소를 아는 누구나 DB 를 통째로 내려받고 크롤러를 지울
수 있기 때문이다.

잠그는 기준은 "열어 둔 것 말고 전부" 다. 새 라우트가 생겨도 기본이 잠김이라, 여기 목록에
적는 것을 잊어서 열린 채로 나가는 경로가 없다.

`/health` 만은 잠그지 않는다. Coolify 가 이 응답으로 배포 성공을 판정한다 — 막으면 배포가
실패한다.

쿠키는 서명한다. 서명하지 않으면 값을 지어내서 넣는 것으로 잠금이 통째로 없는 것과 같아진다.
서명 키는 비밀번호에서 파생한다. 별도의 SECRET_KEY 를 두지 않아 설정이 하나로 끝나고,
비밀번호를 바꾸면 이미 나간 쿠키가 전부 무효가 된다.

비밀번호는 로그·응답·템플릿 어디에도 남기지 않는다. 틀렸을 때 무엇이 틀렸는지도 알려 주지
않는다.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.api.ui import render_page, templates
from app.config import get_settings

logger = logging.getLogger(__name__)

# 환경변수를 두지 않았을 때 쓰는 값. 이 값을 쓰고 있으면 화면과 기동 로그가 그렇다고 말한다
DEFAULT_PASSWORD = "1234"

COOKIE_NAME = "admin_session"
# 쿠키 수명. 운영자 한 명이 쓰는 화면이라 매번 다시 묻지 않는다
MAX_AGE_SECONDS = 14 * 24 * 60 * 60
# 서명이 맞아도 이만큼 미래에 발급된 것은 받지 않는다. 서버 시계가 조금 흔들리는 것만 봐준다
CLOCK_SKEW_SECONDS = 60

# 잠그지 않는 경로. 이 집합 밖은 전부 잠긴다
#   /health  Coolify 의 배포 판정. 막으면 배포가 실패한다
#   /login   잠긴 문을 여는 자리
#   /logout  잠금을 푸는 자리. 잠겨 있어도 부를 수 있어야 되돌이가 생기지 않는다
PUBLIC_PATHS = frozenset({"/health", "/login", "/logout"})


def admin_password_is_default() -> bool:
    """기본 비밀번호로 떠 있는가. 화면 경고와 기동 로그가 이것을 본다."""
    return get_settings().admin_password == DEFAULT_PASSWORD


def _signing_key() -> bytes:
    """비밀번호에서 서명 키를 만든다. 비밀번호가 바뀌면 나간 쿠키가 전부 무효가 된다."""
    password = get_settings().admin_password
    return hashlib.sha256(f"job-crawler-admin-v1:{password}".encode()).digest()


def _sign(payload: str) -> str:
    digest = hmac.new(_signing_key(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def issue_token() -> str:
    """발급 시각과 그 서명. 서명 키가 없으면 만들어 낼 수 없다."""
    issued = str(int(time.time()))
    return f"{issued}.{_sign(issued)}"


def token_is_valid(token: str | None) -> bool:
    if not token:
        return False
    issued, separator, signature = token.partition(".")
    if not separator or not signature:
        return False
    # 서명부터 본다. 여기서 걸리면 지어낸 값이다.
    # 바이트로 견준다 — compare_digest 는 ASCII 밖의 글자가 든 str 에 TypeError 를 낸다.
    # 쿠키 값은 밖에서 오는 것이라 무엇이든 들어올 수 있다
    if not hmac.compare_digest(signature.encode(), _sign(issued).encode()):
        return False
    try:
        age = time.time() - int(issued)
    except ValueError:
        return False
    return -CLOCK_SKEW_SECONDS <= age <= MAX_AGE_SECONDS


def password_matches(supplied: str) -> bool:
    # 바이트로 견준다. 한글이 든 비밀번호를 str 로 견주면 TypeError 로 로그인이 500 이 된다
    return hmac.compare_digest(supplied.encode(), get_settings().admin_password.encode())


def is_authenticated(request: Request) -> bool:
    return token_is_valid(request.cookies.get(COOKIE_NAME))


def _is_https(request: Request) -> bool:
    """프록시 뒤에서도 원래 스킴을 본다. Coolify 가 TLS 를 끊고 평문으로 넘긴다."""
    if request.url.scheme == "https":
        return True
    forwarded = request.headers.get("x-forwarded-proto", "")
    return forwarded.split(",")[0].strip() == "https"


def _set_session_cookie(request: Request, response: Response) -> None:
    response.set_cookie(
        COOKIE_NAME,
        issue_token(),
        max_age=MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=_is_https(request),
        path="/",
    )


def _safe_next(raw: str) -> str:
    """돌아갈 자리는 이 서버 안의 경로만 받는다. 남의 주소로 튕겨 보내지 않는다."""
    if not raw.startswith("/") or raw.startswith("//"):
        return "/"
    return raw


router = APIRouter(tags=["auth"], include_in_schema=False)


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/") -> Response:
    if is_authenticated(request):
        return RedirectResponse(_safe_next(next), status_code=303)
    return render_page(request, "pages/login.html", next=_safe_next(next))


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    password: Annotated[str, Form()],
    next: Annotated[str, Form()] = "/",
) -> Response:
    target = _safe_next(next)
    if not password_matches(password):
        # 무엇이 틀렸는지 말하지 않는다. 시도한 값도 남기지 않는다
        logger.warning("운영 화면 로그인 실패")
        response = render_page(request, "pages/login.html", next=target, failed=True)
        response.status_code = 401
        return response
    redirect = RedirectResponse(target, status_code=303)
    _set_session_cookie(request, redirect)
    return redirect


@router.post("/logout")
def logout() -> Response:
    redirect = RedirectResponse("/login", status_code=303)
    redirect.delete_cookie(COOKIE_NAME, path="/")
    return redirect


def _denied(request: Request) -> Response:
    """잠긴 것을 부른 쪽이 알아들을 수 있는 모양으로 거절한다."""
    # HTMX 는 리다이렉트를 따라가서 로그인 화면을 조각 자리에 갈아 넣는다. 헤더로 화면을
    # 통째로 옮기게 한다
    if request.headers.get("hx-request"):
        return Response(status_code=401, headers={"HX-Redirect": "/login"})
    if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
        target = request.url.path
        if request.url.query:
            target = f"{target}?{request.url.query}"
        return RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303)
    return JSONResponse({"detail": "인증이 필요하다"}, status_code=401)


def install_auth(app: FastAPI) -> None:
    """잠금을 앱에 건다. 라우트 등록이 끝난 뒤 `app/main.py` 가 한 번 부른다."""
    app.include_router(router)
    # 화면이 기본 비밀번호 경고를 그릴 때 본다. 값은 넘기지 않는다 — 쓰고 있는지 여부만이다
    templates.env.globals["admin_password_is_default"] = admin_password_is_default

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in PUBLIC_PATHS or is_authenticated(request):
            return await call_next(request)
        return _denied(request)
