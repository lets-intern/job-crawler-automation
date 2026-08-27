-- 손보정을 새 칸 열 개에도 걸 수 있게 한다.
--
-- 0011 이 `normalized_jobs` 를 열여섯 칸으로 늘렸지만 `job_field_overrides.field_name` 의
-- CHECK 는 옛 여섯 칸에 묶여 있다. 그래서 **새 칸 열 개는 검수 화면에서 고칠 수 없다** —
-- 자동으로 뽑은 값이 틀렸을 때 사람이 고칠 길이 없고, 그 시도는 저장을 누른 뒤에야 DB 의
-- CHECK 에 걸려 실패한다.
--
-- 0009·0010 이 쓴 방법(새 CHECK 를 단 컬럼 추가 -> 값 이동 -> 옛 컬럼 삭제)이 여기서는 통하지
-- 않는다. `field_name` 이 `UNIQUE (raw_job_id, field_name)` 의 자동 인덱스에 걸려 있고,
-- SQLite 는 인덱스가 걸린 컬럼을 DROP 하지 못한다.
--
-- 그래서 **표를 다시 만든다.** 새 CHECK 를 단 표를 만들고, 있는 행을 옮기고, 옛 표를 지우고,
-- 이름을 되돌린다. 2026-08-26 확인 결과 운영 DB 의 이 표는 **0행**이라 옮길 데이터가 없지만,
-- 행이 있어도 그대로 넘어가도록 INSERT ... SELECT 를 넣는다.
--
-- `id` 를 그대로 옮긴다. 이 표를 가리키는 외래키는 없지만, id 가 바뀌면 화면과 로그에 적힌
-- 보정 번호가 다른 보정을 가리키게 된다.
--
-- 받는 필드는 `app/normalize/rules.py` 의 `NORMALIZED_FIELDS` 열여섯 개 중 열여섯 개다.
-- `source_url` 은 공고의 신원이라 여전히 받지 않고, `normalized_at` 과 `delivered_at` 도
-- 그대로 받지 않는다 — 수동 수정이 전달 표시를 되돌리면 소비 측에 같은 데이터가 다시 간다
-- (`.claude/rules/data-safety.md`).
--
-- `app/normalize/engine.py` 의 `OVERRIDABLE_FIELDS` 를 같은 커밋에서 열여섯 개로 넓힌다.
-- 코드 쪽만 넓히면 DB 가 거절하고, DB 쪽만 넓히면 코드가 보정을 읽고도 버린다.
--
-- 되돌리기: `migrate down` 이 같은 방법으로 옛 여섯 칸 CHECK 를 단 표를 다시 만든다.
-- **새 칸 열 개에 걸린 보정 행은 그때 사라진다** — 옛 CHECK 가 그 값을 담지 못하므로 옮길
-- 자리가 없다. 사라지는 것은 사람이 고친 값이고, 다음 정규화에서 그 필드는 규칙이 만든 값으로
-- 돌아간다. `raw_jobs` 와 `normalized_jobs` 는 어느 방향으로도 건드리지 않는다. 역적용 전에
-- 새 칸의 보정이 필요하면 따로 뽑아 둔다:
--
--     SELECT * FROM job_field_overrides
--      WHERE field_name NOT IN
--            ('company', 'title', 'department', 'deadline', 'body', 'requirements');

-- migrate:up
CREATE TABLE job_field_overrides_new (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_job_id INTEGER NOT NULL REFERENCES raw_jobs(id),
    field_name TEXT NOT NULL CHECK (
                   field_name IN (
                       'company', 'title', 'department', 'deadline', 'body', 'requirements',
                       'start_date', 'job_category', 'employment_type', 'career_level',
                       'work_location', 'headcount', 'duties', 'preferred', 'hiring_process',
                       'etc_info'
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

-- migrate:down
CREATE TABLE job_field_overrides_old (
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

-- 새 칸에 걸린 보정은 옛 CHECK 에 담을 자리가 없어 여기서 떨어진다
INSERT INTO job_field_overrides_old (id, raw_job_id, field_name, value, created_at, updated_at)
SELECT id, raw_job_id, field_name, value, created_at, updated_at
  FROM job_field_overrides
 WHERE field_name IN ('company', 'title', 'department', 'deadline', 'body', 'requirements');

DROP TABLE job_field_overrides;

ALTER TABLE job_field_overrides_old RENAME TO job_field_overrides;
