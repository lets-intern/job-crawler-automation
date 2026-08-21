"""설정 로딩 테스트."""

import pathlib

import pytest

from app.config import Settings, get_settings

ENV_NAMES = [
    "ANTHROPIC_API_KEY",
    "DATABASE_PATH",
    "CRAWL_USER_AGENT",
    "CRAWL_DELAY_SECONDS",
    "CRAWL_TIMEOUT_SECONDS",
    "CRAWL_MAX_RETRIES",
    "MAX_CONCURRENT_RUNS",
    "RUN_TIMEOUT_SECONDS",
]


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    """환경변수를 걷어내고, `.env` 가 없는 디렉터리로 옮겨 순수 기본값만 남긴다."""
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)


def test_defaults_are_conservative(clean_env: None) -> None:
    settings = Settings()

    assert settings.database_path == "./data/jobs.db"
    assert settings.crawl_delay_seconds == 3.0
    assert settings.crawl_timeout_seconds == 20.0
    assert settings.crawl_max_retries == 3
    assert settings.max_concurrent_runs == 3
    assert settings.run_timeout_seconds == 600
    assert "job-crawler-automation" in settings.crawl_user_agent


def test_env_overrides_defaults(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", "/srv/other.db")
    monkeypatch.setenv("CRAWL_DELAY_SECONDS", "9.5")
    monkeypatch.setenv("MAX_CONCURRENT_RUNS", "1")

    settings = Settings()

    assert settings.database_path == "/srv/other.db"
    assert settings.crawl_delay_seconds == 9.5
    assert settings.max_concurrent_runs == 1


def test_loads_without_api_key(clean_env: None) -> None:
    """키가 없어도 설정 로딩은 성공한다. 실패하는 것은 셀렉터 생성뿐이다."""
    settings = Settings()

    assert settings.anthropic_api_key == ""


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
