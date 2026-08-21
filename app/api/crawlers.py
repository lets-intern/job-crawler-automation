"""크롤러 등록과 셀렉터 수동 보정.

등록은 리스트 URL 과 상세 URL 을 받아 셀렉터를 생성하고 `crawlers` 행을 `status=draft` 로
남기는 데까지다. 여기서 워크플로우가 되지는 않는다 — 테스트 실행을 거쳐야 `tested` 가 되고,
그 다음이 승격이다 (`.claude/docs/data-model.md`).

생성된 셀렉터는 가설이라 실패한 필드가 있어도 행은 남는다. 실패한 필드 이름을 응답에 실어
운영자가 그 필드만 손으로 고치게 한다. 손으로 고친 셀렉터를 요청 없이 다시 생성하지 않는다
(`.claude/rules/llm.md`).

테스트 실행은 저장된 셀렉터로 실제 페이지를 1회 크롤링해 필드별 미리보기와 실패 사유를
돌려준다. 통과한 것만 `tested` 가 된다 — 실패한 실행은 상태를 건드리지 않는다.

`default_company` 는 회사명이 페이지에 없는 사이트를 위한 운영자 입력이고 선택이다. 운영자가
타이핑한 값이라 추출 결과가 아니고, 그래서 `crawlers` 에만 있고 `raw_jobs` 에는 가지 않는다
(`.claude/rules/data-safety.md`). 어느 회사명이 쓰일지는 정규화 단계가 정한다.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Awaitable, Callable, Iterator
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app import db
from app.crawler.failures import SUCCESS
from app.crawler.fetcher import Fetcher, FetchError, RobotsDisallowedError, get_fetcher
from app.crawler.runner import RunTarget, run_once
from app.selector.generator import GenerationResult, SelectorGenerationError, generate_for_urls
from app.selector.schema import SelectorSchemaError, SelectorSet, validate_selectors

router = APIRouter(prefix="/api/crawlers", tags=["crawlers"])

GenerateFn = Callable[[str, str], Awaitable[GenerationResult]]


class CrawlerCreate(BaseModel):
    list_url: str
    detail_url: str
    name: str = ""
    # 회사명이 페이지에 없는 사이트를 위한 운영자 입력. 없으면 비운다
    default_company: str = ""


class CompanyUpdate(BaseModel):
    """운영자가 적어 둔 회사명만 바꾼다. 빈 문자열은 지운다는 뜻이다."""

    default_company: str = ""


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
    default_company: str | None
    selectors: SelectorSet
    matches: dict[str, int]
    failed_fields: list[str]
    notes: list[str]
    usage: UsageOut


class CompanyOut(BaseModel):
    """회사명 수정 결과. 저장된 값을 그대로 돌려준다."""

    id: int
    default_company: str | None


class SelectorsOut(BaseModel):
    """수동 보정 결과. `status` 는 보정으로 바뀌지 않는다."""

    id: int
    status: str
    selectors: SelectorSet


class PreviewItem(BaseModel):
    """추출된 값 그대로. 정제 전이라 공백과 줄바꿈이 섞여 있는 것이 정상이다."""

    source_url: str
    state: str
    fields: dict[str, str]


class RunFailure(BaseModel):
    source_url: str
    error_class: str | None
    message: str


class TestRunOut(BaseModel):
    """`crawl_runs` 행에 남은 값과 같은 카운트 + 미리보기."""

    crawler_id: int
    run_id: int
    status: str
    crawler_status: str
    matched: int
    success_count: int
    new_count: int
    fail_count: int
    error_class: str | None
    error_message: str
    items: list[PreviewItem]
    failures: list[RunFailure]


def get_connection() -> Iterator[sqlite3.Connection]:
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def get_crawl_fetcher() -> Fetcher:
    """공용 fetch 클라이언트. 테스트는 이 의존성을 갈아끼운다."""
    return get_fetcher()


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
    # 안 적었으면 NULL 이다. 빈 문자열로 넣으면 "회사명이 있다" 와 구분되지 않는다
    default_company = payload.default_company.strip() or None
    cursor = conn.execute(
        """
        INSERT INTO crawlers (name, list_url, detail_url, selectors_json, status, default_company)
        VALUES (?, ?, ?, ?, 'draft', ?)
        """,
        (
            name,
            payload.list_url,
            payload.detail_url,
            result.selectors.to_json(),
            default_company,
        ),
    )
    crawler_id = int(cursor.lastrowid or 0)

    return CrawlerOut(
        id=crawler_id,
        name=name,
        status="draft",
        default_company=default_company,
        selectors=result.selectors,
        matches=result.verification.summary(),
        failed_fields=result.verification.failed,
        notes=result.notes,
        usage=UsageOut(**vars(result.usage)),
    )


@router.put("/{crawler_id}/company", response_model=CompanyOut)
def update_company(
    crawler_id: int,
    payload: CompanyUpdate,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
) -> CompanyOut:
    """운영자가 적어 둔 회사명을 고친다.

    이 값은 `normalized_jobs` 에 즉시 반영되지 않는다. 고친 뒤 재정규화를 돌려야 `operator`
    로 확정된 행이 새 값을 받는다 (`.claude/tasks/todo/tasks-job-crawler-push7.md`).
    """
    row = conn.execute("SELECT id FROM crawlers WHERE id = ?", (crawler_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail={"message": f"크롤러 {crawler_id} 가 없다"})

    default_company = payload.default_company.strip() or None
    conn.execute(
        "UPDATE crawlers SET default_company = ? WHERE id = ?", (default_company, crawler_id)
    )
    return CompanyOut(id=crawler_id, default_company=default_company)


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


@router.post("/{crawler_id}/test-run", response_model=TestRunOut)
async def test_run(
    crawler_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    fetcher: Annotated[Fetcher, Depends(get_crawl_fetcher)],
    limit: Annotated[int, Query(ge=1, le=20)] = 3,
) -> TestRunOut:
    """저장된 셀렉터로 실제 페이지를 1회 크롤링한다.

    `limit` 은 상세를 몇 건까지 따라갈지다. 테스트는 3건이면 충분하고, 전체를 도는 것은
    테스트가 아니라 그냥 크롤링이다 (`.claude/skills/crawl-test/SKILL.md`).

    워크플로우가 없는 실행이라 `raw_jobs` 에는 적재하지 않는다. 남는 것은 `crawl_runs` 행과
    이 응답의 미리보기뿐이다.
    """
    row = conn.execute(
        "SELECT list_url, selectors_json, status FROM crawlers WHERE id = ?", (crawler_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail={"message": f"크롤러 {crawler_id} 가 없다"})
    if not row["selectors_json"]:
        raise HTTPException(
            status_code=409,
            detail={"reason": "no_selectors", "message": "셀렉터가 없는 크롤러는 실행할 수 없다"},
        )

    try:
        selectors = validate_selectors(json.loads(row["selectors_json"]))
    except (json.JSONDecodeError, SelectorSchemaError) as exc:
        # 저장된 셀렉터가 스키마에 맞지 않는다. 추측해서 고치지 않고 그대로 알린다.
        raise HTTPException(
            status_code=409, detail={"reason": "invalid_selectors", "message": str(exc)}
        ) from exc

    result = await run_once(
        conn,
        RunTarget(list_url=row["list_url"], selectors=selectors, crawler_id=crawler_id),
        fetcher=fetcher,
        limit=limit,
    )

    crawler_status = row["status"]
    if result.status == SUCCESS and crawler_status == "draft":
        conn.execute("UPDATE crawlers SET status = 'tested' WHERE id = ?", (crawler_id,))
        crawler_status = "tested"

    return TestRunOut(
        crawler_id=crawler_id,
        run_id=result.run_id,
        status=result.status,
        crawler_status=crawler_status,
        matched=result.matched,
        success_count=result.success_count,
        new_count=result.new_count,
        fail_count=result.fail_count,
        error_class=result.error_class,
        error_message=result.error_message,
        items=[
            PreviewItem(source_url=item.source_url, state=item.state, fields=item.fields)
            for item in result.items
        ],
        failures=[
            RunFailure(
                source_url=failure.source_url,
                error_class=failure.error_class,
                message=failure.message,
            )
            for failure in result.failures
        ],
    )
