"""올라온 파일의 검증.

임의의 파일이 업로드로 들어온다. 확인하는 것은 넷이다. SQLite 인가, 우리가 읽을 테이블과
컬럼이 있는가, 마이그레이션 버전이 이 서버보다 앞서지 않는가, 크기가 상한 안인가.

거절은 사유가 서로 달라야 한다. 전부 "잘못된 파일" 로 돌아오면 운영자는 다음에 무엇을 할지
알 수 없다. 그래서 이 파일은 `reason` 값을 하나씩 단언한다.

검증만으로 이 서버의 DB 가 바뀌지 않는 것도 여기서 본다. 거절된 파일이 절반쯤 들어가 있는
상태를 만들지 않는다 (`../.claude/rules/data-safety.md`).
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import pytest

from app import db
from app.api.import_data import (
    READ_TABLES,
    ImportRejected,
    inspect_upload,
    server_version,
)

# 저장소에 있는 실제 수집 데이터. 이 기능이 실제로 받게 될 파일이다
SNAPSHOT = pathlib.Path(__file__).resolve().parent.parent / "seeds" / "snapshot" / "jobs.db"


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    """이 서버의 DB. 마이그레이션이 전부 적용된 상태다."""
    connection = db.connect(tmp_path / "server.db")
    db.migrate_up(connection)
    try:
        yield connection
    finally:
        connection.close()


def make_upload(path: pathlib.Path) -> pathlib.Path:
    """올릴 파일 하나. 같은 마이그레이션이 적용된 빈 DB 다."""
    upload = db.connect(path)
    db.migrate_up(upload)
    upload.close()
    return path


def rejected(path: pathlib.Path, conn: sqlite3.Connection) -> ImportRejected:
    with pytest.raises(ImportRejected) as caught:
        inspect_upload(path, server_version=server_version(conn))
    return caught.value


def test_정상_파일은_통과하고_버전을_돌려준다(
    conn: sqlite3.Connection, tmp_path: pathlib.Path
) -> None:
    upload = make_upload(tmp_path / "upload.db")

    assert inspect_upload(upload, server_version=server_version(conn)) == server_version(conn)


def test_저장소의_스냅샷_파일이_통과한다(conn: sqlite3.Connection) -> None:
    """실제로 쌓인 138건짜리 파일이다. 합성 픽스처만 통과하는 검증이 아니다."""
    assert SNAPSHOT.exists()

    assert inspect_upload(SNAPSHOT, server_version=server_version(conn)) == "0007"


def test_SQLite_가_아니면_not_sqlite(conn: sqlite3.Connection, tmp_path: pathlib.Path) -> None:
    path = tmp_path / "not.db"
    path.write_text("이건 그냥 텍스트다" * 100, encoding="utf-8")

    assert rejected(path, conn).reason == "not_sqlite"


def test_머리말만_흉내낸_파일도_not_sqlite(
    conn: sqlite3.Connection, tmp_path: pathlib.Path
) -> None:
    """첫 16바이트만 맞춰 놓은 파일. 열어서 읽어 봐야 갈린다."""
    path = tmp_path / "fake.db"
    path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 4096)

    assert rejected(path, conn).reason == "not_sqlite"


def test_빈_파일은_empty_file(conn: sqlite3.Connection, tmp_path: pathlib.Path) -> None:
    path = tmp_path / "empty.db"
    path.touch()

    assert rejected(path, conn).reason == "empty_file"


def test_상한을_넘으면_too_large(
    conn: sqlite3.Connection, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload = make_upload(tmp_path / "upload.db")
    monkeypatch.setattr("app.api.import_data.MAX_UPLOAD_BYTES", 10)

    failure = rejected(upload, conn)
    assert failure.reason == "too_large"
    assert "10" in failure.message


def test_우리_DB_가_아니면_missing_table(conn: sqlite3.Connection, tmp_path: pathlib.Path) -> None:
    """SQLite 이긴 한데 다른 프로그램이 만든 파일이다."""
    path = tmp_path / "other.db"
    other = sqlite3.connect(path)
    other.execute("CREATE TABLE 남의테이블 (id INTEGER)")
    other.commit()
    other.close()

    failure = rejected(path, conn)
    assert failure.reason == "missing_table"
    assert "schema_migrations" in failure.message


def test_읽을_테이블이_빠졌으면_이름을_대고_거절한다(
    conn: sqlite3.Connection, tmp_path: pathlib.Path
) -> None:
    upload = make_upload(tmp_path / "upload.db")
    source = sqlite3.connect(upload)
    source.execute("DROP TABLE job_field_overrides")
    source.commit()
    source.close()

    failure = rejected(upload, conn)
    assert failure.reason == "missing_table"
    assert "job_field_overrides" in failure.message


def test_읽을_컬럼이_빠졌으면_missing_column(
    conn: sqlite3.Connection, tmp_path: pathlib.Path
) -> None:
    """0004 이전 스키마처럼 `crawlers.default_company` 가 없는 파일."""
    upload = make_upload(tmp_path / "upload.db")
    source = sqlite3.connect(upload)
    source.execute("ALTER TABLE crawlers DROP COLUMN default_company")
    source.commit()
    source.close()

    failure = rejected(upload, conn)
    assert failure.reason == "missing_column"
    assert "default_company" in failure.message


def test_마이그레이션_버전이_앞서면_ahead_migration(
    conn: sqlite3.Connection, tmp_path: pathlib.Path
) -> None:
    """이 서버가 모르는 컬럼이 있을 수 있는 파일이다. 읽지 않는다."""
    upload = make_upload(tmp_path / "upload.db")
    source = sqlite3.connect(upload)
    source.execute(
        "INSERT INTO schema_migrations (version, name, applied_at)"
        " VALUES ('9999', 'from_the_future', '2030-01-01T00:00:00+00:00')"
    )
    source.commit()
    source.close()

    failure = rejected(upload, conn)
    assert failure.reason == "ahead_migration"
    assert "9999" in failure.message


def test_버전_기록이_비어_있으면_no_migration_version(
    conn: sqlite3.Connection, tmp_path: pathlib.Path
) -> None:
    upload = make_upload(tmp_path / "upload.db")
    source = sqlite3.connect(upload)
    source.execute("DELETE FROM schema_migrations")
    source.commit()
    source.close()

    assert rejected(upload, conn).reason == "no_migration_version"


def test_서버에_스키마가_없으면_올린_파일을_보지도_않는다(tmp_path: pathlib.Path) -> None:
    upload = make_upload(tmp_path / "upload.db")

    with pytest.raises(ImportRejected) as caught:
        inspect_upload(upload, server_version="")
    assert caught.value.reason == "server_not_migrated"


def test_거절된_검증은_이_서버의_DB_를_건드리지_않는다(
    conn: sqlite3.Connection, tmp_path: pathlib.Path
) -> None:
    """검증은 올린 파일만 읽는다. 어느 사유로 거절되든 이쪽은 그대로다."""
    before = _server_snapshot(conn)

    for path in _every_bad_upload(tmp_path):
        assert rejected(path, conn).reason

    assert _server_snapshot(conn) == before


def _server_snapshot(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    return [
        (table, int(conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]))
        for table in ("crawlers", "workflows", "raw_jobs", "normalized_jobs", "schema_migrations")
    ]


def _every_bad_upload(tmp_path: pathlib.Path) -> list[pathlib.Path]:
    not_sqlite = tmp_path / "bad_text.db"
    not_sqlite.write_text("텍스트", encoding="utf-8")

    empty = tmp_path / "bad_empty.db"
    empty.touch()

    no_table = make_upload(tmp_path / "bad_table.db")
    source = sqlite3.connect(no_table)
    source.execute("DROP TABLE raw_jobs")
    source.commit()
    source.close()

    ahead = make_upload(tmp_path / "bad_ahead.db")
    source = sqlite3.connect(ahead)
    source.execute(
        "INSERT INTO schema_migrations (version, name, applied_at)"
        " VALUES ('9999', 'from_the_future', '2030-01-01T00:00:00+00:00')"
    )
    source.commit()
    source.close()

    return [not_sqlite, empty, no_table, ahead]


def test_0021_이전에_뜬_스냅샷도_거절되지_않는다(conn: sqlite3.Connection) -> None:
    """새 표가 생겨도 그 표가 없는 옛 파일은 그대로 들어온다.

    `side_workflows` 와 `side_runs` 는 이 서버의 설정과 이 서버의 실행 기록이라 올린 파일에서
    읽을 것이 없다. 그래서 `READ_TABLES` 에 넣지 않았고, 넣지 않은 것이 옛 스냅샷이 계속
    통과한다는 뜻이다 — 넣으면 저장소의 실제 스냅샷부터 `missing_table` 로 거절된다.

    `crawl_runs` 를 가져오지 않는 것과 같은 판단이다 (`app/api/import_data.py`).
    """
    assert "side_workflows" not in READ_TABLES
    assert "side_runs" not in READ_TABLES

    assert inspect_upload(SNAPSHOT, server_version=server_version(conn))
