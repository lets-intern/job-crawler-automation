"""실행 1회. `crawl_runs` 행 하나가 실행 하나다.

행은 시작할 때 만들고, 어떤 종료 경로에서도 종료 상태와 카운트로 갱신한다. 기록이 없는 실행은
아무도 디버깅하지 못한다 (`.claude/rules/crawling.md`).

흐름은 목록 파싱 → 신규 판정 → 신규 건만 상세 → `raw_jobs` append 다.

신규 판정을 두 단계로 나눈 이유가 하나 있다. `content_hash` 는 상세에서 오는 `body` 와
`deadline` 까지 넣어 만드는데, 상세를 가져오기 전에는 그 값이 없다. 그래서 목록 단계에서는
`source_url` 로 아는 공고인지만 보고, 아는 공고면 상세를 가져오지 않는다. 상세까지 간 건에
대해서만 `content_hash` 를 만들어 마지막으로 한 번 더 확인한다.

`raw_jobs` 는 append-only 다. 기존 행을 갱신하지 않는다 (`.claude/rules/data-safety.md`).

워크플로우가 없는 테스트 실행은 `raw_jobs` 에 적재하지 않는다. 적재할 워크플로우가 없기
때문이고, 테스트 실행이 원하는 것은 화면에 보여줄 미리보기이지 수집 데이터가 아니다.
그 실행의 `new_count` 는 0 이다 — 적재한 것이 없다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from dataclasses import dataclass, field

from app.config import get_settings
from app.crawler.failures import FAILED, ZERO_ITEM_MESSAGE, Failure, classify, run_status
from app.crawler.fetcher import Fetcher, get_fetcher
from app.crawler.hashing import content_hash
from app.crawler.parser import ListItem, parse_detail, parse_list
from app.selector.schema import SelectorSchemaError, SelectorSet, validate_selectors

logger = logging.getLogger(__name__)

# 항목 하나가 어떻게 끝났는가. 미리보기 표가 그대로 읽는다.
STORED = "stored"
KNOWN = "known"
PREVIEW = "preview"


@dataclass(frozen=True)
class RunTarget:
    """무엇을 실행하는가. `workflow_id` 와 `crawler_id` 중 하나는 있어야 한다."""

    list_url: str
    selectors: SelectorSet
    workflow_id: int | None = None
    crawler_id: int | None = None

    def __post_init__(self) -> None:
        if self.workflow_id is None and self.crawler_id is None:
            raise ValueError("workflow_id 나 crawler_id 중 하나는 있어야 한다")


@dataclass(frozen=True)
class ItemResult:
    """항목 하나의 결과. `fields` 는 셀렉터로 뽑은 값 그대로다."""

    source_url: str
    state: str
    fields: dict[str, str]


@dataclass(frozen=True)
class ItemFailure:
    source_url: str
    error_class: str | None
    message: str


@dataclass
class RunResult:
    """`crawl_runs` 행에 들어간 값 그대로 + 미리보기."""

    run_id: int
    status: str
    matched: int = 0
    success_count: int = 0
    new_count: int = 0
    fail_count: int = 0
    error_class: str | None = None
    error_message: str = ""
    items: list[ItemResult] = field(default_factory=list)
    failures: list[ItemFailure] = field(default_factory=list)


class WorkflowMissingError(LookupError):
    """워크플로우 행이 없다. `crawl_runs` 행을 만들 수 없어 기록도 남지 않는다."""


async def run_workflow(
    conn: sqlite3.Connection,
    workflow_id: int,
    *,
    fetcher: Fetcher | None = None,
    limit: int | None = None,
    timeout_seconds: float | None = None,
) -> RunResult:
    """스케줄러가 부르는 진입점. 무엇을 실행할지는 매번 테이블에서 다시 읽는다.

    `workflows` 와 `crawlers` 가 진실이다. 잡을 등록할 때의 값을 스케줄러가 들고 있다가
    쓰지 않는다 (`.claude/rules/crawling.md`).

    실행은 `RUN_TIMEOUT_SECONDS` 로 감싼다. 끝나지 않는 실행 하나가 동시 실행 자리를 영원히
    붙들고 있으면 나머지 워크플로우가 전부 멈춘다.

    셀렉터가 없거나 스키마에 맞지 않으면 실행하지 못하지만, 그것도 종료 경로다.
    `crawl_runs` 행을 실패로 남긴다.
    """
    row = conn.execute(
        """
        SELECT c.list_url AS list_url, c.selectors_json AS selectors_json
          FROM workflows w
          JOIN crawlers c ON c.id = w.crawler_id
         WHERE w.id = ?
        """,
        (workflow_id,),
    ).fetchone()
    if row is None:
        raise WorkflowMissingError(f"워크플로우 {workflow_id} 가 없다")

    try:
        selectors = validate_selectors(json.loads(row["selectors_json"] or "null"))
    except (json.JSONDecodeError, SelectorSchemaError) as exc:
        # 저장된 셀렉터가 실행할 수 있는 상태가 아니다. transport·selector_miss·parse 중
        # 어느 것도 아니므로 error_class 는 비워 두고 사유만 남긴다.
        return _config_failure(conn, workflow_id, f"셀렉터를 읽을 수 없다: {exc}")

    bound = timeout_seconds if timeout_seconds is not None else get_settings().run_timeout_seconds
    return await run_once(
        conn,
        RunTarget(list_url=row["list_url"], selectors=selectors, workflow_id=workflow_id),
        fetcher=fetcher,
        limit=limit,
        timeout_seconds=bound,
    )


def _config_failure(conn: sqlite3.Connection, workflow_id: int, message: str) -> RunResult:
    cursor = conn.execute(
        "INSERT INTO crawl_runs (workflow_id) VALUES (?)",
        (workflow_id,),
    )
    result = RunResult(run_id=int(cursor.lastrowid or 0), status="")
    _finish_run(conn, result, Failure(error_class=None, message=message))
    return result


async def run_once(
    conn: sqlite3.Connection,
    target: RunTarget,
    *,
    fetcher: Fetcher | None = None,
    limit: int | None = None,
    timeout_seconds: float | None = None,
) -> RunResult:
    """1회 실행. 예외를 밖으로 던지지 않고 실패한 `RunResult` 로 돌려준다.

    `timeout_seconds` 가 있으면 그 시간을 넘긴 실행은 중단되고 `status=timeout` 으로 남는다.
    None 이면 시간 제한을 걸지 않는다 — 항목 수를 정해 놓고 도는 테스트 실행이 그렇다.

    시간 제한에 걸려도 그때까지 적재한 `raw_jobs` 는 지우지 않는다. append-only 라 되돌리지
    않고, 다음 실행이 같은 공고를 다시 넣지도 않는다 (`.claude/rules/data-safety.md`).
    """
    client = fetcher or get_fetcher()
    run_id = _start_run(conn, target)
    result = RunResult(run_id=run_id, status="")
    failure: Failure | None = None
    timed_out = False

    try:
        # asyncio.timeout 은 안쪽의 취소를 경계에서 TimeoutError 로 바꿔 준다. 그래서 아래
        # BaseException 절(밖에서 온 취소)과 시간 제한이 섞이지 않는다
        async with asyncio.timeout(timeout_seconds) as bound:
            await _crawl(conn, target, client, limit, result)
    except TimeoutError as exc:
        # 제한을 넘겨서 끊긴 것인지, 안쪽에서 올라온 TimeoutError 인지 구분한다.
        # 후자를 timeout 으로 적으면 사이트 문제를 실행 시간 문제로 잘못 읽게 된다
        if not bound.expired():
            failure = classify(exc)
        else:
            timed_out = True
            failure = Failure(
                error_class=None,
                message=f"실행이 시간 제한 {timeout_seconds}초를 넘겨 중단됐다",
            )
    except Exception as exc:
        failure = classify(exc)
    except BaseException as exc:
        # 취소·강제 종료도 종료 경로다. 행을 남기고 나서 그대로 올려보낸다.
        _finish_run(conn, result, classify(exc))
        raise

    _finish_run(conn, result, failure, timed_out=timed_out)
    return result


async def _crawl(
    conn: sqlite3.Connection,
    target: RunTarget,
    fetcher: Fetcher,
    limit: int | None,
    result: RunResult,
) -> None:
    page = await fetcher.fetch(target.list_url)
    parsed = parse_list(page.text, target.selectors.list, page.url)

    result.matched = parsed.matched
    for miss in parsed.failures:
        result.fail_count += 1
        result.failures.append(
            ItemFailure(
                source_url=f"{target.list_url}#{miss.index}",
                error_class="parse",
                message=f"list.{miss.field}: {miss.message}",
            )
        )

    for item in parsed.items[:limit]:
        try:
            collected = await _collect(conn, target, item, fetcher)
        except Exception as exc:
            # 항목 하나가 실패해도 나머지는 계속 간다. 실패는 fail_count 로 남는다.
            classified = classify(exc)
            result.fail_count += 1
            result.failures.append(
                ItemFailure(
                    source_url=item.link,
                    error_class=classified.error_class,
                    message=classified.message,
                )
            )
            continue

        result.items.append(collected)
        result.success_count += 1
        if collected.state == STORED:
            result.new_count += 1


async def _collect(
    conn: sqlite3.Connection, target: RunTarget, item: ListItem, fetcher: Fetcher
) -> ItemResult:
    """항목 하나를 처리한다. 아는 공고면 상세를 가져오지 않는다."""
    if _is_known(conn, target.workflow_id, "source_url", item.link):
        return ItemResult(source_url=item.link, state=KNOWN, fields={})

    page = await fetcher.fetch(item.link)
    detail = parse_detail(page.text, target.selectors.detail)
    record = _record(item, detail.fields)
    digest = content_hash(record)

    if target.workflow_id is None:
        # 테스트 실행. 미리보기만 돌려주고 적재하지 않는다.
        return ItemResult(source_url=item.link, state=PREVIEW, fields=record)

    if _is_known(conn, target.workflow_id, "content_hash", digest):
        return ItemResult(source_url=item.link, state=KNOWN, fields=record)

    conn.execute(
        """
        INSERT INTO raw_jobs (workflow_id, source_url, raw_data_json, content_hash)
        VALUES (?, ?, ?, ?)
        """,
        (
            target.workflow_id,
            item.link,
            json.dumps(record, ensure_ascii=False),
            digest,
        ),
    )
    return ItemResult(source_url=item.link, state=STORED, fields=record)


def _record(item: ListItem, detail: dict[str, str]) -> dict[str, str]:
    """`raw_jobs.raw_data_json` 에 그대로 들어가는 값. 정제하지 않는다."""
    return {
        "source_url": item.link,
        "title": detail["title"],
        "body": detail["body"],
        "requirements": detail["requirements"],
        "deadline": detail["deadline"],
        "department": detail["department"],
        "list_title": item.title,
        "list_date": item.date,
    }


def _is_known(conn: sqlite3.Connection, workflow_id: int | None, column: str, value: str) -> bool:
    """이미 적재한 공고인지 본다. 적재하지 않는 실행에는 아는 공고가 없다."""
    if workflow_id is None:
        return False
    # column 은 이 모듈 안에서 넘기는 고정 값 둘뿐이다. 밖에서 오는 값이 들어오지 않는다.
    row = conn.execute(
        f"SELECT 1 FROM raw_jobs WHERE workflow_id = ? AND {column} = ? LIMIT 1",
        (workflow_id, value),
    ).fetchone()
    return row is not None


def _start_run(conn: sqlite3.Connection, target: RunTarget) -> int:
    # started_at 은 테이블 기본값(datetime('now'))이 채운다. 다른 테이블과 같은 형식이어야 한다.
    cursor = conn.execute(
        "INSERT INTO crawl_runs (workflow_id, crawler_id) VALUES (?, ?)",
        (target.workflow_id, target.crawler_id),
    )
    return int(cursor.lastrowid or 0)


def _finish_run(
    conn: sqlite3.Connection,
    result: RunResult,
    failure: Failure | None,
    *,
    timed_out: bool = False,
) -> None:
    """종료 상태와 카운트를 확정한다. 정상 파싱 0건은 실패다."""
    result.status = run_status(result.success_count, failure, timed_out=timed_out)
    if failure is not None:
        result.error_class = failure.error_class
        result.error_message = failure.message
    elif result.status == FAILED:
        # 실행 전체는 예외 없이 끝났는데 남은 항목이 0건인 경우다. 항목별 실패가 있으면 그
        # 분류를 그대로 쓰고, 없으면 모르는 채로 둔다. 추측해서 셋 중 하나로 적지 않는다.
        first = result.failures[0] if result.failures else None
        result.error_class = first.error_class if first is not None else None
        result.error_message = ZERO_ITEM_MESSAGE
        if first is not None:
            result.error_message = f"{ZERO_ITEM_MESSAGE}: {first.message}"

    conn.execute(
        """
        UPDATE crawl_runs
           SET finished_at = datetime('now'), status = ?, success_count = ?, new_count = ?,
               fail_count = ?, error_class = ?, error_message = ?
         WHERE id = ?
        """,
        (
            result.status,
            result.success_count,
            result.new_count,
            result.fail_count,
            result.error_class,
            result.error_message or None,
            result.run_id,
        ),
    )
    logger.info(
        "run %s %s: matched=%s success=%s new=%s fail=%s error_class=%s",
        result.run_id,
        result.status,
        result.matched,
        result.success_count,
        result.new_count,
        result.fail_count,
        result.error_class,
    )
