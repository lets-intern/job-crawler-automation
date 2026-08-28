"""전달 설정. 값은 `app_settings` 표에 들어간다 — 새 표를 만들지 않는다.

`app/notify/settings.py` 와 같은 자리의 모듈이다. 다른 점은 이 값을 실제로 쓰는 코드가 아직
없다는 것뿐이다 — 이 Push 는 자리를 만드는 데까지고, 실제 전송은 다음 일이다
(`.claude/tasks/todo/prd-side-workflows.md` 3절).

읽기는 예외를 던지지 않는다. 손으로 넣은 깨진 값 하나가 화면을 죽이면 안 된다. 읽지 못한
값은 기본값으로 떨어지고 로그에 남는다. 쓰기는 반대로 깐깐하다 — 저장되는 값은 전부 검증을
지난다.

**자격증명을 어떻게 줄지는 아직 정하지 않았다** (`.claude/docs/api-contract.md`). 여기 있는
`auth_header` 는 그 값을 넣어 둘 자리일 뿐이고, 계약이 정해지면 이 파일과 그 문서를 같은
커밋에서 고친다.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

logger = logging.getLogger(__name__)

URL = "deliver_url"
METHOD = "deliver_method"
AUTH_HEADER = "deliver_auth_header"
BATCH_SIZE = "deliver_batch_size"

KEYS: tuple[str, ...] = (URL, METHOD, AUTH_HEADER, BATCH_SIZE)

# 받는 메서드 둘뿐이다. 조회가 아니라 보내는 동작이라 GET 은 없다
METHODS: tuple[str, ...] = ("POST", "PUT")
DEFAULT_METHOD = "POST"

DEFAULT_BATCH_SIZE = 100


class DeliverSettingError(ValueError):
    """저장할 수 없는 값. 거절 사유를 화면이 그대로 옮긴다."""


@dataclass(frozen=True)
class DeliverConfig:
    """전달 설정 한 벌. 저장된 값이 없으면 이 기본값이 그대로 쓰인다.

    `configured` 가 참이어야 화면이 "보낼 준비가 됐다" 로 읽는다. 지금은 이 값을 실제로
    쓰는 전송 경로가 없으므로, 참이어도 아무 일도 일어나지 않는다.
    """

    url: str = ""
    method: str = DEFAULT_METHOD
    # "이름: 값" 한 줄. 비워 두면 인증 없이 부르는 것이다
    auth_header: str = ""
    batch_size: int = DEFAULT_BATCH_SIZE

    @property
    def configured(self) -> bool:
        return bool(self.url.strip())

    def validate(self) -> None:
        """저장하기 전에 본다. 하나라도 걸리면 아무것도 저장하지 않는다."""
        cleaned = self.url.strip()
        if cleaned and not cleaned.startswith(("http://", "https://")):
            raise DeliverSettingError(
                f"전달 주소는 http:// 나 https:// 로 시작해야 한다: {self.url!r}"
            )
        if self.method not in METHODS:
            raise DeliverSettingError(
                f"전달 방식이 아니다: {self.method!r}. {' 또는 '.join(METHODS)} 다"
            )
        if self.batch_size < 1:
            raise DeliverSettingError(f"1회 전달 건수는 1 이상이어야 한다: {self.batch_size}")


def read_config(conn: sqlite3.Connection) -> DeliverConfig:
    """저장된 설정. 값이 없거나 읽지 못하면 기본값이다. 읽는 김에 채워 넣지 않는다."""
    stored = {
        str(row["key"]): str(row["value"])
        for row in conn.execute(
            f"SELECT key, value FROM app_settings WHERE key IN ({','.join('?' * len(KEYS))})",
            KEYS,
        )
    }
    default = DeliverConfig()
    return DeliverConfig(
        url=stored.get(URL, default.url),
        method=_as_method(stored.get(METHOD), default.method),
        auth_header=stored.get(AUTH_HEADER, default.auth_header),
        batch_size=_as_int(stored.get(BATCH_SIZE), default.batch_size),
    )


def write_config(conn: sqlite3.Connection, config: DeliverConfig) -> DeliverConfig:
    """설정 한 벌을 저장한다. 거절된 값은 하나도 저장되지 않는다."""
    config.validate()
    values = {
        URL: config.url.strip(),
        METHOD: config.method,
        AUTH_HEADER: config.auth_header.strip(),
        BATCH_SIZE: str(config.batch_size),
    }
    conn.executemany(
        """
        INSERT INTO app_settings (key, value) VALUES (?, ?)
        ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
        """,
        list(values.items()),
    )
    return read_config(conn)


def _as_method(raw: str | None, fallback: str) -> str:
    if raw is None:
        return fallback
    if raw in METHODS:
        return raw
    logger.warning("%s 에 저장된 값이 전달 방식이 아니다: %r. 기본값을 쓴다", METHOD, raw)
    return fallback


def _as_int(raw: str | None, fallback: int) -> int:
    if raw is None:
        return fallback
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s 에 저장된 값을 정수로 읽을 수 없다: %r. 기본값을 쓴다", BATCH_SIZE, raw)
        return fallback
    if value < 1:
        logger.warning("%s 에 저장된 값이 1 미만이다: %r. 기본값을 쓴다", BATCH_SIZE, raw)
        return fallback
    return value
