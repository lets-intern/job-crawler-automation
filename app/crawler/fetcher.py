"""공용 fetch 클라이언트. 이 레포에서 밖으로 나가는 요청은 전부 여기를 지난다.

`.claude/rules/crawling.md` 가 정한 것을 그대로 담는다.

- User-Agent 는 설정값 그대로 쓴다. 브라우저 위장은 하지 않는다
- 같은 호스트로 가는 요청 사이에 최소 딜레이를 실제로 기다린다
- 첫 요청 전에 robots.txt 를 확인하고, disallow 면 대상 요청을 보내지 않고 실패한다
- transport 실패(타임아웃, 연결 끊김, 5xx)만 백오프 재시도한다. 4xx 는 재시도하지 않는다

호스트별 딜레이는 인스턴스가 하나일 때만 사실이다. 호출부는 `get_fetcher()` 를 쓴다.

리다이렉트는 따라간다. 리다이렉트로 다른 호스트에 도착한 경우의 robots 재확인은 하지 않는다 —
지금 필요한 곳이 없다.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.config import Settings, get_settings

_BACKOFF_BASE_SECONDS = 1.0
_ROBOTS_PATH = "/robots.txt"


class FetchError(Exception):
    """fetch 실패의 공통 타입.

    `error_class` 는 `crawl_runs.error_class` 에 그대로 들어간다. 이 모듈에서 나올 수 있는 값은
    `transport` 뿐이다. `selector_miss` 와 `parse` 는 파서가 판정한다.
    """

    error_class: str | None = "transport"


class TransportError(FetchError):
    """타임아웃, 연결 끊김, 5xx. 재시도를 다 쓰고도 실패한 것만 올라온다."""


class ResponseStatusError(FetchError):
    """재시도하지 않는 응답 상태(4xx). 4초 뒤에 다시 물어도 같은 답이 온다."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class RobotsDisallowedError(FetchError):
    """robots.txt 가 막은 경로. 대상 URL 로는 요청이 나가지 않았다."""


@dataclass(frozen=True)
class FetchResult:
    url: str
    status_code: int
    text: str


class PageSource(Protocol):
    """URL 하나를 HTML 로 바꿔 주는 것. `Fetcher` 와 렌더러가 둘 다 이 모양이다.

    실행 경로가 정적인지 렌더인지는 `crawlers.render_mode` 가 정하고, 그 뒤로는 같은 코드가
    돈다. 파서와 러너는 어느 쪽이 왔는지 알 필요가 없다.
    """

    async def fetch(self, url: str) -> FetchResult: ...


class FetchPolicy(PageSource, Protocol):
    """정책을 들고 있는 쪽. 렌더 경로가 이것을 받아 같은 robots·딜레이·이름 아래에서 돈다."""

    @property
    def user_agent(self) -> str: ...

    def guard(self, url: str) -> AbstractAsyncContextManager[None]: ...


class Fetcher:
    """유일한 외부 요청 경로.

    `clock` 과 `sleep` 은 테스트가 실제로 기다리지 않게 하려고 주입 가능하다. 운영에서는
    `time.monotonic` 과 `asyncio.sleep` 을 쓴다.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        resolved = settings or get_settings()
        self._user_agent = resolved.crawl_user_agent
        self._delay_seconds = resolved.crawl_delay_seconds
        self._max_retries = resolved.crawl_max_retries
        self._clock = clock or time.monotonic
        self._sleep = sleep or asyncio.sleep
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(resolved.crawl_timeout_seconds),
            headers={"User-Agent": self._user_agent},
            follow_redirects=True,
        )
        self._last_request_at: dict[str, float] = {}
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._robots: dict[str, RobotFileParser | None] = {}

    async def fetch(self, url: str) -> FetchResult:
        """robots 확인을 통과한 URL 만 가져온다. 실패는 `FetchError` 로 올라온다."""
        await self._ensure_allowed(url)
        return await self._send(url)

    @property
    def user_agent(self) -> str:
        """렌더 경로가 같은 이름으로 나가기 위해 읽는다. 브라우저 위장은 하지 않는다."""
        return self._user_agent

    @asynccontextmanager
    async def guard(self, url: str) -> AsyncIterator[None]:
        """httpx 로 가져오지 않는 요청에 같은 정책을 씌운다. 렌더 경로가 쓴다.

        `fetch()` 와 순서가 같다 — robots 확인, 호스트 잠금, 딜레이. 잠금은 렌더가 끝날 때까지
        잡고 있는다. 렌더 중에 같은 호스트로 정적 요청이 나가면 딜레이가 사실이 아니게 된다.

        브라우저는 페이지 하나를 그리며 같은 호스트로 여러 요청을 낸다. 그래서 다음 요청까지의
        간격은 렌더가 시작한 시점이 아니라 끝난 시점부터 센다.
        """
        await self._ensure_allowed(url)
        host = urlsplit(url).netloc
        async with self._lock_for(host):
            await self._respect_delay(host)
            try:
                yield
            finally:
                self._last_request_at[host] = self._clock()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _ensure_allowed(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise FetchError(f"가져올 수 없는 URL 이다: {url}")

        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            # 판정을 얻지 못하면 캐시하지 않는다. robots 를 모르는 채로 대상에 요청하지 않는다.
            self._robots[origin] = await self._load_robots(origin)

        rules = self._robots[origin]
        if rules is not None and not rules.can_fetch(self._user_agent, url):
            raise RobotsDisallowedError(f"robots.txt 가 막은 경로다: {url}")

    async def _load_robots(self, origin: str) -> RobotFileParser | None:
        """robots.txt 를 읽어 파서를 만든다. 4xx(없음·차단)면 규칙 없음으로 본다.

        가져오지 못한 경우(transport 실패)는 `TransportError` 가 그대로 올라간다. 확인하지 못한
        것을 허용으로 바꿔 읽지 않는다.
        """
        try:
            result = await self._send(origin + _ROBOTS_PATH)
        except ResponseStatusError:
            return None

        rules = RobotFileParser()
        rules.parse(result.text.splitlines())
        return rules

    async def _send(self, url: str) -> FetchResult:
        host = urlsplit(url).netloc
        last_error: FetchError | None = None

        async with self._lock_for(host):
            for attempt in range(self._max_retries + 1):
                if attempt:
                    await self._sleep(_BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))
                await self._respect_delay(host)

                try:
                    response = await self._client.get(url)
                except httpx.TransportError as exc:
                    last_error = TransportError(f"전송 실패({type(exc).__name__}): {url}")
                    continue

                if response.status_code < 400:
                    return FetchResult(
                        url=str(response.url),
                        status_code=response.status_code,
                        text=response.text,
                    )
                if response.status_code < 500:
                    raise ResponseStatusError(
                        f"응답 {response.status_code}: {url}", response.status_code
                    )
                last_error = TransportError(f"서버 오류 {response.status_code}: {url}")

        assert last_error is not None  # 루프는 최소 한 번 돈다
        raise last_error

    async def _respect_delay(self, host: str) -> None:
        """같은 호스트로 가는 직전 요청과의 간격을 `CRAWL_DELAY_SECONDS` 이상으로 만든다."""
        now = self._clock()
        last = self._last_request_at.get(host)
        if last is not None:
            remaining = self._delay_seconds - (now - last)
            if remaining > 0:
                await self._sleep(remaining)
                now = self._clock()
        self._last_request_at[host] = now

    def _lock_for(self, host: str) -> asyncio.Lock:
        """호스트당 잠금 하나. 동시 실행이 같은 호스트의 딜레이를 건너뛰지 못하게 한다."""
        lock = self._host_locks.get(host)
        if lock is None:
            lock = asyncio.Lock()
            self._host_locks[host] = lock
        return lock


_fetcher: Fetcher | None = None


def get_fetcher() -> Fetcher:
    """공용 인스턴스. 호스트별 딜레이는 모두가 이것을 공유할 때만 지켜진다."""
    global _fetcher
    if _fetcher is None:
        _fetcher = Fetcher()
    return _fetcher


async def close_fetcher() -> None:
    """앱 종료 시 공용 인스턴스를 닫는다."""
    global _fetcher
    if _fetcher is not None:
        await _fetcher.aclose()
        _fetcher = None
