"""DB 에 저장되는 운영 설정.

환경변수와 역할이 다르다. 환경변수는 배포가 정하는 값이고, 여기 있는 것은 운영자가 돌아가는
중에 바꾸는 값이다. 그래서 값이 아직 없을 때만 환경변수에서 채우고, 한 번 들어간 뒤로는
DB 가 이긴다. 환경변수를 나중에 고쳐도 저장된 값을 덮지 않는다.

여기 있는 것은 둘뿐이다. 환경변수로 충분한 값을 여기로 옮기면 같은 설정이 두 곳에 생기고,
어느 쪽이 진실인지 매번 확인해야 한다 (`.claude/rules/core.md` 단순함 우선).
"""

from __future__ import annotations

import sqlite3

from app.config import get_settings

MAX_CONCURRENT_RUNS = "max_concurrent_runs"

# 워크플로우의 **첫 실행**이 담을 항목 수의 상한. 0 이면 상한 없음이다.
#
# 사이트를 등록하면 목록에 걸린 과거 공고가 통째로 들어온다. 2026-08-26 에 열두 곳을 등록하며
# 670건이 그렇게 들어왔고, 그 뒤 실행은 신규 0~1건이다. 저장량과 분류 토큰이 튀는 자리가
# 평소 수집이 아니라 이 첫 실행이다.
#
# 두 번째 실행부터는 적용하지 않는다. 상한이 계속 걸려 있으면 목록이 상한보다 길게 밀린 날에
# 뒤쪽 공고를 영영 못 본다 — 그날 한 번 놓친 것이 다시 올라오지 않는다.
FIRST_RUN_LIMIT = "first_run_limit"

KEYS: tuple[str, ...] = (MAX_CONCURRENT_RUNS, FIRST_RUN_LIMIT)


class UnknownSettingError(KeyError):
    """이 저장소가 모르는 키. 새 키는 코드에서 먼저 정한다."""


class SettingValueError(ValueError):
    """값이 이 키가 받을 수 있는 범위 밖이다."""


def _validate(key: str, value: int) -> int:
    if key == MAX_CONCURRENT_RUNS and value < 1:
        raise SettingValueError(f"{key} 는 1 이상의 정수여야 한다: {value}")
    if key == FIRST_RUN_LIMIT and value < 0:
        raise SettingValueError(f"{key} 는 0 이상의 정수여야 한다(0 은 상한 없음): {value}")
    return value


def _env_default(key: str) -> int:
    if key == MAX_CONCURRENT_RUNS:
        return get_settings().max_concurrent_runs
    if key == FIRST_RUN_LIMIT:
        return get_settings().first_run_limit
    raise UnknownSettingError(key)


def read_int(conn: sqlite3.Connection, key: str) -> int:
    """저장된 값. 아직 없으면 환경변수 값으로 채우고 그 값을 돌려준다."""
    if key not in KEYS:
        raise UnknownSettingError(key)

    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    if row is not None:
        return _stored_int(key, row["value"])

    seeded = _validate(key, _env_default(key))
    conn.execute(
        "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)", (key, str(seeded))
    )
    return seeded


def write_int(conn: sqlite3.Connection, key: str, value: int) -> int:
    """값을 바꾼다. 범위 밖이면 저장하지 않고 `SettingValueError` 다."""
    if key not in KEYS:
        raise UnknownSettingError(key)
    validated = _validate(key, value)
    conn.execute(
        """
        INSERT INTO app_settings (key, value) VALUES (?, ?)
        ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
        """,
        (key, str(validated)),
    )
    return validated


def read_all(conn: sqlite3.Connection) -> dict[str, int]:
    """모든 키의 현재 값. 없는 키는 읽는 김에 채워진다."""
    return {key: read_int(conn, key) for key in KEYS}


def _stored_int(key: str, raw: str) -> int:
    """저장된 문자열을 정수로 읽는다. 손으로 넣은 값이 깨져 있으면 그대로 알린다."""
    try:
        value = int(raw)
    except ValueError as exc:
        raise SettingValueError(f"{key} 에 저장된 값을 정수로 읽을 수 없다: {raw!r}") from exc
    return _validate(key, value)
