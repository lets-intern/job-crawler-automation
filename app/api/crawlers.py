"""크롤러 등록과 셀렉터 수동 보정.

등록은 리스트 URL 과 상세 URL 을 받아 셀렉터를 생성하고 `crawlers` 행을 `status=draft` 로
남기는 데까지다. 여기서 워크플로우가 되지는 않는다 — 테스트 실행을 거쳐야 `tested` 가 되고,
그 다음이 승격이다 (`.claude/docs/data-model.md`).

생성된 셀렉터는 가설이라 실패한 필드가 있어도 행은 남는다. 실패한 필드 이름을 응답에 실어
운영자가 그 필드만 손으로 고치게 한다. 손으로 고친 셀렉터를 요청 없이 다시 생성하지 않는다
(`.claude/rules/llm.md`).

예외는 둘이다. 목록 필드가 전부 0개 매칭이면 정적 HTML 에 목록이 없는 것이고, 항목은 잡혔는데
그 안의 제목·링크·날짜가 전부 0개면 항목 셀렉터가 목록이 아닌 다른 것을 잡은 것이다. 둘 다 행을
남기지 않고 실패로 돌려주되 사유를 갈라 적는다 — 앞은 렌더 승격을, 뒤는 항목 셀렉터를 다시
잡는 것을 다음 수단으로 가리킨다. 어느 쪽이든 저장해 봐야 아무것도 뽑지 못하는 크롤러가 남고,
0건 추출을 성공으로 내보내지 않는다는 규칙이 생성 단계에도 적용된다.

테스트 실행은 저장된 셀렉터로 실제 페이지를 1회 크롤링해 필드별 미리보기와 실패 사유를
돌려준다. 통과한 것만 `tested` 가 된다 — 실패한 실행은 상태를 건드리지 않는다.

삭제는 크롤러 정의만 지운다. 워크플로우로 승격된 크롤러는 거절한다 — 워크플로우와 그 실행
기록이 매달려 있고, 정의만 사라지면 남은 기록이 누구 것인지 아무도 설명하지 못한다. 수집한
데이터(`raw_jobs`, `normalized_jobs`)는 크롤러 정의와 수명이 다르므로 함께 지우지 않는다
(`.claude/rules/data-safety.md`).

상세 URL 은 선택이다. 상세를 JS 로 그려서 공고마다 주소가 따로 없는 사이트가 있고, 그런
사이트에 없는 주소를 지어내 가져오지 않는다. 비우면 목록 페이지만 보고 생성하며, 상세
셀렉터는 확인하지 않은 가설로 남는다 — 실패가 아니라 건너뛴 것이라 응답에서 갈라 적는다.

`default_company` 는 회사명이 페이지에 없는 사이트를 위한 운영자 입력이고 선택이다. 운영자가
타이핑한 값이라 추출 결과가 아니고, 그래서 `crawlers` 에만 있고 `raw_jobs` 에는 가지 않는다
(`.claude/rules/data-safety.md`). 어느 회사명이 쓰일지는 정규화 단계가 정한다.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Awaitable, Callable, Iterator
from typing import Annotated, Any, Protocol
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app import db
from app.crawler.failures import SUCCESS
from app.crawler.fetcher import FetchError, FetchPolicy, RobotsDisallowedError, get_fetcher
from app.crawler.playwright import RENDER_MODES, STATIC, open_source
from app.crawler.runner import TEST, RunTarget, run_once
from app.selector.generator import (
    GenerationResult,
    SelectorGenerationError,
    generate_for_urls,
    generate_from_html,
)
from app.selector.repair import RepairOutcome, SelectorRepairError, repair_for_urls
from app.selector.schema import SelectorSchemaError, SelectorSet, validate_selectors

router = APIRouter(prefix="/api/crawlers", tags=["crawlers"])

# 새 크롤러가 받는 모드. 정적이다 — 브라우저 하나가 실행당 150~300MB 이고 정적은 사실상
# 0이라, 정적으로 되는 사이트까지 렌더로 돌리면 그만큼이 그냥 나간다. 측정한 사이트 6개 중
# 4개가 JS 렌더지만, 어느 쪽이 필요한지는 테스트 실행 화면에서 두 모드를 비교해 정한다
DEFAULT_RENDER_MODE = STATIC

# 인자는 리스트 URL, 상세 URL, render_mode 다. 어느 경로로 가져올지는 크롤러마다 다르므로
# 생성 함수가 매번 받는다.
GenerateFn = Callable[[str, str, str], Awaitable[GenerationResult]]


class RepairFn(Protocol):
    """고치기 경로. 저장된 셀렉터를 기준으로만 돈다 — 무엇이 이미 맞는지 알아야 피해서 고른다.

    `hint` 는 운영자가 브라우저에서 보고 준 단서다. 비어 있으면 힌트가 생기기 전과 같은
    프롬프트로 돈다 (`app/selector/repair.py`). 키워드 인자인 것은 앞의 넷이 어디서 왔는지
    (DB 행) 와 이것이 어디서 왔는지(화면의 입력칸)가 다르기 때문이다.
    """

    async def __call__(
        self,
        list_url: str,
        detail_url: str,
        render_mode: str,
        selectors: SelectorSet,
        *,
        hint: str = "",
    ) -> RepairOutcome: ...


class CrawlerCreate(BaseModel):
    list_url: str
    # 선택이다. 상세를 JS 로 그려 주소가 따로 없는 사이트가 있다
    detail_url: str = ""
    name: str = ""
    # 회사명이 페이지에 없는 사이트를 위한 운영자 입력. 없으면 비운다
    default_company: str = ""
    # 기본값은 정적이다. 렌더가 필요한 사이트는 테스트 실행 화면에서 확인하고 올린다
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
    """등록 결과. `failed_fields` 가 비어야 테스트 실행으로 넘어갈 만하다.

    `skipped_fields` 는 판정하지 않은 필드다. 두 가지가 들어간다 — 상세 URL 없이 등록해서
    돌려볼 HTML 이 없었던 상세 필드와, 모델이 "사이트에 그 항목이 없다"고 답해 셀렉터가 비어
    있는 선택 필드다. 어느 쪽도 매칭은 0개지만 실패가 아니다. 0개 매칭을 성공으로 적으면
    운영자는 못 뽑은 필드와 원래 없는 필드를 구분할 수 없다.
    """

    id: int
    name: str
    status: str
    default_company: str | None
    render_mode: str
    detail_url: str | None
    selectors: SelectorSet
    matches: dict[str, int]
    failed_fields: list[str]
    skipped_fields: list[str]
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


class SelectorChangeOut(BaseModel):
    """필드 하나가 어떻게 바뀌었는지. 화면이 전/후를 나란히 적는 데 쓴다."""

    name: str
    before: str
    after: str


class RepairIn(BaseModel):
    """고치기 요청. 본문 없이 불러도 된다 — 그때는 힌트 없이 지금까지처럼 돈다.

    `hint` 는 자유 입력이다. F12 의 `Copy selector` 가 뱉은 경로일 수도 있고 "마감일은 목록
    두 번째 줄에 있다" 같은 문장일 수도 있다. 어느 쪽이든 그냥 사람이 준 단서로 프롬프트에
    실린다. 상한과 "그대로 베껴 쓰지 말라"는 지시는 `app/selector/repair.py` 가 건다.
    """

    hint: str = ""


class RepairOut(BaseModel):
    """AI 수정 결과. **저장하지 않는다.**

    `saved` 가 늘 거짓인 것은 자리를 채우려는 필드가 아니다. 이 응답을 읽는 쪽이 "고쳤으니
    반영됐겠지"로 넘어가지 않게 하려는 것이다. `crawlers.selectors_json` 을 바꾸는 경로는
    지금까지처럼 `PUT /api/crawlers/{id}/selectors` 하나뿐이고, 운영자가 전/후를 보고 저장을
    누른다 (`.claude/rules/llm.md`).

    `before_matches` 와 `after_matches` 는 **같은 HTML** 에 돌린 판정이다. 그래야 매칭
    개수의 차이가 셀렉터 변화 때문이라고 말할 수 있다.
    """

    id: int
    status: str
    saved: bool
    selectors: SelectorSet
    before_matches: dict[str, int]
    after_matches: dict[str, int]
    # `failed` 면 실패한 필드를 고친 것이고, `hinted` 면 실패는 없는데 운영자가 힌트로 지적한
    # 자리를 고친 것이다. 화면이 뭐라고 적을지가 여기서 갈린다
    mode: str
    targets: list[str]
    # `targets` 중 실제로 실패였던 것. 힌트가 들어오면 대상이 그보다 넓어진다 — 화면이
    # "실패한 필드 N개" 라고 적을 때 세야 하는 것은 이쪽이다
    failed_targets: list[str]
    repaired: list[str]
    unresolved: list[str]
    # 고친 뒤에도 실패로 남은 필드 전부. `unresolved` 는 이번에 고치려 한 것만이라, 대상이
    # 아니었던 실패(상세 HTML 이 없어 판정을 건너뛴 것 말고)가 여기서만 보인다
    failed_fields: list[str]
    skipped_fields: list[str]
    changes: list[SelectorChangeOut]
    notes: list[str]
    usage: UsageOut


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
    """`crawl_runs` 행에 남은 값과 같은 카운트 + 미리보기.

    `render_mode` 는 이 실행이 실제로 쓴 경로고, `saved_render_mode` 는 크롤러에 저장된
    값이다. 둘이 다르면 이번 한 번만 다른 모드로 시험한 것이고 저장값은 그대로다.
    """

    crawler_id: int
    run_id: int
    status: str
    crawler_status: str
    render_mode: str
    saved_render_mode: str
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
            if not detail_url.strip():
                # 상세 페이지 주소가 없는 사이트다. 없는 주소를 지어내 가져오지 않는다.
                # 목록만 보고 만들고, 상세 셀렉터는 볼 HTML 이 없어 판정되지 않는다
                list_html = (await source.fetch(list_url)).text
                return await generate_from_html(list_html, "", list_url=list_url)
            return await generate_for_urls(list_url, detail_url, source=source)

    return generate


def get_repairer() -> RepairFn:
    """기본 고치기 경로. 테스트는 이 의존성을 갈아끼운다.

    가져오기는 생성과 같은 경로다. HTML 은 어디에도 보관하지 않으므로 고칠 때 다시 가져오고,
    그 요청도 공용 fetch 클라이언트의 딜레이와 robots 아래에서 돈다
    (`.claude/rules/crawling.md`).
    """

    async def repair(
        list_url: str,
        detail_url: str,
        render_mode: str,
        selectors: SelectorSet,
        *,
        hint: str = "",
    ) -> RepairOutcome:
        async with open_source(render_mode, get_fetcher()) as source:
            return await repair_for_urls(list_url, detail_url, selectors, source=source, hint=hint)

    return repair


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

    if result.verification.list_fields_missing:
        # 항목은 잡혔는데 그 안이 비었다. 목록이 없는 것과 사유가 다르다 — 여기서는 목록을
        # 찾았으므로 다음 수단이 렌더 승격이 아니라 항목 셀렉터를 다시 잡는 것이다.
        failed = ", ".join(result.verification.failed_list_fields)
        matched = result.verification.summary().get("list.item", 0)
        raise HTTPException(
            status_code=422,
            detail={
                "reason": "list_fields_not_found",
                "message": (
                    f"목록 항목은 찾았으나 그 안에서 필드를 뽑지 못했다. 항목 {matched}건을 "
                    f"잡고도 {failed} 가 모두 0개 매칭이다. 항목 셀렉터가 공고 목록이 아닌 "
                    "다른 반복 요소를 잡았거나, 항목 안의 셀렉터가 실제 구조와 다르다"
                ),
                "failed_fields": result.verification.failed,
                "matches": result.verification.summary(),
            },
        )

    name = payload.name.strip() or urlsplit(payload.list_url).netloc
    # 안 적었으면 NULL 이다. 빈 문자열로 넣으면 "회사명이 있다" 와 구분되지 않는다
    default_company = payload.default_company.strip() or None
    detail_url = payload.detail_url.strip() or None
    cursor = conn.execute(
        """
        INSERT INTO crawlers
               (name, list_url, detail_url, selectors_json, status, default_company, render_mode)
        VALUES (?, ?, ?, ?, 'draft', ?, ?)
        """,
        (
            name,
            payload.list_url,
            detail_url,
            result.selectors.to_json(),
            default_company,
            render_mode,
        ),
    )
    crawler_id = int(cursor.lastrowid or 0)

    matches = result.verification.summary()
    unverified = _skipped_detail_fields(matches, detail_url)
    # 모델이 "사이트에 그 항목이 없다"고 답해 셀렉터가 비어 있는 필드. 매칭 0개지만 고칠
    # 셀렉터가 없어 실패가 아니다 (`app/selector/verify.py`)
    absent = [name for name in result.verification.skipped if name not in unverified]
    # 화면의 표 순서대로 적는다. 어느 줄이 건너뛴 것인지 위에서 아래로 짚을 수 있어야 한다
    skipped = [name for name in matches if name in unverified or name in absent]
    notes = list(result.notes)
    if unverified:
        notes.append(
            "상세 URL 이 없어 상세 셀렉터를 확인하지 못했다. 볼 페이지가 없어 판정을 건너뛴 "
            "것이라 실패가 아니다. 실제로 맞는지는 테스트 실행이 말해 준다"
        )
    if absent:
        notes.append(
            f"모델이 사이트에 없다고 답해 셀렉터가 비어 있는 필드가 있다: {', '.join(absent)}. "
            "매칭 0개지만 고칠 셀렉터가 없으므로 실패가 아니라 건너뜀이다"
        )

    return CrawlerOut(
        id=crawler_id,
        name=name,
        status="draft",
        default_company=default_company,
        render_mode=render_mode,
        detail_url=detail_url,
        selectors=result.selectors,
        matches=matches,
        # 건너뛴 필드는 실패에서 뺀다. 고칠 곳을 알려 주는 목록에 확인 못 한 것을 섞지 않는다
        failed_fields=[name for name in result.verification.failed if name not in skipped],
        skipped_fields=skipped,
        notes=notes,
        usage=UsageOut(**vars(result.usage)),
    )


def _skipped_detail_fields(matches: dict[str, int], detail_url: str | None) -> list[str]:
    """상세 URL 없이 생성했을 때 판정하지 않은 필드.

    상세 셀렉터는 모델이 낸 그대로 저장되지만 어느 HTML 에도 돌려보지 않았다. 0개 매칭을
    실패로 적으면 운영자는 고칠 곳으로 읽는데, 여기서는 볼 페이지가 없었을 뿐이다.
    """
    if detail_url:
        return []
    return [name for name in matches if name.startswith("detail.")]


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


@router.post("/{crawler_id}/repair", response_model=RepairOut)
async def repair_selectors(
    crawler_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    repair: Annotated[RepairFn, Depends(get_repairer)],
    payload: RepairIn | None = None,
) -> RepairOut:
    """실패한 필드만 모델에게 다시 고르게 한다. **저장하지 않는다.**

    저장된 셀렉터를 기준으로, 저장된 URL 을 지금 다시 가져와 판정하고, 그 자리에서 실패한
    필드만 고친다. 고친 셀렉터도 같은 HTML 에 다시 돌려 필드별 매칭 개수를 낸다 — 전과 후가
    같은 HTML 에서 나온 숫자여야 차이가 셀렉터 때문이라고 말할 수 있다.

    결과는 응답으로만 나간다. `crawlers.selectors_json` 은 이 호출로 바뀌지 않는다. 운영자가
    전/후를 보고 "셀렉터 저장" 을 누르는 것이 `.claude/rules/llm.md` 가 말하는 그 요청이고,
    누르기 전까지 DB 는 그대로다.

    고친 뒤에도 실패가 남으면 `unresolved` 에 그대로 적는다. 억지로 성공으로 만들지 않는다.

    `payload.hint` 는 운영자가 브라우저에서 보고 준 단서다. 있으면 프롬프트에 함께 실리고,
    없으면 지금까지와 같다. 힌트가 있어도 검증은 그대로다 — 고친 셀렉터는 같은 HTML 에 다시
    돌린다.
    """
    row = conn.execute(
        "SELECT list_url, detail_url, selectors_json, status, render_mode "
        "FROM crawlers WHERE id = ?",
        (crawler_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail={"message": f"크롤러 {crawler_id} 가 없다"})
    if not row["selectors_json"]:
        raise HTTPException(
            status_code=409,
            detail={"reason": "no_selectors", "message": "셀렉터가 없는 크롤러는 고칠 수 없다"},
        )

    try:
        selectors = validate_selectors(json.loads(row["selectors_json"]))
    except (json.JSONDecodeError, SelectorSchemaError) as exc:
        # 저장된 셀렉터가 스키마에 맞지 않는다. 추측해서 고치지 않고 그대로 알린다
        raise HTTPException(
            status_code=409, detail={"reason": "invalid_selectors", "message": str(exc)}
        ) from exc

    detail_url = str(row["detail_url"] or "")
    try:
        outcome = await repair(
            str(row["list_url"]),
            detail_url,
            str(row["render_mode"]),
            selectors,
            hint=payload.hint if payload else "",
        )
    except RobotsDisallowedError as exc:
        raise HTTPException(
            status_code=400, detail={"reason": "robots", "message": str(exc)}
        ) from exc
    except FetchError as exc:
        raise HTTPException(
            status_code=502, detail={"reason": exc.error_class, "message": str(exc)}
        ) from exc
    except SelectorRepairError as exc:
        # 고칠 것이 없는 것은 서버 실패가 아니라 상태다. 나머지는 생성과 같은 사유로 갈린다
        status = 409 if exc.reason == "nothing_to_repair" else 502
        raise HTTPException(
            status_code=status, detail={"reason": exc.reason, "message": str(exc)}
        ) from exc
    except SelectorGenerationError as exc:
        # 호출 경로를 생성과 공유하므로 호출 실패도 같은 예외로 온다. Gemini 한도 초과(429)가
        # 여기로 오고, 그 코드와 메시지가 그대로 화면까지 간다
        status = 500 if exc.reason == "no_api_key" else 502
        raise HTTPException(
            status_code=status, detail={"reason": exc.reason, "message": str(exc)}
        ) from exc

    after_matches = outcome.after.summary()
    unverified = _skipped_detail_fields(after_matches, detail_url or None)
    absent = [name for name in outcome.after.skipped if name not in unverified]
    skipped = [name for name in after_matches if name in unverified or name in absent]

    return RepairOut(
        id=crawler_id,
        status=str(row["status"]),
        # 이 호출은 저장하지 않는다. 읽는 쪽이 반영됐다고 넘겨짚지 않게 응답에 적어 둔다
        saved=False,
        selectors=outcome.selectors,
        before_matches=outcome.before.summary(),
        after_matches=after_matches,
        mode="hinted" if outcome.hinted_only else "failed",
        targets=outcome.targets,
        failed_targets=outcome.failed_targets,
        repaired=outcome.repaired,
        unresolved=outcome.unresolved,
        failed_fields=[name for name in outcome.after.failed if name not in skipped],
        skipped_fields=skipped,
        changes=[SelectorChangeOut(**vars(change)) for change in outcome.changes],
        notes=outcome.notes,
        usage=UsageOut(**vars(outcome.usage)),
    )


@router.post("/{crawler_id}/test-run", response_model=TestRunOut)
async def test_run(
    crawler_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    fetcher: Annotated[FetchPolicy, Depends(get_crawl_fetcher)],
    limit: Annotated[int, Query(ge=1, le=20)] = 3,
    render_mode: Annotated[str, Query()] = "",
) -> TestRunOut:
    """저장된 셀렉터로 실제 페이지를 1회 크롤링한다.

    `limit` 은 상세를 몇 건까지 따라갈지다. 테스트는 3건이면 충분하고, 전체를 도는 것은
    테스트가 아니라 그냥 크롤링이다 (`.claude/skills/crawl-test/SKILL.md`).

    `render_mode` 는 이번 한 번만 다른 경로로 시험하는 값이다. 비우면 저장된 모드로 돈다.
    값을 줘도 `crawlers.render_mode` 는 바뀌지 않는다 — 정적으로 되는지 렌더가 필요한지
    비교하는 것이 이 실행의 일이고, 시험할 때마다 저장값이 따라 바뀌면 비교가 안 된다.
    저장값을 바꾸는 것은 `PUT /api/crawlers/{id}/render-mode` 하나뿐이다.

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

    saved_mode = str(row["render_mode"])
    # 값을 줬을 때만 이번 실행의 경로가 갈린다. 저장값은 어느 쪽이든 그대로다
    used_mode = _validated_render_mode(render_mode) if render_mode.strip() else saved_mode
    async with open_source(used_mode, fetcher) as source:
        result = await run_once(
            conn,
            RunTarget(
                list_url=row["list_url"],
                selectors=selectors,
                trigger=TEST,
                crawler_id=crawler_id,
                render_mode=used_mode,
            ),
            fetcher=source,
            limit=limit,
        )

    crawler_status = row["status"]
    # 다른 모드로 한 번 시험한 실행은 상태를 올리지 않는다. 저장된 모드로 돌 때 어떻게 되는지를
    # 말해 주지 않기 때문이다 — 그것으로 tested 를 주면 승격된 워크플로우가 첫 주기에 실패한다
    if result.status == SUCCESS and crawler_status == "draft" and used_mode == saved_mode:
        conn.execute("UPDATE crawlers SET status = 'tested' WHERE id = ?", (crawler_id,))
        crawler_status = "tested"

    return TestRunOut(
        crawler_id=crawler_id,
        run_id=result.run_id,
        status=result.status,
        crawler_status=crawler_status,
        render_mode=used_mode,
        saved_render_mode=saved_mode,
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
