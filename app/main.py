"""FastAPI 앱. 스케줄러와 나머지 라우터는 아직 붙지 않았다."""

from fastapi import FastAPI

from app.api import crawlers

app = FastAPI(title="job-crawler-automation")
app.include_router(crawlers.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
