"""ntfy 보내기 테스트 (1.1.V).

확인하는 것은 둘이다. 헤더가 ntfy 가 읽는 이름과 값으로 실리는지, 그리고 어떤 실패에서도
예외가 밖으로 새지 않는지.

망은 테스트 의존이 아니다 (`../.claude/rules/core.md`). `httpx.MockTransport` 로 요청을 받아
본다 — 실제 알림 서버를 때리지 않는다.
"""

from __future__ import annotations

import httpx
import pytest

from app.notify import ntfy


def capture(status_code: int = 200) -> tuple[list[httpx.Request], httpx.MockTransport]:
    """보낸 요청을 담아 두는 transport. 응답 상태는 테스트가 정한다."""
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status_code, json={"id": "abc", "topic": "job"})

    return seen, httpx.MockTransport(handle)


def target(priority: str = "default") -> ntfy.NtfyTarget:
    return ntfy.NtfyTarget(server_url="https://ntfy.example.com", topic="job", priority=priority)


def message() -> ntfy.NtfyMessage:
    return ntfy.NtfyMessage(
        title="삼성전자 새 공고 3건",
        body="- **삼성전자** 신입 채용\n외 2건",
        tags=("briefcase",),
        click="https://ops.example.com/review",
    )


async def test_헤더가_ntfy_가_읽는_이름으로_실린다() -> None:
    seen, transport = capture()

    result = await ntfy.send(target("high"), message(), transport=transport)

    assert result.ok
    assert result.status_code == 200
    assert len(seen) == 1
    request = seen[0]
    assert str(request.url) == "https://ntfy.example.com/job"
    assert request.method == "POST"
    assert request.headers["X-Title"] == "삼성전자 새 공고 3건"
    assert request.headers["X-Priority"] == "high"
    assert request.headers["X-Tags"] == "briefcase"
    assert request.headers["X-Markdown"] == "yes"
    assert request.headers["X-Click"] == "https://ops.example.com/review"


async def test_한글_제목은_UTF_8_바이트로_나간다() -> None:
    """curl 로 확인한 것과 같은 바이트여야 ntfy 가 제목을 제대로 읽는다."""
    seen, transport = capture()

    await ntfy.send(target(), message(), transport=transport)

    raw = {key.lower(): value for key, value in seen[0].headers.raw}
    assert raw[b"x-title"] == "삼성전자 새 공고 3건".encode()


async def test_본문은_UTF_8_로_실린다() -> None:
    seen, transport = capture()

    await ntfy.send(target(), message(), transport=transport)

    assert seen[0].content.decode("utf-8") == "- **삼성전자** 신입 채용\n외 2건"


async def test_값이_없는_헤더는_붙이지_않는다() -> None:
    seen, transport = capture()

    await ntfy.send(target(), ntfy.NtfyMessage(title="제목", body="본문"), transport=transport)

    assert "X-Tags" not in seen[0].headers
    assert "X-Click" not in seen[0].headers


async def test_5xx_는_예외가_아니라_실패한_결과로_돌아온다() -> None:
    _, transport = capture(status_code=503)

    result = await ntfy.send(target(), message(), transport=transport)

    assert result.ok is False
    assert result.status_code == 503
    assert "503" in result.detail


async def test_연결이_끊겨도_예외가_새지_않는다() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("연결하지 못했다", request=request)

    result = await ntfy.send(target(), message(), transport=httpx.MockTransport(broken))

    assert result.ok is False
    assert "ConnectError" in result.detail


async def test_타임아웃도_예외가_새지_않는다() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("답이 없다", request=request)

    result = await ntfy.send(target(), message(), transport=httpx.MockTransport(slow))

    assert result.ok is False
    assert "답하지 않았다" in result.detail


@pytest.mark.parametrize(
    ("server_url", "topic", "priority"),
    [
        ("ntfy.example.com", "job", "default"),
        ("https://ntfy.example.com", "", "default"),
        ("https://ntfy.example.com", "job/sub", "default"),
        ("https://ntfy.example.com", "job", "아주높음"),
    ],
)
async def test_틀린_설정은_보내지_않고_사유를_돌려준다(
    server_url: str, topic: str, priority: str
) -> None:
    seen, transport = capture()

    result = await ntfy.send(
        ntfy.NtfyTarget(server_url=server_url, topic=topic, priority=priority),
        message(),
        transport=transport,
    )

    assert result.ok is False
    assert "설정이 틀렸다" in result.detail
    # 틀린 설정으로는 요청 자체를 보내지 않는다
    assert seen == []


def test_서버_주소_끝의_슬래시는_토픽과_겹치지_않는다() -> None:
    assert (
        ntfy.NtfyTarget(server_url="https://ntfy.example.com/", topic="job").publish_url
        == "https://ntfy.example.com/job"
    )
