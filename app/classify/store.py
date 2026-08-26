"""분류 결과를 읽고 쓴다. `job_classifications` 하나만 건드린다.

`raw_jobs` 는 읽기만 한다 (`.claude/rules/data-safety.md`). 분류는 본문을 읽어 만든 값이라
출처를 고칠 이유가 없고, 고치면 분류가 틀렸을 때 되돌릴 원본이 사라진다.

`normalized_jobs` 에도 쓰지 않는다. 그 표를 갱신하는 것은 정규화 경로 하나뿐이고, 분류 결과는
정규화가 규칙 다음에 덮어 읽는다 (`app/normalize/engine.py`).

분류하지 못한 공고는 행이 없다. 빈 행을 넣으면 "분류했는데 아무것도 안 나왔다" 와 "아직
분류하지 않았다" 가 같은 모양이 되고, 다음 실행이 어느 쪽을 다시 돌아야 할지 모른다.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence

from app.classify.schema import CLASSIFY_FIELDS

# `raw_jobs.raw_data_json` 에서 본문을 꺼내는 자리. JSON 함수는 SQLite 3.38+ 에 있다
_BODY = "json_extract(r.raw_data_json, '$.body')"


def pending_ids(conn: sqlite3.Connection, limit: int | None = None) -> list[int]:
    """본문이 있고 아직 분류되지 않은 공고. 오래된 것부터다. 읽기 전용이다.

    `limit` 은 한 번에 도는 건수의 상한이다. 640건을 한 번에 돌리면 멈출 수가 없다
    (`.claude/tasks/todo/prd-llm-classify.md`).
    """
    bound = "" if limit is None else " LIMIT ?"
    params: tuple[int, ...] = () if limit is None else (limit,)
    rows = conn.execute(
        f"""
        SELECT r.id AS id
          FROM raw_jobs r
          LEFT JOIN job_classifications c ON c.raw_job_id = r.id
         WHERE c.raw_job_id IS NULL
           AND coalesce({_BODY}, '') <> ''
         ORDER BY r.id{bound}
        """,
        params,
    ).fetchall()
    return [int(row["id"]) for row in rows]


def pending_count(conn: sqlite3.Connection) -> int:
    """아직 분류되지 않은 공고 수. 화면이 "몇 건 남았나" 로 읽는다."""
    row = conn.execute(
        f"""
        SELECT count(*) AS n
          FROM raw_jobs r
          LEFT JOIN job_classifications c ON c.raw_job_id = r.id
         WHERE c.raw_job_id IS NULL
           AND coalesce({_BODY}, '') <> ''
        """
    ).fetchone()
    return int(row["n"])


def read_body(conn: sqlite3.Connection, raw_job_id: int) -> str:
    """그 공고의 본문. 없으면 빈 문자열이다. 읽기 전용이다."""
    row = conn.execute(
        f"SELECT coalesce({_BODY}, '') AS body FROM raw_jobs r WHERE r.id = ?",
        (raw_job_id,),
    ).fetchone()
    return "" if row is None else str(row["body"])


def read_classification(conn: sqlite3.Connection, raw_job_id: int) -> dict[str, str]:
    """그 공고의 분류 결과. 아직 분류되지 않았으면 빈 dict 다. 읽기 전용이다.

    빈 dict 와 "전부 빈 문자열인 dict" 는 뜻이 다르다. 앞은 아직 돌지 않은 것이고 뒤는
    돌았는데 본문이 아무것도 주지 않은 것이다.
    """
    row = conn.execute(
        f"SELECT {', '.join(CLASSIFY_FIELDS)} FROM job_classifications WHERE raw_job_id = ?",
        (raw_job_id,),
    ).fetchone()
    if row is None:
        return {}
    return {name: str(row[name] or "") for name in CLASSIFY_FIELDS}


def save_classification(
    conn: sqlite3.Connection,
    raw_job_id: int,
    fields: Mapping[str, str],
    *,
    model: str,
    dropped: Sequence[str] = (),
) -> None:
    """분류 결과를 넣거나 덮는다. 빈 값은 NULL 로 들어간다.

    덮는 것이 맞다. 분류는 본문에서 다시 만들 수 있는 값이라 이력을 쌓을 이유가 없고,
    한 공고에 결과가 둘이면 어느 쪽이 지금 값인지 알 수 없다.
    """
    columns = (*CLASSIFY_FIELDS, "dropped_fields", "model")
    values = [fields.get(name, "").strip() or None for name in CLASSIFY_FIELDS]
    values.append(", ".join(dropped))
    values.append(model)
    assignments = ", ".join(f"{name} = excluded.{name}" for name in columns)
    conn.execute(
        f"""
        INSERT INTO job_classifications (raw_job_id, {", ".join(columns)})
        VALUES ({", ".join("?" for _ in range(len(columns) + 1))})
        ON CONFLICT (raw_job_id) DO UPDATE
           SET {assignments}, classified_at = datetime('now')
        """,
        (raw_job_id, *values),
    )
