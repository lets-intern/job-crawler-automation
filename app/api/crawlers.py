"""크롤러 등록과 셀렉터 수동 보정.

등록은 리스트 URL 과 상세 URL 을 받아 셀렉터를 생성하고 `crawlers` 행을 `status=draft` 로
남기는 데까지다. 여기서 워크플로우가 되지는 않는다 — 테스트 실행을 거쳐야 `tested` 가 되고,
그 다음이 승격이다 (`.claude/docs/data-model.md`).

생성된 셀렉터는 가설이라 실패한 필드가 있어도 행은 남는다. 실패한 필드 이름을 응답에 실어
운영자가 그 필드만 손으로 고치게 한다. 손으로 고친 셀렉터를 요청 없이 다시 생성하지 않는다
(`.claude/rules/llm.md`).

예외는 목록 필드가 전부 0개 매칭인 경우다. 그때는 행을 남기지 않고 실패로 돌려준다. 고칠 필드
하나가 틀린 것이 아니라 정적 HTML 에 목록이 없는 것이라, 저장해 봐야 아무것도 뽑지 못하는
크롤러가 남는다. 0건 추출을 성공으로 내보내지 않는다는 규칙이 생성 단계에도 적용된다.

테스트 실행은 저장된 셀렉터로 실제 페이지를 1회 크롤링해 필드별 미리보기와 실패 사유를
돌려준다. 통과한 것만 `tested` 가 된다 — 실패한 실행은 상태를 건드리지 않는다.

삭제는 크롤러 정의만 지운다. 워크플로우로 승격된 크롤러는 거절한다 — 워크플로우와 그 실행
기록이 매달려 있고, 정의만 사라지면 남은 기록이 누구 것인지 아무도 설명하지 못한다. 수집한
데이터(`raw_jobs`, `normalized_jobs`)는 크롤러 정의와 수명이 다르므로 함께 지우지 않는다
(`.claude/rules/data-safety.md`).

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
from app.crawler.fetcher import FetchError, FetchPolicy, RobotsDisallowedError, get_fetcher
from app.crawler.playwright import PLAYWRIGHT, RENDER_MODES, open_source
from app.crawler.runner import RunTarget, run_once
from app.selector.generator import GenerationResult, SelectorGenerationError, generate_for_urls
from app.selector.schema import SelectorSchemaError, SelectorSet, validate_selectors

router = APIRouter(prefix="/api/crawlers", tags=["crawlers"])

# 새 크롤러가 받는 모드. 측정한 사이트 6개 중 4개가 JS 렌더라, 정적으로 먼저 시도하면 대부분이
# 빈 목록으로 돌아온다. 정적은 지우지 않고 선택지로 남긴다 — 브라우저 하나가 150~300MB 라,
# 정적으로 되는 사이트까지 렌더로 돌리면 그만큼이 그냥 나간다. 내리는 것은 운영자가 한다
DEFAULT_RENDER_MODE = PLAYWRIGHT

# 인자는 리스트 URL, 상세 URL, render_mode 다. 어느 경로로 가져올지는 크롤러마다 다르므로
# 생성 함수가 매번 받는다.
GenerateFn = Callable[[str, str, str], Awaitable[GenerationResult]]


class CrawlerCreate(BaseModel):
    list_url: str
    detail_url: str
    name: str = ""
    # 회사명이 페이지에 없는 사이트를 위한 운영자 입력. 없으면 비운다
    default_company: str = ""
    # 기본값은 렌더다. 정적으로 충분한 사이트는 등록 뒤에 운영자가 내린다
    render_mode: str = DEFAULT_RENDER_MODE


class RenderModeUpdate(BaseModel):
    """`static` 과 `playwright` 둘뿐이다. 승격은 운영자가 정한다."""

    render_mode: str


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
    render_mode: str
    selectors: SelectorSet
    matches: dict[str, int]
    failed_fields: list[str]
    notes: list[str]
    usage: UsageOut


class RenderModeOut(BaseModel):
    """전환 결과. 저장된 값을 그대로 돌려준다."""

    id: int
    render_mode: str


class CompanyOut(BaseModel):
    """회사명 수정 결과. 저장된 값을 그대로 돌려준다."""

    id: int
    default_company: str | None


class DeleteOut(BaseModel):
    """삭제 결과. 함께 지운 테스트 실행 기록 수를 같이 돌려준다."""

    id: int
    name: str
    deleted_test_runs: int


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


def get_crawl_fetcher() -> FetchPolicy:
    """공용 fetch 클라이언트. 테스트는 이 의존성을 갈아끼운다."""
    return get_fetcher()


def get_generator() -> GenerateFn:
    """기본 생성 경로. 테스트는 이 의존성을 갈아끼운다."""

    async def generate(list_url: str, detail_url: str, render_mode: str) -> GenerationResult:
        # 렌더 모드면 브라우저가 이 블록 안에서만 산다. 생성이 끝나면 닫힌다
        async with open_source(render_mode, get_fetcher()) as source:
            return await generate_for_urls(list_url, detail_url, source=source)

    return generate


@router.post("", response_model=CrawlerOut, status_code=201)
async def create_crawler(
    payload: CrawlerCreate,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    generate: Annotated[GenerateFn, Depends(get_generator)],
) -> CrawlerOut:
    render_mode = _validated_render_mode(payload.render_mode)
    try:
        result = await generate(payload.list_url, payload.detail_url, render_mode)
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

    if result.verification.list_missing:
        # 정적 HTML 에 목록이 없다. 셀렉터를 손으로 고쳐도 잡을 노드가 없으므로 행을 남기지
        # 않는다. 다음 수단은 렌더 모드 승격이지 셀렉터 재생성이 아니다.
        failed = ", ".join(result.verification.failed_list_fields)
        raise HTTPException(
            status_code=422,
            detail={
                "reason": "list_not_found",
                "message": (
                    f"정적 HTML 에서 목록을 찾지 못했다. 목록 필드 {failed} 가 모두 0개 매칭이다. "
                    "JS 로 목록을 그리는 사이트일 수 있으니 렌더 모드 승격을 검토한다"
                ),
                "failed_fields": result.verification.failed,
                "matches": result.verification.summary(),
            },
        )

    name = payload.name.strip() or urlsplit(payload.list_url).netloc
    # 안 적었으면 NULL 이다. 빈 문자열로 넣으면 "회사명이 있다" 와 구분되지 않는다
    default_company = payload.default_company.strip() or None
    cursor = conn.execute(
        """
        INSERT INTO crawlers
               (name, list_url, detail_url, selectors_json, status, default_company, render_mode)
        VALUES (?, ?, ?, ?, 'draft', ?, ?)
        """,
        (
            name,
            payload.list_url,
            payload.detail_url,
            result.selectors.to_json(),
            default_company,
            render_mode,
        ),
    )
    crawler_id = int(cursor.lastrowid or 0)

    return CrawlerOut(
        id=crawler_id,
        name=name,
        status="draft",
        default_company=default_company,
        render_mode=render_mode,
        selectors=result.selectors,
        matches=result.verification.summary(),
        failed_fields=result.verification.failed,
        notes=result.notes,
        usage=UsageOut(**vars(result.usage)),
    )


def _validated_render_mode(value: str) -> str:
    """모르는 값은 거절한다. 조용히 다른 모드로 되돌리면 운영자는 고른 줄 알고 기다린다."""
    mode = value.strip() or DEFAULT_RENDER_MODE
    if mode not in RENDER_MODES:
        raise HTTPException(
            status_code=422,
            detail={
                "reason": "unknown_render_mode",
                "message": f"render_mode 는 {', '.join(RENDER_MODES)} 중 하나다: {value}",
            },
        )
    return mode


@router.put("/{crawler_id}/render-mode", response_model=RenderModeOut)
def update_render_mode(
    crawler_id: int,
    payload: RenderModeUpdate,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
) -> RenderModeOut:
    """정적과 렌더 사이를 옮긴다. 자동 승격은 없다 — 이 경로로만 바뀐다.

    바꾼다고 셀렉터가 다시 생성되지는 않는다. 정적으로 만든 셀렉터는 렌더된 DOM 과 다를 수
    있으므로, 올린 뒤에는 테스트 실행으로 다시 확인하는 것이 순서다
    (`.claude/skills/crawl-test/SKILL.md`).
    """
    row = conn.execute("SELECT id FROM crawlers WHERE id = ?", (crawler_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail={"message": f"크롤러 {crawler_id} 가 없다"})

    mode = _validated_render_mode(payload.render_mode)
    conn.execute("UPDATE crawlers SET render_mode = ? WHERE id = ?", (mode, crawler_id))
    return RenderModeOut(id=crawler_id, render_mode=mode)


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


@router.delete("/{crawler_id}", response_model=DeleteOut)
def delete_crawler(
    crawler_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
) -> DeleteOut:
    """크롤러 정의를 지운다. 되돌릴 수 없다.

    워크플로우가 매달려 있으면 거절한다. 크롤러만 사라지면 그 워크플로우의 `crawl_runs` 와
    `raw_jobs` 가 어느 사이트에서 온 것인지 설명할 수 없게 된다. 지우려면 워크플로우를 먼저
    지워야 한다.

    함께 지우는 것은 승격 전 테스트 실행 기록뿐이다. 그 행은 이 크롤러 하나만 가리키고 있어
    정의가 없으면 읽을 수 없다. 수집한 공고(`raw_jobs`, `normalized_jobs`)는 워크플로우에
    매달려 있고 크롤러 정의와 수명이 다르므로 건드리지 않는다 (`.claude/rules/data-safety.md`).
    """
    row = conn.execute(
        "SELECT id, name, status FROM crawlers WHERE id = ?", (crawler_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail={"message": f"크롤러 {crawler_id} 가 없다"})

    workflow_ids = [
        int(item["id"])
        for item in conn.execute(
            "SELECT id FROM workflows WHERE crawler_id = ? ORDER BY id", (crawler_id,)
        ).fetchall()
    ]
    if workflow_ids:
        joined = ", ".join(str(item) for item in workflow_ids)
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "has_workflow",
                "message": (
                    f"워크플로우 {joined} 가 이 크롤러를 쓰고 있어 지울 수 없다. "
                    "워크플로우를 먼저 지운 뒤 다시 시도한다"
                ),
            },
        )
    if row["status"] == "promoted":
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "promoted",
                "message": (
                    "승격된 크롤러는 지울 수 없다. 매달린 워크플로우를 먼저 정리한 뒤 "
                    "상태를 되돌려야 한다"
                ),
            },
        )

    deleted = conn.execute(
        "DELETE FROM crawl_runs WHERE crawler_id = ? AND workflow_id IS NULL", (crawler_id,)
    ).rowcount
    conn.execute("DELETE FROM crawlers WHERE id = ?", (crawler_id,))
    return DeleteOut(id=crawler_id, name=str(row["name"]), deleted_test_runs=max(deleted, 0))


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
    fetcher: Annotated[FetchPolicy, Depends(get_crawl_fetcher)],
    limit: Annotated[int, Query(ge=1, le=20)] = 3,
) -> TestRunOut:
    """저장된 셀렉터로 실제 페이지를 1회 크롤링한다.

    `limit` 은 상세를 몇 건까지 따라갈지다. 테스트는 3건이면 충분하고, 전체를 도는 것은
    테스트가 아니라 그냥 크롤링이다 (`.claude/skills/crawl-test/SKILL.md`).

    워크플로우가 없는 실행이라 `raw_jobs` 에는 적재하지 않는다. 남는 것은 `crawl_runs` 행과
    이 응답의 미리보기뿐이다.
    """
    row = conn.execute(
        "SELECT list_url, selectors_json, status, render_mode FROM crawlers WHERE id = ?",
        (crawler_id,),
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

    async with open_source(row["render_mode"], fetcher) as source:
        result = await run_once(
            conn,
            RunTarget(
                list_url=row["list_url"],
                selectors=selectors,
                crawler_id=crawler_id,
                render_mode=row["render_mode"],
            ),
            fetcher=source,
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
