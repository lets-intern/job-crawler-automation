"""알림 설정. 값은 `app_settings` 표에 들어간다 — 새 표를 만들지 않는다.

`app/settings.py` 와 같은 표를 쓰지만 저장소를 따로 둔다. 그쪽은 정수 하나를 다루고
`/api/settings` 가 `dict[str, int]` 로 내보내는데, 여기 값은 켜기·끄기와 주소와 낱말이
섞여 있다. 그 API 의 응답 모양을 알림 때문에 바꾸면 이미 있는 화면이 같이 흔들린다.

환경변수 짝을 두지 않는다. 동시 실행 상한과 달리 배포가 정할 값이 아니라 운영자가 화면에서
정하는 값이고, 짝을 만들면 같은 설정이 두 곳에 생긴다 (`app/settings.py`).

읽기는 예외를 던지지 않는다. 이 값을 읽는 자리가 크롤링 실행의 끝이라, 손으로 넣은 깨진 값
하나가 수집을 멈추게 둘 수 없다. 읽지 못한 값은 기본값으로 떨어지고 로그에 남는다. 쓰기는
반대로 깐깐하다 — 저장되는 값은 전부 검증을 지난다.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from app.notify.ntfy import PRIORITIES, NtfyConfigError, NtfyTarget

logger = logging.getLogger(__name__)

ENABLED = "ntfy_enabled"
SERVER_URL = "ntfy_server_url"
TOPIC = "ntfy_topic"
PRIORITY = "ntfy_priority"
MIN_NEW_COUNT = "ntfy_min_new_count"
CLICK_BASE = "ntfy_click_base"

KEYS: tuple[str, ...] = (ENABLED, SERVER_URL, TOPIC, PRIORITY, MIN_NEW_COUNT, CLICK_BASE)

# 2026-08-25 에 200 을 주는 것을 확인한 주소다
# (`../.claude/tasks/done/ntfy-notify/tasks-ntfy-notify.md`).
# 기본값으로 넣어 두되 `enabled` 는 꺼진 채로 둔다 — 주소가 맞다는 것과 보내도 된다는 것은
# 다른 이야기라서, 켜는 것은 운영자가 화면에서 한다
DEFAULT_SERVER_URL = "https://ntfy.supabin.com"
DEFAULT_TOPIC = "job"
DEFAULT_PRIORITY = "default"

# 몇 건부터 알릴지의 기본값. 1이면 새 공고가 하나라도 들어오면 알린다
DEFAULT_MIN_NEW_COUNT = 1


class NotifySettingError(ValueError):
    """저장할 수 없는 값. 거절 사유를 화면이 그대로 옮긴다."""


@dataclass(frozen=True)
class NotifyConfig:
    """알림 설정 한 벌. 저장된 값이 없으면 이 기본값이 그대로 쓰인다."""

    enabled: bool = False
    server_url: str = DEFAULT_SERVER_URL
    topic: str = DEFAULT_TOPIC
    priority: str = DEFAULT_PRIORITY
    # 이 수 이상 새로 적재됐을 때만 보낸다
    min_new_count: int = DEFAULT_MIN_NEW_COUNT
    # 운영 화면의 바깥 주소. 알림을 눌렀을 때 열 곳을 여기서 만든다.
    # 비어 있으면 누를 곳 없는 알림이 나간다 — 알림 자체는 그대로 간다
    click_base: str = ""

    @property
    def target(self) -> NtfyTarget:
        return NtfyTarget(server_url=self.server_url, topic=self.topic, priority=self.priority)

    @property
    def click_url(self) -> str:
        """알림을 눌렀을 때 열 주소. 데이터 검수 화면이다 (`app/api/ui.py` 의 `NAV`)."""
        if not self.click_base.strip():
            return ""
        return f"{self.click_base.strip().rstrip('/')}/review"

    def validate(self) -> None:
        """저장하기 전에 본다. 하나라도 걸리면 아무것도 저장하지 않는다."""
        try:
            self.target.validate()
        except NtfyConfigError as exc:
            raise NotifySettingError(str(exc)) from exc
        if self.min_new_count < 1:
            raise NotifySettingError(f"알림 기준 건수는 1 이상이어야 한다: {self.min_new_count}")
        base = self.click_base.strip()
        if base and not base.startswith(("http://", "https://")):
            raise NotifySettingError(
                f"운영 화면 주소는 http:// 나 https:// 로 시작해야 한다: {self.click_base!r}"
            )


def read_config(conn: sqlite3.Connection) -> NotifyConfig:
    """저장된 설정. 값이 없거나 읽지 못하면 기본값이다. 읽는 김에 채워 넣지 않는다.

    `app/settings.py` 의 `read_int` 는 환경변수 값을 읽으면서 저장해 둔다. 나중에 환경변수를
    고쳐도 그때 정해진 값이 이기게 하려는 것이다. 여기에는 지킬 환경변수가 없으므로 읽기가
    쓰기를 하지 않는다.
    """
    stored = {
        str(row["key"]): str(row["value"])
        for row in conn.execute(
            f"SELECT key, value FROM app_settings WHERE key IN ({','.join('?' * len(KEYS))})",
            KEYS,
        )
    }
    default = NotifyConfig()
    return NotifyConfig(
        enabled=_as_bool(stored.get(ENABLED), default.enabled),
        server_url=stored.get(SERVER_URL, default.server_url),
        topic=stored.get(TOPIC, default.topic),
        priority=_as_priority(stored.get(PRIORITY), default.priority),
        min_new_count=_as_int(stored.get(MIN_NEW_COUNT), default.min_new_count),
        click_base=stored.get(CLICK_BASE, default.click_base),
    )


def write_config(conn: sqlite3.Connection, config: NotifyConfig) -> NotifyConfig:
    """설정 한 벌을 저장한다. 거절된 값은 하나도 저장되지 않는다."""
    config.validate()
    values = {
        ENABLED: "1" if config.enabled else "0",
        SERVER_URL: config.server_url.strip(),
        TOPIC: config.topic.strip(),
        PRIORITY: config.priority,
        MIN_NEW_COUNT: str(config.min_new_count),
        CLICK_BASE: config.click_base.strip(),
    }
    conn.executemany(
        """
        INSERT INTO app_settings (key, value) VALUES (?, ?)
        ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
        """,
        list(values.items()),
    )
    return read_config(conn)


def _as_bool(raw: str | None, fallback: bool) -> bool:
    if raw is None:
        return fallback
    if raw in ("0", "1"):
        return raw == "1"
    logger.warning("%s 에 저장된 값을 켜짐/꺼짐으로 읽을 수 없다: %r. 기본값을 쓴다", ENABLED, raw)
    return fallback


def _as_int(raw: str | None, fallback: int) -> int:
    if raw is None:
        return fallback
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "%s 에 저장된 값을 정수로 읽을 수 없다: %r. 기본값을 쓴다", MIN_NEW_COUNT, raw
        )
        return fallback
    if value < 1:
        logger.warning("%s 에 저장된 값이 1 미만이다: %r. 기본값을 쓴다", MIN_NEW_COUNT, raw)
        return fallback
    return value


def _as_priority(raw: str | None, fallback: str) -> str:
    if raw is None:
        return fallback
    if raw in PRIORITIES:
        return raw
    logger.warning(
        "%s 에 저장된 값이 ntfy 가 받는 우선순위가 아니다: %r. 기본값을 쓴다", PRIORITY, raw
    )
    return fallback
