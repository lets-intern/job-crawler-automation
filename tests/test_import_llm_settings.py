"""가져오기가 AI 제공자 설정을 같이 옮기는지 (2.8.V).

**키가 같이 옮겨지는 것은 결정된 사항이다** (2026-08-27). 서버를 옮길 때 키를 다시 넣지
않아도 되는 편이 낫다는 판단이고, 그 대가로 스냅샷 파일 자체가 자격증명이 된다.

확인하는 것은 셋이다. 빈 서버에는 들어오는가, 이미 값이 있으면 덮지 않는가, 그리고 제공자
설정 말고 다른 운영 설정까지 따라오지는 않는가 — 알림 주소와 동시 실행 상한이 남의 파일
하나로 바뀌면 이 서버의 운영 설정을 아무도 설명할 수 없다.
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import pytest

from app import db
from app.api.import_data import import_database
from app.llm import settings as store
from app.llm.log import CLASSIFY
from tests.test_import_merge import job, make_upload
from tests.test_llm_settings import env

UPLOAD_KEY = "sk-저쪽-서버의-키-9999"


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "server.db")
    db.migrate_up(connection)
    try:
        yield connection
    finally:
        connection.close()


def upload_with(tmp_path: pathlib.Path, values: dict[str, str]) -> pathlib.Path:
    """저쪽 서버가 내보낸 파일. `app_settings` 에 값이 들어 있다."""
    path = make_upload(tmp_path / "upload.db", jobs=[job("공고")])
    source = db.connect(path)
    source.executemany("INSERT INTO app_settings (key, value) VALUES (?, ?)", list(values.items()))
    source.close()
    return path


def stored(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        str(row["key"]): str(row["value"])
        for row in conn.execute("SELECT key, value FROM app_settings")
    }


def test_빈_서버에_키와_기능_선택이_따라온다(
    conn: sqlite3.Connection, tmp_path: pathlib.Path
) -> None:
    path = upload_with(
        tmp_path,
        {
            store.key_row("qwen"): UPLOAD_KEY,
            store.provider_row(CLASSIFY): "qwen",
            store.model_row(CLASSIFY): "qwen3.8-flash",
        },
    )

    result = import_database(conn, path)

    assert result.llm_added == 3
    assert result.llm_skipped == 0
    config = store.read_config(conn, env(qwen_api_key=""))
    assert config.key("qwen").tail == "9999"
    assert config.key("qwen").stored is True
    assert store.settings_for(conn, CLASSIFY, env()).qwen_model == "qwen3.8-flash"


def test_이미_있는_값은_덮지_않는다(conn: sqlite3.Connection, tmp_path: pathlib.Path) -> None:
    """지금 도는 서버의 키가 남의 파일로 조용히 바뀌면 다음 호출이 어느 계정에서 나가는지
    아무도 모른다. 가져오기 전체의 규칙과 같다 — 없는 것만 더한다."""
    store.write_key(conn, "qwen", "sk-이-서버의-키-0000", env())
    path = upload_with(
        tmp_path, {store.key_row("qwen"): UPLOAD_KEY, store.provider_row(CLASSIFY): "qwen"}
    )

    result = import_database(conn, path)

    assert result.llm_added == 1
    assert result.llm_skipped == 1
    assert stored(conn)[store.key_row("qwen")] == "sk-이-서버의-키-0000"


def test_제공자_설정_밖의_운영_설정은_따라오지_않는다(
    conn: sqlite3.Connection, tmp_path: pathlib.Path
) -> None:
    path = upload_with(
        tmp_path,
        {
            store.key_row("gpt"): UPLOAD_KEY,
            "ntfy_server_url": "https://저쪽.example",
            "max_concurrent_runs": "99",
        },
    )

    import_database(conn, path)

    assert set(stored(conn)) == {store.key_row("gpt")}


def test_app_settings_가_없는_파일도_나머지는_들어온다(
    conn: sqlite3.Connection, tmp_path: pathlib.Path
) -> None:
    """읽지 않는 표를 요구하지 않는 것이 이 가져오기의 원칙이다."""
    path = make_upload(tmp_path / "upload.db", jobs=[job("공고")])
    source = db.connect(path)
    source.execute("DROP TABLE app_settings")
    source.close()

    result = import_database(conn, path)

    assert result.llm_added == 0
    assert result.crawlers_added == 1
    assert result.raw_added == 1
