-- 사람이 검수하며 고친 값의 저장소.
--
-- 검수한 값을 `normalized_jobs` 에 그대로 쓰면 다음 재정규화가 규칙으로 그 컬럼을 덮어써서
-- 검수 결과가 통째로 사라진다. 사람의 보정은 규칙에서 나온 파생값이 아니라 또 하나의 출처이고,
-- 출처는 파생값과 같은 자리에 두지 않는다 (`../.claude/rules/data-safety.md`).
--
-- 적용 순서는 규칙 다음에 보정이다. 규칙을 개선하면 보정하지 않은 필드는 같이 좋아지고,
-- 보정한 필드는 사람이 정한 값을 유지한다. 보정을 지우면 다음 정규화에서 규칙이 만든 값으로
-- 돌아간다.
--
-- `normalized_jobs.id` 가 아니라 `raw_jobs.id` 에 매단다. `normalized_jobs` 행은 재정규화로
-- 다시 만들어질 수 있고, 그때 보정이 따라붙지 못하면 같은 값을 사람이 다시 고쳐야 한다.
-- `raw_jobs` 는 append-only 라 id 가 바뀌지 않는다.
--
-- 고칠 수 있는 필드는 규칙이 만드는 여섯 개뿐이고 CHECK 로 못 박는다. `source_url` 은 공고의
-- 신원이라 고치지 않는다. `normalized_at` 과 `delivered_at` 은 아예 받지 않는다 — 수동 수정이
-- 전달 표시를 되돌리면 소비 측에 같은 데이터가 다시 간다.
--
-- `value` 는 NOT NULL 이고 빈 문자열을 허용한다. 빈 문자열은 "이 필드는 비어 있는 것이 맞다"
-- 는 사람의 판단이고, 보정을 없애는 것은 행을 지우는 것이다. 둘을 NULL 하나로 겹쳐 두면
-- 구분할 수 없다.
--
-- 되돌리기: 테이블을 지운다. 사람이 고친 값은 사라지고, 다음 정규화부터 모든 필드가 규칙이
-- 만든 값으로 돌아간다. `raw_jobs` 와 `normalized_jobs` 는 그대로다.

-- migrate:up
CREATE TABLE job_field_overrides (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_job_id INTEGER NOT NULL REFERENCES raw_jobs(id),
    field_name TEXT NOT NULL CHECK (
                   field_name IN (
                       'company', 'title', 'department', 'deadline', 'body', 'requirements'
                   )
               ),
    value      TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (raw_job_id, field_name)
);

-- migrate:down
DROP TABLE job_field_overrides;
