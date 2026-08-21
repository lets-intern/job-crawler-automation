"""규칙 적용. `raw_jobs` 를 읽고 `normalized_jobs` 에만 쓴다.

이 방향은 뒤집히지 않는다. 정규화가 raw 를 고치면 잘못된 규칙 하나가 수집 데이터를 영구히
망가뜨리고, 크롤링은 다시 돌릴 수 없다 (`.claude/rules/data-safety.md`). 그래서 이 파일에
`raw_jobs` 를 대상으로 하는 UPDATE 나 DELETE 는 없다 — SELECT 하나뿐이다.

## 한 필드에 규칙이 여럿일 때

`priority` 오름차순으로 적용하고, 앞 규칙의 결과가 뒤 규칙의 입력이 된다. `enabled=false` 인
규칙은 건너뛴다. 같은 `priority` 면 `id` 순이다 — 순서가 정해지지 않으면 같은 입력에 같은
결과가 나온다는 보장이 없다.

정렬과 `enabled` 판정은 규칙을 어디서 받았든 이 파일에서 다시 한다. DB 의 ORDER BY 에만
맡기면 규칙 목록을 손으로 만들어 넣는 경로에서 조용히 순서가 뒤집힌다.

## 회사명은 두 출처에서 하나를 고른다

`raw_data_json.company` 가 비어 있지 않으면 그 값을 쓰고 `company_source='parsed'` 다.
비어 있으면 그 크롤러의 `crawlers.default_company` 를 쓰고 `company_source='operator'` 다.
둘 다 없으면 둘 다 NULL 이다 — 빈 문자열로 채우지 않는다.

파싱값이 이기는 이유는 공고 단위가 사이트 단위보다 구체적이기 때문이다. 삼성 채용 사이트
하나에 삼성SDS 와 삼성전기 공고가 섞여 들어오고, 그 둘을 구분하는 것은 파싱값뿐이다.

고른 값에도 다른 필드와 똑같이 규칙이 적용된다. "삼성전기(주)" 를 "삼성전기" 로 맞추는 것은
`mapping` 규칙의 일이지 이 해결 단계의 일이 아니다.

## 빈 값에는 규칙을 적용하지 않는다

셀렉터가 아무것도 못 뽑은 필드는 정규화할 것이 없다. 규칙을 태우지 않고 NULL 로 둔다.
빈 문자열에 `date_parse` 를 걸면 값이 없다는 사실이 "규칙이 실패했다" 로 둔갑한다.

## 실패는 예외다

규칙이 값을 처리하지 못하면 `NormalizeError` 를 던지고, 그 건은 `normalized_jobs` 에
들어가지 않는다. 절반만 적용된 행은 겉보기에 멀쩡해서 아무도 틀린 줄 모른다. raw 는 남아
있으므로 규칙을 고쳐 재정규화하면 복구된다.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime

from app.normalize.rules import (
    NORMALIZED_FIELDS,
    DateParseConfig,
    MappingConfig,
    RegexConfig,
    Rule,
    RuleConfigError,
    TrimConfig,
    build_rule,
)

_WHITESPACE = re.compile(r"\s+")

# `normalized_jobs.company_source` 의 CHECK 제약과 같은 값이어야 한다.
PARSED = "parsed"
OPERATOR = "operator"

# 규칙이 만드는 필드가 아니라 해결 단계가 정하는 값이다. `NORMALIZED_FIELDS` 에 넣지 않는다.
COMPANY_SOURCE = "company_source"


class NormalizeError(RuntimeError):
    """규칙 하나가 값을 처리하지 못했다. 그 건은 정규화되지 않는다."""

    def __init__(self, field_name: str, rule_type: str, message: str, rule_id: int | None) -> None:
        where = (
            f"{field_name}/{rule_type}"
            if rule_id is None
            else f"{field_name}/{rule_type}#{rule_id}"
        )
        super().__init__(f"정규화 실패({where}): {message}")
        self.field_name = field_name
        self.rule_type = rule_type
        self.rule_id = rule_id


class RawJobMissingError(LookupError):
    """정규화하려는 `raw_jobs` 행이 없다."""


def load_rules(conn: sqlite3.Connection) -> list[Rule]:
    """저장된 규칙을 읽는다. 설정이 깨진 행은 그 필드의 정규화를 실패시킨다.

    설정을 여기서 고치지 않는다. 저장 단계가 이미 검증했으므로, 읽는 쪽에서 깨진 설정을 만났다면
    누군가 DB 를 직접 고쳤다는 뜻이고 그것은 조용히 넘어갈 일이 아니다.
    """
    rows = conn.execute(
        """
        SELECT id, field_name, rule_type, rule_config_json, priority, enabled
          FROM normalization_rules
         ORDER BY field_name, priority, id
        """
    ).fetchall()
    return [_rule_from_row(row) for row in rows]


def resolve_company(
    raw: Mapping[str, object], default_company: str | None
) -> tuple[str, str | None]:
    """쓸 회사명과 그 출처. 파싱값이 이기고, 둘 다 없으면 ("", None) 이다.

    규칙을 태우기 전의 값을 그대로 돌려준다. 앞뒤 공백을 여기서 깎으면 `trim` 규칙이 하는 일을
    두 곳에서 하게 된다. 비었는지 판정할 때만 공백을 무시한다.
    """
    parsed = raw.get("company")
    if isinstance(parsed, str) and parsed.strip():
        return parsed, PARSED
    if default_company and default_company.strip():
        return default_company, OPERATOR
    return "", None


def normalize_fields(
    raw: Mapping[str, object],
    rules: Sequence[Rule],
    default_company: str | None = None,
) -> dict[str, str | None]:
    """원문 필드에서 `normalized_jobs` 의 값들을 만든다. 값이 없는 필드는 None 이다.

    `company` 만 원문 그대로가 아니라 해결된 값에서 출발하고, 그 출처가 `company_source` 로
    함께 나온다. 규칙이 값을 지워 버리면 출처도 NULL 이다 — 남은 값이 없는데 어디서 왔는지만
    적혀 있으면 그 행은 읽는 쪽을 헷갈리게 한다.
    """
    ordered = _by_field(rules)
    resolved, source = resolve_company(raw, default_company)
    result: dict[str, str | None] = {}
    for field_name in NORMALIZED_FIELDS:
        raw_value = resolved if field_name == "company" else raw.get(field_name)
        value = raw_value if isinstance(raw_value, str) else ""
        if not value:
            result[field_name] = None
            continue
        for rule in ordered.get(field_name, ()):
            value = _apply(value, rule)
        result[field_name] = value or None
    result[COMPANY_SOURCE] = source if result["company"] else None
    return result


def read_default_company(conn: sqlite3.Connection, raw_job_id: int) -> str | None:
    """그 건을 수집한 크롤러에 운영자가 적어 둔 회사명. 없으면 None 이다. 읽기 전용이다."""
    row = conn.execute(
        """
        SELECT c.default_company AS default_company
          FROM raw_jobs r
          JOIN workflows w ON w.id = r.workflow_id
          JOIN crawlers c ON c.id = w.crawler_id
         WHERE r.id = ?
        """,
        (raw_job_id,),
    ).fetchone()
    if row is None:
        return None
    value = row["default_company"]
    return str(value) if value is not None else None


def read_raw(conn: sqlite3.Connection, raw_job_id: int) -> tuple[str, dict[str, object]]:
    """`raw_jobs` 한 행의 `source_url` 과 파싱된 원문 필드. 읽기 전용이다."""
    row = conn.execute(
        "SELECT source_url, raw_data_json FROM raw_jobs WHERE id = ?", (raw_job_id,)
    ).fetchone()
    if row is None:
        raise RawJobMissingError(f"raw_jobs {raw_job_id} 가 없다")
    try:
        data = json.loads(row["raw_data_json"])
    except json.JSONDecodeError as exc:
        raise NormalizeError(
            "(전체)", "json", f"raw_data_json 을 읽을 수 없다: {exc}", None
        ) from exc
    if not isinstance(data, dict):
        raise NormalizeError(
            "(전체)", "json", f"raw_data_json 이 객체가 아니다: {type(data).__name__}", None
        )
    return str(row["source_url"]), data


def insert_normalized(conn: sqlite3.Connection, raw_job_id: int, rules: Sequence[Rule]) -> int:
    """`raw_jobs` 한 행을 정규화해 `normalized_jobs` 에 넣는다. 새 행의 id 를 돌려준다.

    `delivered_at` 은 쓰지 않는다. 제공 API 경로만 쓴다 (`.claude/rules/data-safety.md`).
    """
    source_url, data = read_raw(conn, raw_job_id)
    fields = normalize_fields(data, rules, read_default_company(conn, raw_job_id))
    cursor = conn.execute(
        """
        INSERT INTO normalized_jobs
               (raw_job_id, company, company_source, title, department, deadline, body,
                requirements, source_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            raw_job_id,
            fields["company"],
            fields[COMPANY_SOURCE],
            fields["title"],
            fields["department"],
            fields["deadline"],
            fields["body"],
            fields["requirements"],
            source_url,
        ),
    )
    return int(cursor.lastrowid or 0)


def _by_field(rules: Sequence[Rule]) -> dict[str, list[Rule]]:
    """필드별 적용 순서. 꺼진 규칙은 여기서 빠진다."""
    grouped: dict[str, list[Rule]] = {}
    for rule in rules:
        if not rule.enabled:
            continue
        grouped.setdefault(rule.field_name, []).append(rule)
    for items in grouped.values():
        items.sort(key=lambda rule: (rule.priority, rule.id if rule.id is not None else 0))
    return grouped


def _apply(value: str, rule: Rule) -> str:
    config = rule.config
    if isinstance(config, MappingConfig):
        if value in config.map:
            return config.map[value]
        return value if config.default is None else config.default

    if isinstance(config, RegexConfig):
        try:
            return re.sub(config.pattern, config.replacement, value)
        except re.error as exc:
            raise NormalizeError(rule.field_name, rule.rule_type, str(exc), rule.id) from exc

    if isinstance(config, TrimConfig):
        trimmed = _WHITESPACE.sub(" ", value) if config.collapse_whitespace else value
        return trimmed.strip(config.strip_chars) if config.strip_chars else trimmed.strip()

    return _parse_date(value, rule, config)


def _parse_date(value: str, rule: Rule, config: DateParseConfig) -> str:
    """`formats` 를 순서대로 시도한다. 하나도 맞지 않으면 실패다.

    맞지 않는 값을 원문 그대로 통과시키지 않는다. 그러면 `deadline` 컬럼에 날짜와 "상시채용"
    이 섞여 들어가고, 소비 측은 그것을 날짜로 읽는다. 날짜가 아닌 표기가 섞이는 사이트라면
    앞 순번에 `mapping` 규칙을 두어 먼저 걸러야 한다.
    """
    text = value.strip()
    for fmt in config.formats:
        try:
            return datetime.strptime(text, fmt).strftime(config.output_format)
        except ValueError:
            continue
    raise NormalizeError(
        rule.field_name,
        rule.rule_type,
        f"어느 형식으로도 날짜로 읽지 못했다: {value!r} (시도: {', '.join(config.formats)})",
        rule.id,
    )


def _rule_from_row(row: sqlite3.Row) -> Rule:
    try:
        return build_rule(
            row["field_name"],
            row["rule_type"],
            row["rule_config_json"],
            priority=int(row["priority"]),
            enabled=bool(row["enabled"]),
            rule_id=int(row["id"]),
        )
    except RuleConfigError as exc:
        raise NormalizeError(
            row["field_name"], row["rule_type"], f"저장된 설정이 잘못됐다: {exc}", int(row["id"])
        ) from exc
