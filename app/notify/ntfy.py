"""ntfy 로 알림 하나를 보낸다. 이 모듈이 아는 것은 HTTP 와 ntfy 헤더뿐이다.

공용 fetch 클라이언트(`app/crawler/fetcher.py`)를 쓰지 않는다. 그 클라이언트는 크롤링 대상
사이트를 지키는 장치다 — robots.txt 를 묻고, 호스트별로 딜레이를 기다리고, 우리 이름을
User-Agent 로 밝힌다. 알림 서버는 크롤링 대상이 아니라 우리가 우리에게 보내는 자리라 셋 다
뜻이 없고, 딜레이는 실행이 끝나는 시각을 밀기만 한다. 이 예외는
`.claude/rules/crawling.md` 에 적혀 있다.

**보내기는 실패해도 예외를 밖으로 내지 않는다.** 알림이 안 갔다고 수집이 실패한 것은 아니다
(`.claude/tasks/done/ntfy-notify/tasks-ntfy-notify.md`). 사유는 `SendResult` 와 로그에 남는다.

한글은 헤더에 UTF-8 바이트로 직접 넣는다. httpx 에 `dict[str, str]` 을 넘기면 헤더 값을
**ascii 로** 인코딩해서 한글 제목이 `UnicodeEncodeError` 로 죽는다 (`Headers.__init__` 은
ascii, `Headers.__setitem__` 은 utf-8 로 서로 다르다). 바이트로 넘기면 httpx 가 손대지 않고
그대로 싣는다 — curl 이 보낸 것과 같은 바이트이고, ntfy 가 그것을 읽는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# 알림 하나에 쓰는 시간의 상한. 알림 서버가 답하지 않아 실행이 멈추면 안 된다.
# 크롤링 타임아웃보다 짧게 둔다 — 이것은 수집이 끝난 뒤에 덧붙는 시간이다
TIMEOUT_SECONDS = 5.0

# ntfy 가 받는 우선순위 이름. 숫자(1~5)도 받지만 저장값은 읽히는 쪽으로 둔다
PRIORITIES: tuple[str, ...] = ("min", "low", "default", "high", "urgent")


class NtfyConfigError(ValueError):
    """보낼 수 없는 설정. 주소나 토픽이나 우선순위가 ntfy 가 받는 모양이 아니다."""


@dataclass(frozen=True)
class NtfyTarget:
    """어디로 보내는가. 서버 주소와 토픽을 따로 둔다 — 토픽만 바꾸는 일이 더 잦다."""

    server_url: str
    topic: str
    priority: str = "default"

    @property
    def publish_url(self) -> str:
        return f"{self.server_url.rstrip('/')}/{self.topic.strip('/')}"

    def validate(self) -> None:
        """보내기 전에 한 번 본다. 틀린 설정은 5초를 기다린 뒤가 아니라 지금 알린다."""
        if not self.server_url.startswith(("http://", "https://")):
            raise NtfyConfigError(
                f"서버 주소는 http:// 나 https:// 로 시작해야 한다: {self.server_url!r}"
            )
        topic = self.topic.strip()
        if not topic:
            raise NtfyConfigError("토픽이 비었다")
        if "/" in topic:
            raise NtfyConfigError(f"토픽에 / 를 넣을 수 없다: {self.topic!r}")
        if self.priority not in PRIORITIES:
            raise NtfyConfigError(
                f"우선순위는 {', '.join(PRIORITIES)} 중 하나여야 한다: {self.priority!r}"
            )


@dataclass(frozen=True)
class NtfyMessage:
    """알림 하나의 내용. 본문은 마크다운으로 나간다.

    `tags` 는 ntfy 의 이모지 단축이름이다. `.claude/rules/writing.md` 의 그림문자 금지는
    문서에 대한 것이고 휴대폰 알림은 문서가 아니다 — 태그는 상태를 한눈에 보이게 하는
    자리라 쓰되, `title` 과 `body` 의 문장에는 넣지 않는다.

    `click` 은 알림을 눌렀을 때 열 주소다. 비어 있으면 헤더를 붙이지 않는다.
    """

    title: str
    body: str
    tags: tuple[str, ...] = ()
    click: str = ""

    def headers(self) -> dict[str, str]:
        """ntfy 가 읽는 헤더. 값이 없는 헤더는 아예 붙이지 않는다."""
        built = {"X-Title": self.title, "X-Markdown": "yes"}
        if self.tags:
            built["X-Tags"] = ",".join(self.tags)
        if self.click:
            built["X-Click"] = self.click
        return built


@dataclass(frozen=True)
class SendResult:
    """보낸 결과. 실패도 값으로 돌아온다 — 예외로 올라가지 않는다."""

    ok: bool
    # 화면과 로그에 그대로 적는 한 줄. 성공이면 무엇을 어디로 보냈는지, 실패면 왜 못 보냈는지
    detail: str
    status_code: int | None = None


async def send(
    target: NtfyTarget,
    message: NtfyMessage,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> SendResult:
    """알림 하나를 보낸다. 어떤 실패에서도 예외를 던지지 않는다.

    `transport` 는 테스트가 `httpx.MockTransport` 를 끼우는 자리다. 운영 경로에서는 None 이다.
    """
    try:
        target.validate()
    except NtfyConfigError as exc:
        logger.warning("알림을 보내지 못했다. 설정이 틀렸다: %s", exc)
        return SendResult(ok=False, detail=f"설정이 틀렸다: {exc}")

    headers = message.headers()
    headers["X-Priority"] = target.priority
    # 값을 바이트로 넘긴다. 문자열로 넘기면 httpx 가 ascii 로 인코딩해 한글 제목에서 죽는다.
    # 이름도 같이 바이트로 만든다 — httpx 는 이름과 값의 타입이 섞인 매핑을 받지 않는다
    encoded = {name.encode("ascii"): value.encode("utf-8") for name, value in headers.items()}
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(TIMEOUT_SECONDS), transport=transport
        ) as client:
            response = await client.post(
                target.publish_url,
                content=message.body.encode("utf-8"),
                headers=encoded,
            )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        logger.warning("알림 서버가 %s 로 거절했다: %s", status, target.publish_url)
        return SendResult(ok=False, detail=f"알림 서버가 {status} 로 거절했다", status_code=status)
    except httpx.TimeoutException:
        logger.warning(
            "알림 서버가 %s초 안에 답하지 않았다: %s", TIMEOUT_SECONDS, target.publish_url
        )
        return SendResult(ok=False, detail=f"알림 서버가 {TIMEOUT_SECONDS}초 안에 답하지 않았다")
    except Exception as exc:
        # 알림 하나 때문에 실행이 죽지 않는다. 무엇이 났는지는 남긴다
        logger.warning("알림을 보내지 못했다: %s: %s", type(exc).__name__, exc)
        return SendResult(ok=False, detail=f"알림을 보내지 못했다: {type(exc).__name__}: {exc}")

    logger.info("알림을 보냈다: %s (%s)", target.publish_url, response.status_code)
    return SendResult(
        ok=True,
        detail=f"{target.publish_url} 로 보냈다",
        status_code=response.status_code,
    )
