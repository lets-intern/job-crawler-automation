"""크롤러 등록과 셀렉터 수동 보정.

등록은 리스트 URL 과 상세 URL 을 받아 셀렉터를 생성하고 `crawlers` 행을 `status=draft` 로
남기는 데까지다. 여기서 워크플로우가 되지는 않는다 — 테스트 실행을 거쳐야 `tested` 가 되고,
그 다음이 승격이다 (`.claude/docs/data-model.md`).

생성된 셀렉터는 가설이라 실패한 필드가 있어도 행은 남는다. 실패한 필드 이름을 응답에 실어
운영자가 그 필드만 손으로 고치게 한다. 손으로 고친 셀렉터를 요청 없이 다시 생성하지 않는다
(`.claude/rules/llm.md`).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Awaitable, Callable, Iterator
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import db
from app.crawler.fetcher import FetchError, RobotsDisallowedError
from app.selector.generator import GenerationResult, SelectorGenerationError, generate_for_urls
from app.selector.schema import SelectorSchemaError, SelectorSet, validate_selectors

router = APIRouter(prefix="/api/crawlers", tags=["crawlers"])

GenerateFn = Callable[[str, str], Awaitable[GenerationResult]]


class CrawlerCreate(BaseModel):
    list_url: str
    detail_url: str
    name: str = ""


class UsageOut(BaseModel):
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: int


class CrawlerOut(BaseModel):
    """등록 결과. `failed_fields` 가 비어야 테스트 실행으로 넘어갈 만하다."""

    id: int
    name: str
    status: str
    selectors: SelectorSet
    matches: dict[str, int]
    failed_fields: list[str]
    notes: list[str]
    usage: UsageOut


class SelectorsOut(BaseModel):
    """수동 보정 결과. `status` 는 보정으로 바뀌지 않는다."""

    id: int
    status: str
    selectors: SelectorSet


def get_connection() -> Iterator[sqlite3.Connection]:
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def get_generator() -> GenerateFn:
    """기본 생성 경로. 테스트는 이 의존성을 갈아끼운다."""

    async def generate(list_url: str, detail_url: str) -> GenerationResult:
        return await generate_for_urls(list_url, detail_url)

    return generate


@router.post("", response_model=CrawlerOut, status_code=201)
async def create_crawler(
    payload: CrawlerCreate,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    generate: Annotated[GenerateFn, Depends(get_generator)],
) -> CrawlerOut:
    try:
        result = await generate(payload.list_url, payload.detail_url)
    except RobotsDisallowedError as exc:
        # robots 가 막은 URL 은 등록 자체를 거절한다 (`.claude/rules/crawling.md`).
        raise HTTPException(
            status_code=400, detail={"reason": "robots", "message": str(exc)}
        ) from exc
    except FetchError as exc:
        raise HTTPException(
            status_code=502, detail={"reason": exc.error_class, "message": str(exc)}
        ) from exc
    except SelectorGenerationError as exc:
        status = 500 if exc.reason == "no_api_key" else 502
        raise HTTPException(
            status_code=status, detail={"reason": exc.reason, "message": str(exc)}
        ) from exc

    name = payload.name.strip() or urlsplit(payload.list_url).netloc
    cursor = conn.execute(
        """
        INSERT INTO crawlers (name, list_url, detail_url, selectors_json, status)
        VALUES (?, ?, ?, ?, 'draft')
        """,
        (name, payload.list_url, payload.detail_url, result.selectors.to_json()),
    )
    crawler_id = int(cursor.lastrowid or 0)

    return CrawlerOut(
        id=crawler_id,
        name=name,
        status="draft",
        selectors=result.selectors,
        matches=result.verification.summary(),
        failed_fields=result.verification.failed,
        notes=result.notes,
        usage=UsageOut(**vars(result.usage)),
    )


@router.put("/{crawler_id}/selectors", response_model=SelectorsOut)
def update_selectors(
    crawler_id: int,
    payload: dict[str, Any],
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
) -> SelectorsOut:
    """운영자가 손으로 고친 셀렉터를 그대로 저장한다. 다시 생성하지 않는다."""
    row = conn.execute("SELECT status FROM crawlers WHERE id = ?", (crawler_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail={"message": f"크롤러 {crawler_id} 가 없다"})

    try:
        selectors = validate_selectors(payload)
    except SelectorSchemaError as exc:
        raise HTTPException(
            status_code=422, detail={"reason": exc.reason, "message": str(exc)}
        ) from exc

    conn.execute(
        "UPDATE crawlers SET selectors_json = ? WHERE id = ?",
        (selectors.to_json(), crawler_id),
    )
    return SelectorsOut(id=crawler_id, status=row["status"], selectors=selectors)
