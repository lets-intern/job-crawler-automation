"""FastAPI 앱. 스케줄러는 아직 붙지 않았다."""

from fastapi import FastAPI

from app.api import crawlers, workflows

app = FastAPI(title="job-crawler-automation")
app.include_router(crawlers.router)
app.include_router(workflows.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
