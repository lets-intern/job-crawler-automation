"""올라온 SQLite 파일을 검증하고 기존 데이터에 더한다.

배포된 서버는 빈 DB 로 시작한다. 로컬에 쌓인 수집 데이터를 옮길 길이 화면에 없으면 운영자는
SSH 와 `docker cp` 로 파일을 밀어 넣게 되고, 그것은 이 서비스가 쓰라고 만든 길이 아니다.

## 덮지 않는다. 더한다

`raw_jobs` 는 append-only 다 (`.claude/rules/data-safety.md`). 올린 파일의 내용으로 기존 행을
고치지 않는다. 없는 것만 넣고, 있는 것은 건너뛴 건수로만 보고한다.

같은 공고인지는 `content_hash` 가 가른다. 그 값은 `app/crawler/hashing.py` 가 만들고 여기서
다시 만들지 않는다 — 올린 파일에 적힌 해시를 믿는 대신 `raw_data_json` 에서 같은 함수로 다시
계산한다. 그래야 이 서버가 이미 가진 행과 같은 잣대로 비교된다.

## 정규화 값은 가져오지 않는다

올린 파일의 `normalized_jobs` 는 읽지 않는다. 가져온 `raw_jobs` 를 **이 서버의**
`normalization_rules` 로 다시 정규화한다. 저쪽 규칙이 만든 값을 그대로 들여오면 이 서버의
규칙과 어긋난 채로 남는다. 그 어긋남은 다음 재정규화에서 값이 바뀌고서야 드러나고, 그때는
왜 바뀌었는지 아무도 모른다.

규칙 자체는 가져온다. 화면에서 한 줄씩 만든 것이라 안 가져오면 새 서버에서 전부 다시 만들어야
한다. 다만 들여오는 방식은 다른 테이블과 같다 — 없는 것만 더하고, 있는 규칙은 건드리지
않는다. 같은 규칙인지는 `field_name`, `rule_type`, `rule_config_json`, `priority` 넷으로
가른다. `note` 는 사람이 읽는 이름표라 판정에 넣지 않는다 — 넣으면 메모만 다른 같은 규칙이
두 벌 쌓이고, 정규화는 그 둘을 차례로 태운다.

순서는 규칙이 먼저, 정규화가 나중이다. 그래야 방금 들여온 규칙이 방금 들여온 공고에 적용된다.

## delivered_at 은 가져오지 않는다

저쪽에서 이미 전달된 행이라도 이 서버의 소비 측은 그것을 받은 적이 없다. 전달 표시를 들여오면
소비 측이 영영 못 받는 공고가 생긴다. 가져온 행은 전부 미전달로 들어간다. 이 파일에
`delivered_at` 을 적는 문장이 없는 것이 그 보장이다 (`.claude/rules/data-safety.md`).

## crawl_runs 도 가져오지 않는다

저쪽 서버의 실행 기록이다. 이 서버에서 일어나지 않은 실행을 이 서버의 통계에 섞으면 "주기가
실제로 도는가" 라는 질문에 답할 수 없게 된다. 같은 이유로 `workflows` 의 누적 카운트와 마지막
실행 시각도 가져오지 않는다.

## 올라온 파일은 신뢰하지 않는다

임의의 파일이 들어온다. 손대기 전에 SQLite 인지, 우리가 읽을 테이블과 컬럼이 있는지,
마이그레이션 버전이 이 서버보다 앞서지 않는지 본다. 앞선 파일은 거절한다 — 이 서버가 모르는
컬럼을 읽을 방법이 없다.

거절 사유는 무엇이 틀렸는지 이름을 댄다. "잘못된 파일" 은 운영자가 다음에 무엇을 할지
알려주지 않는다.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app import db

# 올릴 수 있는 파일 크기 상한. 공고 한 건이 4KB 쯤이므로 64MB 는 1만 건을 훨씬 넘는다
# (`seeds/snapshot/README.md`). 상한이 없으면 디스크가 상한이 된다
MAX_UPLOAD_BYTES = 64 * 1024 * 1024

# SQLite 파일의 첫 16바이트. 확장자가 아니라 내용으로 판정한다
SQLITE_MAGIC = b"SQLite format 3\x00"

# 병합이 실제로 읽는 테이블과 컬럼. 읽지 않는 것은 요구하지 않는다 — `normalized_jobs` 와
# `crawl_runs` 가 없는 파일도 가져올 것은 다 가져올 수 있다
READ_TABLES: dict[str, tuple[str, ...]] = {
    "schema_migrations": ("version",),
    "crawlers": (
        "id",
        "name",
        "list_url",
        "detail_url",
        "selectors_json",
        "render_mode",
        "status",
        "default_company",
    ),
    "workflows": ("id", "crawler_id", "name", "interval_minutes", "status", "auto_stop_threshold"),
    "normalization_rules": (
        "field_name",
        "rule_type",
        "rule_config_json",
        "priority",
        "enabled",
        "note",
    ),
    "raw_jobs": ("id", "workflow_id", "source_url", "raw_data_json", "crawled_at"),
    "job_field_overrides": ("raw_job_id", "field_name", "value", "created_at", "updated_at"),
}


class ImportRejected(Exception):
    """올린 파일을 가져가지 않는다. `reason` 이 무엇이 틀렸는지를 이름으로 말한다."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


def server_version(conn: sqlite3.Connection) -> str:
    """이 서버에 적용된 마지막 마이그레이션 버전. 하나도 없으면 빈 문자열이다."""
    applied = db.applied_versions(conn)
    return applied[-1] if applied else ""


def inspect_upload(path: Path, *, server_version: str) -> str:
    """검증한다. 통과하면 올린 파일의 마이그레이션 버전을 돌려준다.

    여기서는 올린 파일만 읽는다. 검증만으로 이 서버의 DB 는 한 글자도 바뀌지 않는다.
    """
    if not server_version:
        raise ImportRejected(
            "server_not_migrated",
            "이 서버에 스키마가 아직 없다. 마이그레이션을 먼저 적용한다",
        )

    _check_size(path)
    _check_magic(path)

    source = _open_read_only(path)
    try:
        tables = _table_names(source)
        if "schema_migrations" not in tables:
            raise ImportRejected(
                "missing_table",
                "schema_migrations 테이블이 없다. 이 서비스가 만든 DB 파일이 아니다",
            )
        version = _upload_version(source)
        if version > server_version:
            raise ImportRejected(
                "ahead_migration",
                f"올린 파일의 마이그레이션 버전 {version} 이 이 서버 {server_version} 보다"
                " 앞선다. 이 서버가 모르는 컬럼은 읽을 수 없다",
            )
        _check_tables(source, tables)
    finally:
        source.close()
    return version


def _check_size(path: Path) -> None:
    size = path.stat().st_size
    if size == 0:
        raise ImportRejected("empty_file", "빈 파일이다")
    if size > MAX_UPLOAD_BYTES:
        raise ImportRejected(
            "too_large",
            f"파일이 {size}바이트다. 상한은 {MAX_UPLOAD_BYTES}바이트다",
        )


def _check_magic(path: Path) -> None:
    with path.open("rb") as handle:
        header = handle.read(len(SQLITE_MAGIC))
    if header != SQLITE_MAGIC:
        raise ImportRejected("not_sqlite", "SQLite 파일이 아니다. 파일 머리말이 맞지 않는다")


def _open_read_only(path: Path) -> sqlite3.Connection:
    """읽기 전용으로 연다. 올린 파일에는 쓰지 않는다."""
    uri = f"file:{path}?mode=ro"
    try:
        source = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise ImportRejected("not_sqlite", f"파일을 열지 못했다: {exc}") from exc
    source.row_factory = sqlite3.Row
    try:
        source.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlite3.DatabaseError as exc:
        source.close()
        raise ImportRejected("not_sqlite", f"SQLite 파일로 읽지 못했다: {exc}") from exc
    return source


def _table_names(source: sqlite3.Connection) -> set[str]:
    rows = source.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row["name"]) for row in rows}


def _upload_version(source: sqlite3.Connection) -> str:
    row = source.execute("SELECT max(version) AS version FROM schema_migrations").fetchone()
    version = row["version"] if row is not None else None
    if version is None:
        raise ImportRejected(
            "no_migration_version",
            "schema_migrations 가 비어 있다. 어느 스키마인지 알 수 없다",
        )
    return str(version)


def _check_tables(source: sqlite3.Connection, tables: set[str]) -> None:
    for table, columns in READ_TABLES.items():
        if table not in tables:
            raise ImportRejected("missing_table", f"{table} 테이블이 없다")
        present = {
            str(row["name"]) for row in source.execute(f"PRAGMA table_info({table})").fetchall()
        }
        missing = [column for column in columns if column not in present]
        if missing:
            raise ImportRejected(
                "missing_column",
                f"{table} 에 컬럼이 없다: {', '.join(missing)}",
            )
