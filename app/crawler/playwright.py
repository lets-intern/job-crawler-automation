"""JS 로 그려지는 페이지를 브라우저로 렌더해 HTML 을 돌려준다.

정적 fetch 가 껍데기만 돌려주는 것이 측정으로 확인된 사이트에만 쓴다 (`seeds/sample-sites.json`).
기본 경로는 계속 정적이고, 렌더는 사이트별 승격이다 (`.claude/rules/crawling.md`).

## 정책은 여기서 다시 만들지 않는다

robots 확인과 호스트별 딜레이는 `app/crawler/fetcher.py` 의 `Fetcher.guard()` 가 그대로
적용한다. 이 모듈은 그 안에서 페이지를 그릴 뿐이다. 렌더 경로가 robots 를 건너뛰면
"모든 외부 요청은 공용 클라이언트를 지난다" 가 사실이 아니게 된다.

User-Agent 도 `Fetcher` 가 들고 있는 값(`CRAWL_USER_AGENT`)을 그대로 쓴다. 브라우저 기본
User-Agent 로 나가면 차단을 우회하는 것이 되고, 그것은 하지 않는다. 로그인·CAPTCHA 우회도
PRD 비목표다 — 여기서 하는 것은 렌더링뿐이다.

## 재시도하지 않는다

`Fetcher` 는 transport 실패를 백오프 재시도하지만 렌더 경로는 하지 않는다. 렌더 1회가 이미
정적 타임아웃의 몇 배를 쓰고, 실패한 렌더를 세 번 더 하면 한 실행이 실행 타임아웃을 넘겨
동시 실행 자리를 붙든다. 실패한 렌더는 다음 주기가 다시 시도한다.

## 브라우저 수명

한 실행 안에서는 브라우저 하나를 목록·상세에 재사용하고, 실행이 끝나면 닫는다. 브라우저
인스턴스 하나가 150~300MB 를 쓰기 때문에 실행 사이에 띄워 두지 않는다. `open_source()` 가
그 수명을 들고 있다.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from typing import Any

from app.config import Settings, get_settings
from app.crawler.fetcher import (
    FetchError,
    FetchPolicy,
    FetchResult,
    PageSource,
    ResponseStatusError,
)

logger = logging.getLogger(__name__)

STATIC = "static"
PLAYWRIGHT = "playwright"
RENDER_MODES: tuple[str, ...] = (STATIC, PLAYWRIGHT)

# 로드가 끝난 뒤 XHR 이 잦아들기를 기다리는 시간. 이 시간이 지나도 조용해지지 않으면 그 시점의
# DOM 을 그대로 쓴다 — 광고나 폴링 때문에 영영 조용해지지 않는 페이지가 있다.
_SETTLE_SECONDS = 5.0


class RenderError(FetchError):
    """렌더 실패. 타임아웃과 브라우저 오류가 여기 들어온다."""

    error_class = "transport"


class RenderUnavailableError(FetchError):
    """브라우저가 설치돼 있지 않다.

    transport 실패가 아니다. 사이트는 아무 잘못이 없고 재시도해도 같은 결과다. 배포에
    Chromium 이 빠진 것이므로 `error_class` 를 비우고 사유만 남긴다.
    """

    error_class = None


class Renderer:
    """렌더 경로의 `PageSource`. `Fetcher` 와 같은 자리에 꽂힌다.

    `launch` 는 테스트가 브라우저 없이 돌리기 위해 주입 가능하다. 운영에서는 Playwright 로
    Chromium 을 띄운다.
    """

    def __init__(
        self,
        fetcher: FetchPolicy,
        *,
        settings: Settings | None = None,
        launch: Callable[[], Any] | None = None,
    ) -> None:
        resolved = settings or get_settings()
        self._fetcher = fetcher
        self._timeout = resolved.render_timeout_seconds
        self._launch = launch or _launch_chromium
        self._playwright: Any | None = None
        self._browser: Any | None = None

    async def fetch(self, url: str) -> FetchResult:
        """robots 와 딜레이를 통과한 URL 만 렌더한다.

        `Fetcher.fetch()` 와 같은 값을 돌려준다. 러너와 파서는 어느 경로로 왔는지 모른다.
        """
        async with self._fetcher.guard(url):
            return await self._render(url)

    async def aclose(self) -> None:
        """브라우저를 닫는다. 두 번 불러도 안전하다."""
        browser, self._browser = self._browser, None
        playwright, self._playwright = self._playwright, None
        if browser is not None:
            with suppress(Exception):
                await browser.close()
        if playwright is not None:
            with suppress(Exception):
                await playwright.stop()

    async def _render(self, url: str) -> FetchResult:
        browser = await self._browser_instance()
        timeout_ms = int(self._timeout * 1000)
        try:
            async with asyncio.timeout(self._timeout):
                context = await browser.new_context(user_agent=self._fetcher.user_agent)
                try:
                    page = await context.new_page()
                    response = await page.goto(
                        url, wait_until="domcontentloaded", timeout=timeout_ms
                    )
                    await _settle(page)
                    html = await page.content()
                    final_url = page.url
                finally:
                    with suppress(Exception):
                        await context.close()
        except TimeoutError as exc:
            # 어디까지 갔는지 알 수 없는 브라우저를 다음 페이지에 재사용하지 않는다.
            await self.aclose()
            raise RenderError(f"렌더가 시간 제한 {self._timeout}초를 넘겼다: {url}") from exc
        except FetchError:
            raise
        except Exception as exc:
            await self.aclose()
            raise RenderError(f"렌더 실패({type(exc).__name__}): {url}") from exc

        status = _status(response)
        if status >= 400:
            # 정적 경로와 같은 판정이다. 4xx·5xx 는 렌더된 껍데기가 아니라 실패다
            raise ResponseStatusError(f"응답 {status}: {url}", status)

        logger.info("렌더 완료 url=%s status=%s chars=%d", url, status, len(html))
        return FetchResult(url=final_url or url, status_code=status, text=html)

    async def _browser_instance(self) -> Any:
        """한 실행 안에서 브라우저 하나를 재사용한다. 페이지마다 새로 띄우지 않는다."""
        if self._browser is None:
            self._playwright, self._browser = await self._launch()
        return self._browser


async def _settle(page: Any) -> None:
    """XHR 이 잦아들 때까지만 기다린다. 안 잦아들어도 실패로 보지 않는다."""
    with suppress(Exception):
        await page.wait_for_load_state("networkidle", timeout=int(_SETTLE_SECONDS * 1000))


def _status(response: Any) -> int:
    """네비게이션 응답의 상태 코드. 응답 자체가 없으면 판정하지 않고 0 으로 둔다."""
    if response is None:
        return 0
    value = getattr(response, "status", None)
    return int(value) if value is not None else 0


async def _launch_chromium() -> tuple[Any, Any]:
    """운영 경로. 임포트를 함수 안에서 하는 이유는 정적 실행만 하는 배포에서 Playwright 가
    없어도 앱이 뜨게 하기 위해서다."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RenderUnavailableError(
            "playwright 패키지가 없다. 렌더 모드는 Chromium 이 설치된 이미지에서만 된다"
        ) from exc

    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.launch(headless=True)
    except Exception as exc:
        await playwright.stop()
        raise RenderUnavailableError(f"Chromium 을 띄우지 못했다: {exc}") from exc
    return playwright, browser


@asynccontextmanager
async def open_source(
    render_mode: str | None,
    fetcher: FetchPolicy,
    *,
    renderer: Callable[[FetchPolicy], Renderer] | None = None,
) -> AsyncIterator[PageSource]:
    """이 실행이 쓸 `PageSource` 를 고른다. 브라우저 수명이 이 블록이다.

    `render_mode` 가 `playwright` 인 경우에만 브라우저를 띄운다. 값이 없거나 모르는 값이면
    정적이다 — 렌더는 운영자가 명시적으로 올린 사이트만 받는다.
    """
    if render_mode != PLAYWRIGHT:
        yield fetcher
        return

    build = renderer or (lambda client: Renderer(client))
    instance = build(fetcher)
    try:
        yield instance
    finally:
        await instance.aclose()
