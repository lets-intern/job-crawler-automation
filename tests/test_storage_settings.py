"""저장소 설정 저장소 테스트 (5.3.V).

확인하는 것은 셋이다. 값이 `app_settings` 에 들어가는지(새 표를 만들지 않는다), 저장하고
다시 읽으면 값이 그대로인지, 그리고 범위 밖 값이 사유와 함께 거절되면서 아무것도 저장하지
않는지.
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import pytest

from app import db
from app.storage import settings as store


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    try:
        yield connection
    finally:
        connection.close()


def saved(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        str(row["key"]): str(row["value"])
        for row in conn.execute("SELECT key, value FROM app_settings")
    }


def minio() -> store.StorageConfig:
    """로컬 MinIO 한 벌. 테스트가 쓰는 기준값이다."""
    return store.StorageConfig(
        endpoint="http://minio:9000",
        region="us-east-1",
        bucket="logos",
        access_key="minioadmin",
        secret_key="minioadmin",
        public_base="http://localhost:9000/logos",
    )


def test_saves_into_app_settings(conn: sqlite3.Connection) -> None:
    """새 표를 만들지 않는다. 여섯 키가 `app_settings` 에 들어간다."""
    store.write_config(conn, minio())

    rows = saved(conn)
    assert set(store.KEYS) <= set(rows)
    tables = {
        str(row["name"])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert "storage_settings" not in tables


def test_round_trip_keeps_values(conn: sqlite3.Connection) -> None:
    """저장하고 다시 읽으면 값이 그대로다."""
    written = store.write_config(conn, minio())
    assert written == minio()
    assert store.read_config(conn) == minio()


def test_defaults_before_first_save(conn: sqlite3.Connection) -> None:
    """저장한 적이 없으면 기본값이고, 아직 올릴 수 있는 상태가 아니다."""
    config = store.read_config(conn)
    assert config.endpoint == store.DEFAULT_ENDPOINT
    assert config.region == store.DEFAULT_REGION
    assert config.bucket == ""
    assert config.configured is False


def test_empty_endpoint_is_allowed(conn: sqlite3.Connection) -> None:
    """실제 S3 는 엔드포인트를 비운다. SDK 가 지역으로 주소를 만든다."""
    aws = store.StorageConfig(
        endpoint="",
        region="ap-northeast-2",
        bucket="logos",
        access_key="AKIA0000",
        secret_key="secret",
        public_base="https://logos.s3.ap-northeast-2.amazonaws.com",
    )
    assert store.write_config(conn, aws).endpoint == ""


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("endpoint", "minio:9000", "엔드포인트"),
        ("public_base", "localhost:9000", "공개 주소"),
        ("bucket", "", "버킷"),
        ("bucket", "   ", "버킷"),
        ("region", "", "지역"),
        ("access_key", "", "접근 키"),
        ("secret_key", "", "비밀 키"),
    ],
)
def test_rejects_with_reason(conn: sqlite3.Connection, field: str, value: str, reason: str) -> None:
    """범위 밖 값은 사유와 함께 거절되고, 한 벌 전체가 저장되지 않는다."""
    broken = {**minio().__dict__, field: value}
    with pytest.raises(store.StorageSettingError) as caught:
        store.write_config(conn, store.StorageConfig(**broken))

    assert reason in str(caught.value)
    assert saved(conn) == {}


def test_rejected_save_does_not_overwrite(conn: sqlite3.Connection) -> None:
    """이미 저장된 한 벌이 거절된 저장으로 흔들리지 않는다."""
    store.write_config(conn, minio())
    with pytest.raises(store.StorageSettingError):
        store.write_config(conn, store.StorageConfig(**{**minio().__dict__, "bucket": ""}))

    assert store.read_config(conn) == minio()


def test_strips_whitespace(conn: sqlite3.Connection) -> None:
    """붙여넣은 키 끝의 개행은 떨어져 나간다."""
    written = store.write_config(
        conn, store.StorageConfig(**{**minio().__dict__, "secret_key": " minioadmin\n"})
    )
    assert written.secret_key == "minioadmin"


def test_public_url_joins_once(conn: sqlite3.Connection) -> None:
    """공개 주소와 키 사이에 빗금이 하나만 남는다."""
    config = store.StorageConfig(
        **{**minio().__dict__, "public_base": "http://localhost:9000/logos/"}
    )
    assert config.public_url("acme.png") == "http://localhost:9000/logos/acme.png"


def test_mask_hides_short_values() -> None:
    """네 자리 이하는 화면에 아무것도 내보내지 않는다."""
    assert store.mask("minioadmin") == "dmin"
    assert store.mask("abcd") == ""
    assert store.mask("") == ""
