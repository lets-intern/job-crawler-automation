"""회사 행을 읽고 쓴다. `companies` 하나만 건드린다.

`app/settings.py` 와 같은 자리의 모듈이다 — 표 하나를 가진 저장소이고, 그 표에 쓰는 코드는
여기 말고 없다. 정규화도 화면도 이 함수들을 지나간다.

## 이름이 신원이다

로고를 공고에 잇는 값은 `normalized_jobs.company` 와 이 표의 `name` 이다. 그래서 이름이
유일하고(`migrations/0020_companies.sql`), 함수도 전부 이름으로 한 건을 찾는다. id 로 찾는
길을 따로 두면 같은 회사를 가리키는 방법이 둘이 되고, 화면과 정규화가 서로 다른 쪽을 쓴다.

`삼성전기` 와 `삼성전기(주)` 는 DB 가 다른 이름으로 본다. 그 둘을 같은 이름으로 만드는 것은
`company` 에 걸린 mapping 규칙의 일이고, 이 모듈은 정규화가 확정한 이름을 그대로 받는다.

## 지우는 함수가 없다

공고가 다 사라진 회사도 행이 남는다. 지우는 것은 운영자가 한다 —
`.claude/tasks/todo/prd-fields-and-logo.md` 4장의 결정이다. 자동으로 지우면 목록이 잠깐 빈
사이에 운영자가 올려 둔 로고 주소가 함께 사라지고, 그 파일은 저장소에 남아 아무도 찾지 못한다.

## 로고를 여기서 검사하지 않는다

`set_logo_url` 은 받은 주소를 그대로 적는다. 무엇을 받을지(파일 형식과 크기 상한)는 올리는
화면이 정한다. 빈 값은 NULL 이다 — 로고를 지우는 길이 그것 하나여야 화면이 "지움" 을 따로
만들지 않는다.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


class CompanyNotFoundError(LookupError):
    """그 이름의 회사 행이 없다. 만드는 것은 정규화가 하고, 쓰기는 있는 행에만 한다."""


class CompanyNameError(ValueError):
    """이름이 비어 있다. 이름 없는 회사 행은 어느 공고와도 이어지지 않는다."""


@dataclass(frozen=True)
class Company:
    """회사 한 행. 화면이 그리는 값 전부다."""

    id: int
    name: str
    # 그 회사의 모회사. 이름이 곧 모회사면 NULL 이다 — 자기 자신을 모회사로 적지 않는다
    parent_name: str | None = None
    # 운영자가 올린 로고의 공개 주소. 행이 만들어질 때는 비어 있다
    logo_url: str | None = None


def ensure(conn: sqlite3.Connection, name: str, parent_name: str | None = None) -> bool:
    """그 이름의 행이 있게 한다. 새로 만들었으면 참이다.

    이미 있으면 한 글자도 고치지 않는다. 정규화는 공고를 넣을 때마다 이 함수를 부르므로,
    있는 행을 덮게 두면 운영자가 화면에서 고친 모회사 이름이 다음 수집에 도로 덮인다.
    """
    cleaned = name.strip()
    if not cleaned:
        raise CompanyNameError("회사명이 비어 있다")
    parent = (parent_name or "").strip()
    cursor = conn.execute(
        """
        INSERT INTO companies (name, parent_name) VALUES (?, ?)
        ON CONFLICT (name) DO NOTHING
        """,
        (cleaned, parent or None),
    )
    return cursor.rowcount == 1


def list_all(conn: sqlite3.Connection) -> list[Company]:
    """모든 회사. 이름 순이다. 읽기 전용이다.

    공고 수로 줄 세우는 것은 화면이 한다. 그 셈은 `normalized_jobs` 를 함께 읽어야 하는데,
    이 모듈이 그 표를 읽기 시작하면 회사 하나를 고치는 일과 공고를 세는 일이 한 자리에 섞인다.
    """
    rows = conn.execute(
        "SELECT id, name, parent_name, logo_url FROM companies ORDER BY name"
    ).fetchall()
    return [_from_row(row) for row in rows]


def read(conn: sqlite3.Connection, name: str) -> Company | None:
    """그 이름의 회사. 없으면 None 이다. 읽는 김에 만들지 않는다."""
    row = conn.execute(
        "SELECT id, name, parent_name, logo_url FROM companies WHERE name = ?", (name.strip(),)
    ).fetchone()
    return None if row is None else _from_row(row)


def set_logo_url(conn: sqlite3.Connection, name: str, logo_url: str | None) -> Company:
    """로고 주소를 적는다. 빈 값이면 지운다. 행이 없으면 `CompanyNotFoundError` 다."""
    return _update(conn, name, "logo_url", (logo_url or "").strip() or None)


def set_parent_name(conn: sqlite3.Connection, name: str, parent_name: str | None) -> Company:
    """모회사 이름을 적는다. 빈 값이면 지운다. 행이 없으면 `CompanyNotFoundError` 다."""
    return _update(conn, name, "parent_name", (parent_name or "").strip() or None)


def _update(conn: sqlite3.Connection, name: str, column: str, value: str | None) -> Company:
    """칸 하나를 고치고 갱신 시각을 적는다. 컬럼 이름은 이 모듈 안에서만 온다."""
    cleaned = name.strip()
    cursor = conn.execute(
        f"UPDATE companies SET {column} = ?, updated_at = datetime('now') WHERE name = ?",
        (value, cleaned),
    )
    if cursor.rowcount == 0:
        raise CompanyNotFoundError(f"회사 행이 없다: {cleaned!r}")
    updated = read(conn, cleaned)
    if updated is None:  # pragma: no cover - 방금 고친 행이 사라지는 경로는 없다
        raise CompanyNotFoundError(f"회사 행이 없다: {cleaned!r}")
    return updated


def _from_row(row: sqlite3.Row) -> Company:
    return Company(
        id=int(row["id"]),
        name=str(row["name"]),
        parent_name=None if row["parent_name"] is None else str(row["parent_name"]),
        logo_url=None if row["logo_url"] is None else str(row["logo_url"]),
    )
