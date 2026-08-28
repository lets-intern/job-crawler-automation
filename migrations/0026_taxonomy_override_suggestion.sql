-- `job_major`/`job_minor` 를 사람이 고치거나(job_field_overrides) 모델이 제안할
-- (job_field_suggestions) 수 있게 CHECK 목록을 넓힌다.
--
-- `job_field_suggestions` 는 스스로 "`app/normalize/rules.py` 의 `NORMALIZED_FIELDS`
-- 전부를 받는다" 고 정했다(`migrations/0023_job_field_suggestions.sql`). 0025 가
-- `NORMALIZED_FIELDS` 에 이 두 칸을 더했으니 CHECK 도 같이 넓혀야 그 약속이 유지된다.
-- `job_field_overrides` 도 다른 판정 칸(`employment_type`·`career_level`)과 같은 이유로
-- 사람이 고칠 수 있어야 한다 — 모델이 잘못 고른 대분류·소분류를 운영자가 검수 화면에서
-- 바로잡는 길이 없으면 재분류(모델 호출)를 다시 돌리는 것 말고는 고칠 방법이 없다.
--
-- SQLite 는 CHECK 를 `ALTER TABLE` 로 못 바꾼다. 0012·0017 이 쓴 방법을 그대로 쓴다 —
-- 새 CHECK 를 단 표를 만들고, 있는 행을 그대로 옮기고, 옛 표를 지우고, 이름을 되돌린다.
--
-- 적용 직후 이 두 칸에 걸린 보정·제안 행은 없다(0025 가 방금 칸을 만들어 값이 전부
-- NULL 이라 걸 만한 값이 없었다). 이 마이그레이션은 옮길 행이 있어도 그대로 옮긴다.
--
-- 되돌리기: CHECK 를 0023·0017 의 목록으로 되돌린다. `job_major`/`job_minor` 에 걸린
-- 보정·제안 행은 옛 CHECK 에 담을 자리가 없어 역적용 시 떨어진다 — 0017 의 역적용이
-- `job_role` 보정을 거르는 것과 같은 이유다.

-- migrate:up
CREATE TABLE job_field_overrides_new (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_job_id INTEGER NOT NULL REFERENCES raw_jobs(id),
    field_name TEXT NOT NULL CHECK (
                   field_name IN (
                       'company', 'title', 'department', 'deadline', 'body', 'requirements',
                       'start_date', 'job_category', 'employment_type', 'career_level',
                       'work_location', 'headcount', 'duties', 'preferred', 'hiring_process',
                       'etc_info', 'job_role', 'job_major', 'job_minor'
                   )
               ),
    value      TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (raw_job_id, field_name)
);

INSERT INTO job_field_overrides_new (id, raw_job_id, field_name, value, created_at, updated_at)
SELECT id, raw_job_id, field_name, value, created_at, updated_at FROM job_field_overrides;

DROP TABLE job_field_overrides;

ALTER TABLE job_field_overrides_new RENAME TO job_field_overrides;

CREATE TABLE job_field_suggestions_new (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_job_id INTEGER NOT NULL REFERENCES raw_jobs(id),
    field_name TEXT NOT NULL CHECK (
                   field_name IN (
                       'company', 'title', 'job_role', 'deadline', 'body', 'requirements',
                       'start_date', 'employment_type', 'career_level', 'work_location',
                       'duties', 'preferred', 'hiring_process', 'etc_info', 'job_major',
                       'job_minor'
                   )
               ),
    value      TEXT NOT NULL,
    reason     TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (raw_job_id, field_name)
);

INSERT INTO job_field_suggestions_new (id, raw_job_id, field_name, value, reason, created_at)
SELECT id, raw_job_id, field_name, value, reason, created_at FROM job_field_suggestions;

DROP TABLE job_field_suggestions;

ALTER TABLE job_field_suggestions_new RENAME TO job_field_suggestions;

-- migrate:down
CREATE TABLE job_field_overrides_old (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_job_id INTEGER NOT NULL REFERENCES raw_jobs(id),
    field_name TEXT NOT NULL CHECK (
                   field_name IN (
                       'company', 'title', 'department', 'deadline', 'body', 'requirements',
                       'start_date', 'job_category', 'employment_type', 'career_level',
                       'work_location', 'headcount', 'duties', 'preferred', 'hiring_process',
                       'etc_info', 'job_role'
                   )
               ),
    value      TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (raw_job_id, field_name)
);

-- 직무 분류에 걸린 보정은 옛 CHECK 에 담을 자리가 없어 여기서 떨어진다
INSERT INTO job_field_overrides_old (id, raw_job_id, field_name, value, created_at, updated_at)
SELECT id, raw_job_id, field_name, value, created_at, updated_at
  FROM job_field_overrides
 WHERE field_name NOT IN ('job_major', 'job_minor');

DROP TABLE job_field_overrides;

ALTER TABLE job_field_overrides_old RENAME TO job_field_overrides;

CREATE TABLE job_field_suggestions_old (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_job_id INTEGER NOT NULL REFERENCES raw_jobs(id),
    field_name TEXT NOT NULL CHECK (
                   field_name IN (
                       'company', 'title', 'job_role', 'deadline', 'body', 'requirements',
                       'start_date', 'employment_type', 'career_level', 'work_location',
                       'duties', 'preferred', 'hiring_process', 'etc_info'
                   )
               ),
    value      TEXT NOT NULL,
    reason     TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (raw_job_id, field_name)
);

INSERT INTO job_field_suggestions_old (id, raw_job_id, field_name, value, reason, created_at)
SELECT id, raw_job_id, field_name, value, reason, created_at
  FROM job_field_suggestions
 WHERE field_name NOT IN ('job_major', 'job_minor');

DROP TABLE job_field_suggestions;

ALTER TABLE job_field_suggestions_old RENAME TO job_field_suggestions;
