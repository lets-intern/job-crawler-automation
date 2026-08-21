"""실행 실패를 `crawl_runs.error_class` 로 옮기는 한 곳.

세 값으로 나뉘어 있는 이유는 조치가 각각 다르기 때문이다 (`.claude/rules/crawling.md`).

| error_class | 무슨 일이 있었나 | 조치 |
|---|---|---|
| `transport` | 타임아웃, 5xx, 연결 끊김 | 백오프 재시도. 반복되면 사이트 상태 확인 |
| `selector_miss` | 가져왔는데 item 이 0개 매칭 | 재시도 금지. 셀렉터 재작성 |
| `parse` | 매칭은 됐는데 필드를 못 읽었다 | 그 필드 셀렉터만 보정 |

분류를 모르는 예외는 `parse` 로 밀어 넣지 않는다. `error_class` 를 NULL 로 두고 예외 이름을
`error_message` 에 남긴다 — 모르는 실패를 아는 실패로 위장하면 그 사이트를 계속 잘못 고치게 된다.

성공 판정도 여기 있다. **정상 파싱 0건은 실패다.** 신규 0건인 정상 실행과 같은 결과로 남기면
마크업이 바뀐 사이트와 새 공고가 없는 사이트를 구분할 수 없다 (`CLAUDE.md`).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.crawler.fetcher import FetchError
from app.crawler.parser import CrawlDataError

# `crawl_runs.error_class` 의 CHECK 제약과 같은 값이어야 한다.
ERROR_CLASSES: tuple[str, ...] = ("transport", "selector_miss", "parse")

SUCCESS = "success"
FAILED = "failed"

ZERO_ITEM_MESSAGE = "정상 파싱된 항목이 0건이다. 신규 0건인 정상 실행이 아니라 실패다"


@dataclass(frozen=True)
class Failure:
    """`crawl_runs` 의 `error_class`, `error_message` 한 쌍."""

    error_class: str | None
    message: str


def classify(exc: BaseException) -> Failure:
    """예외를 `error_class` 로 옮긴다. 모르는 예외는 `error_class` 없이 남긴다."""
    if isinstance(exc, FetchError | CrawlDataError):
        return Failure(error_class=exc.error_class, message=str(exc))
    return Failure(error_class=None, message=f"분류되지 않은 실패({type(exc).__name__}): {exc}")


def run_status(success_count: int, failure: Failure | None = None) -> str:
    """실행 하나의 종료 상태. 실패가 있거나 정상 파싱이 0건이면 `failed` 다."""
    if failure is not None or success_count == 0:
        return FAILED
    return SUCCESS
