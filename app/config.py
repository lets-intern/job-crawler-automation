"""환경변수 로딩. 이름은 `.env.example` 이 문서화한다."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """`.env.example` 의 변수를 전부 읽는다. 기본값은 보수적으로(느리게) 둔다."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 셀렉터 생성. 없어도 임포트와 서버 기동은 성공한다 — 셀렉터 생성만 실패한다
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"

    # 저장
    database_path: str = "./data/jobs.db"

    # 크롤링
    crawl_user_agent: str = "job-crawler-automation (contact: unset)"
    crawl_delay_seconds: float = 3.0
    crawl_timeout_seconds: float = 20.0
    crawl_max_retries: int = 3
    # 렌더 1회의 상한. 정적 타임아웃보다 길지만 무한정 기다리지 않는다
    render_timeout_seconds: float = 60.0

    # 실행
    # 동시 실행 상한의 초기값. 한 번 app_settings 에 들어간 뒤로는 DB 값이 이긴다
    # (`app/settings.py`). 초기값으로 들어갈 값이라 여기서 범위를 지킨다
    max_concurrent_runs: int = Field(default=3, ge=1)
    run_timeout_seconds: int = 600


@lru_cache
def get_settings() -> Settings:
    return Settings()
