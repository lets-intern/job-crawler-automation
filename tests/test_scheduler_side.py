"""부가 워크플로우의 스케줄러 등록 테스트.

`tests/test_scheduler.py` 와 같은 자리이고 대상만 다르다. 확인하는 것은 "표가 이러면 잡이
이렇게 된다" 하나이고, 주기가 되면 실제로 도는지는 APScheduler 의 책임이다.

모델에도 실사이트에도 나가지 않는다. 잡이 부르는 실행 함수는 id 만 받아 적는 스텁이다.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.scheduler import (
    WorkflowScheduler,
    job_id,
    side_job_id,
    side_workflow_id_of,
    workflow_id_of,
)


@pytest.fixture
def scheduler() -> Iterator[WorkflowScheduler]:
    async def nothing(_: int) -> None:
        return None

    # 시작하지 않는다. 잡은 pending 으로 쌓이고 조회·갱신·제거는 그대로 동작한다
    instance = WorkflowScheduler(scheduler=AsyncIOScheduler(timezone="UTC"), runner=nothing)
    try:
        yield instance
    finally:
        instance.shutdown()


def test_잡_id_는_서로의_것을_읽지_않는다() -> None:
    """앞머리가 종류를 가른다. 남의 잡은 어느 쪽으로도 읽히지 않는다."""
    assert workflow_id_of(job_id(1)) == 1
    assert side_workflow_id_of(side_job_id(1)) == 1

    assert workflow_id_of(side_job_id(1)) is None
    assert side_workflow_id_of(job_id(1)) is None

    assert workflow_id_of("cleanup:snapshots") is None
    assert side_workflow_id_of("cleanup:snapshots") is None
    # 앞머리가 맞아도 뒤가 숫자가 아니면 우리 잡이 아니다
    assert side_workflow_id_of("side:classify") is None


def test_같은_id_를_등록해도_잡은_둘이다(scheduler: WorkflowScheduler) -> None:
    """`workflows` 1번과 `side_workflows` 1번은 다른 잡이다.

    두 표는 저마다 자동 증가라 1번이 둘 있다. 앞머리가 갈리지 않으면 나중에 등록되는 쪽이
    `replace_existing=True` 로 먼저 있던 잡을 덮는다.
    """

    async def nothing() -> None:
        return None

    scheduler.scheduler.add_job(
        nothing, "interval", minutes=60, id=job_id(1), replace_existing=True
    )
    scheduler.scheduler.add_job(
        nothing, "interval", minutes=30, id=side_job_id(1), replace_existing=True
    )

    assert len(scheduler.scheduler.get_jobs()) == 2
    assert scheduler.scheduler.get_job(job_id(1)) is not None
    assert scheduler.scheduler.get_job(side_job_id(1)) is not None
