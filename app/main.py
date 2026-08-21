"""FastAPI 앱. 라우터·스케줄러·DB 는 아직 붙지 않았다."""

from fastapi import FastAPI

app = FastAPI(title="job-crawler-automation")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
