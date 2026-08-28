"""분류 결과를 읽고 쓴다. `job_classifications` 하나만 건드린다.

`raw_jobs` 는 읽기만 한다 (`.claude/rules/data-safety.md`). 분류는 본문을 읽어 만든 값이라
출처를 고칠 이유가 없고, 고치면 분류가 틀렸을 때 되돌릴 원본이 사라진다.

`normalized_jobs` 에도 쓰지 않는다. 그 표를 갱신하는 것은 정규화 경로 하나뿐이고, 분류 결과는
정규화가 규칙 다음에 덮어 읽는다 (`app/normalize/engine.py`).

분류하지 못한 공고는 행이 없다. 빈 행을 넣으면 "분류했는데 아무것도 안 나왔다" 와 "아직
분류하지 않았다" 가 같은 모양이 되고, 다음 실행이 어느 쪽을 다시 돌아야 할지 모른다.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence

from app.classify.schema import CLASSIFY_FIELDS

# `raw_jobs.raw_data_json` 에서 원문·본문·제목을 꺼내는 자리. JSON 함수는 SQLite 3.38+ 에 있다
_BODY = "json_extract(r.raw_data_json, '$.body')"
_TITLE = "json_extract(r.raw_data_json, '$.title')"
_SOURCE_TEXT = "json_extract(r.raw_data_json, '$.source_text')"

# 분류에 보내는 글. **원문이 있으면 원문이고, 없으면 본문으로 떨어진다.**
#
# 폴백이 필수다. 원문은 2026-08-28 부터 수집한 건에만 있고, 그 전에 쌓인 건에는 키가 아예
# 없다. 원문만 대상으로 삼으면 그 공고들이 분류에서 통째로 사라진다
# (`.claude/tasks/todo/prd-side-workflows.md` 4절).
#
# 상세가 API 인 사이트는 앞으로 수집하는 건에도 원문이 없다. 응답 전체는 다른 공고 목록을
# 담고 본문 경로의 부모 객체도 하나로 정해지지 않아 원문을 뽑지 않기로 했다
# (`.claude/site-recipes/source-text-container.md`). 그 넷은 계속 본문으로 돈다
_CLASSIFY_TEXT = f"coalesce(nullif({_SOURCE_TEXT}, ''), {_BODY}, '')"


def pending_ids(conn: sqlite3.Connection, limit: int | None = None) -> list[int]:
    """본문이 있고 아직 분류되지 않은 공고. **최근 수집한 것부터다.** 읽기 전용이다.

    `limit` 은 한 번에 도는 건수의 상한이다. 640건을 한 번에 돌리면 멈출 수가 없다
    (`.claude/tasks/memos/보류/llm-classify/prd-llm-classify.md`).

    2026-08-27 에 오래된 것부터에서 최근 것부터로 뒤집었다. 크레딧이 끊겨 313건이 밀려 있는데
    오래된 것부터 돌면 **오늘 들어온 공고가 맨 뒤에 선다.** 소비 측이 지금 필요한 것은 오늘
    올라온 공고이고, 밀린 것은 급하지 않다. 신규가 하루 0~1건이라 이 순서로도 밀린 것은
    결국 다 돈다.
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
         ORDER BY r.id DESC{bound}
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


def read_source(conn: sqlite3.Connection, raw_job_id: int) -> str:
    """분류에 보낼 글. 원문이 있으면 원문이고 없으면 본문이다. 읽기 전용이다.

    본문만 읽던 자리다. 원문은 본문에 더해 그 공고의 이름표 값(회사·마감·근무지·경력)을
    담고 있어, 본문만 보내면 그 값들이 어느 칸에도 들어가지 못했다
    (`.claude/site-recipes/source-text-container.md`).

    둘 다 없으면 빈 문자열이고, 부르는 쪽이 그것을 `empty_body` 로 끝낸다.
    """
    row = conn.execute(
        f"SELECT {_CLASSIFY_TEXT} AS source FROM raw_jobs r WHERE r.id = ?",
        (raw_job_id,),
    ).fetchone()
    return "" if row is None else str(row["source"])


def read_title(conn: sqlite3.Connection, raw_job_id: int) -> str:
    """그 공고의 제목. 없으면 빈 문자열이다. 읽기 전용이다.

    `job_role` 이 여기서 온다. 본문에 없고 제목에만 있는 값이라 본문만 보내면 그 칸은 영원히
    빈다 (`tests/test_job_role_source.py`).
    """
    row = conn.execute(
        f"SELECT coalesce({_TITLE}, '') AS title FROM raw_jobs r WHERE r.id = ?",
        (raw_job_id,),
    ).fetchone()
    return "" if row is None else str(row["title"])


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


def read_evidence(conn: sqlite3.Connection, raw_job_id: int) -> dict[str, str]:
    """판정 칸의 근거 문장. 아직 분류되지 않았거나 판정이 없으면 빈 dict 다. 읽기 전용이다."""
    row = conn.execute(
        "SELECT evidence_json FROM job_classifications WHERE raw_job_id = ?", (raw_job_id,)
    ).fetchone()
    if row is None:
        return {}
    try:
        parsed = json.loads(row["evidence_json"] or "{}")
    except json.JSONDecodeError:
        return {}
    return {str(k): str(v) for k, v in parsed.items()} if isinstance(parsed, dict) else {}


def save_classification(
    conn: sqlite3.Connection,
    raw_job_id: int,
    fields: Mapping[str, str],
    *,
    model: str,
    dropped: Sequence[str] = (),
    evidence: Mapping[str, str] | None = None,
) -> None:
    """분류 결과를 넣거나 덮는다. 빈 값은 NULL 로 들어간다.

    덮는 것이 맞다. 분류는 본문에서 다시 만들 수 있는 값이라 이력을 쌓을 이유가 없고,
    한 공고에 결과가 둘이면 어느 쪽이 지금 값인지 알 수 없다.

    `evidence` 는 판정 칸을 그렇게 고른 근거 문장이다. 남기지 않으면 나중에 "이 공고가 왜
    경력으로 분류됐나" 에 답할 수 없다 (`migrations/0015_classification_evidence.sql`).
    """
    columns = (*CLASSIFY_FIELDS, "dropped_fields", "model", "evidence_json")
    values = [fields.get(name, "").strip() or None for name in CLASSIFY_FIELDS]
    values.append(", ".join(dropped))
    values.append(model)
    values.append(json.dumps(dict(evidence or {}), ensure_ascii=False))
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
