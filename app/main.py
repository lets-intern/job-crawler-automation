"""FastAPI 앱. 라우터 등록과 스케줄러 기동."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import db
from app.api import (
    crawlers,
    rules,
    settings,
    ui,
    ui_crawlers,
    ui_jobs,
    ui_rules,
    ui_settings,
    ui_tests,
    ui_workflows,
    workflows,
)
from app.crawler.fetcher import close_fetcher
from app.scheduler import get_scheduler, shutdown_scheduler


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """기동 시 `workflows` 테이블에서 잡을 등록한다. 스키마 적용은 CLI 가 한다."""
    conn = db.connect()
    try:
        get_scheduler().start(conn)
    finally:
        conn.close()
    try:
        yield
    finally:
        shutdown_scheduler()
        await close_fetcher()


app = FastAPI(title="job-crawler-automation", lifespan=lifespan)
app.include_router(crawlers.router)
app.include_router(workflows.router)
app.include_router(settings.router)
app.include_router(rules.router)
# 화면. API 라우터 뒤에 붙인다 — `/api/...` 가 먼저 잡힌다
app.include_router(ui.router)
app.include_router(ui_crawlers.router)
app.include_router(ui_tests.router)
app.include_router(ui_workflows.router)
app.include_router(ui_rules.router)
app.include_router(ui_jobs.router)
app.include_router(ui_settings.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
