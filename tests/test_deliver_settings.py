"""전달 설정 저장소 (7.1.V, 7.2.V).

`app/notify/settings.py` 와 같은 자리다. 다른 점은 이 값을 실제로 쓰는 전송 경로가 아직
없다는 것뿐이다.
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import pytest

from app import db
from app.deliver.settings import DeliverConfig, DeliverSettingError, read_config, write_config


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    try:
        yield connection
    finally:
        connection.close()


def test_값이_없으면_기본값이다(conn: sqlite3.Connection) -> None:
    config = read_config(conn)

    assert config.url == ""
    assert config.method == "POST"
    assert config.batch_size == 100
    assert config.configured is False


def test_저장하고_다시_읽으면_그대로다(conn: sqlite3.Connection) -> None:
    write_config(
        conn,
        DeliverConfig(
            url="https://board.example.com/ingest",
            method="PUT",
            auth_header="X-Api-Key: secret",
            batch_size=50,
        ),
    )

    config = read_config(conn)

    assert config.url == "https://board.example.com/ingest"
    assert config.method == "PUT"
    assert config.auth_header == "X-Api-Key: secret"
    assert config.batch_size == 50
    assert config.configured is True


def test_주소를_채우면_configured가_참이다(conn: sqlite3.Connection) -> None:
    write_config(conn, DeliverConfig(url="https://x.example.com"))

    assert read_config(conn).configured is True


def test_http로_시작하지_않는_주소는_거절된다(conn: sqlite3.Connection) -> None:
    with pytest.raises(DeliverSettingError, match="http"):
        write_config(conn, DeliverConfig(url="ftp://x.example.com"))

    assert read_config(conn).url == ""


def test_get은_전달_방식이_아니다(conn: sqlite3.Connection) -> None:
    with pytest.raises(DeliverSettingError, match="전달 방식"):
        write_config(conn, DeliverConfig(url="https://x.example.com", method="GET"))


def test_1회_건수는_1_이상이어야_한다(conn: sqlite3.Connection) -> None:
    with pytest.raises(DeliverSettingError, match="1 이상"):
        write_config(conn, DeliverConfig(url="https://x.example.com", batch_size=0))


def test_거절되면_아무것도_저장되지_않는다(conn: sqlite3.Connection) -> None:
    write_config(conn, DeliverConfig(url="https://x.example.com", batch_size=10))

    with pytest.raises(DeliverSettingError):
        write_config(conn, DeliverConfig(url="ftp://bad.example.com", batch_size=10))

    # 앞서 저장된 값이 그대로다 — 거절된 시도가 절반만 반영되지 않는다
    assert read_config(conn).url == "https://x.example.com"


def test_읽지_못하는_저장값은_기본값으로_떨어진다(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO app_settings (key, value) VALUES ('deliver_batch_size', '이상한값')")
    conn.execute("INSERT INTO app_settings (key, value) VALUES ('deliver_method', 'DELETE')")

    config = read_config(conn)

    assert config.batch_size == 100
    assert config.method == "POST"
