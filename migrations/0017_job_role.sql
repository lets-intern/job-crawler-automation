-- 직무 칸을 더한다.
--
-- 0016 이 지운 부서·직군·모집인원 자리에 들어가는 칸이다
-- (`../.claude/tasks/todo/prd-fields-and-logo.md`). **뽑는 칸이지 판정 칸이 아니다** — 직군은
-- 닫힌 목록 열다섯 개였고, 직무는 제목에 적힌 글자를 그대로 옮기는 자유 텍스트다. 목록을
-- 만들지 않는다. 소비 측이 이 칸으로 거를 수 없다는 것은 PRD 가 아는 값이다.
--
-- 값이 제목에서 온다. 2026-08-28 에 열한 사이트 픽스처로 쟀더니 제목이 직무를 말하는 곳이
-- 아홉이고 그중 본문이 같은 글자를 되풀이하는 곳은 셋뿐이었다
-- (`tests/test_job_role_source.py`).
--
-- 칸이 세 자리에 는다.
--
-- | 자리 | 왜 |
-- |---|---|
-- | `normalized_jobs.job_role` | 소비 측이 읽는 칸 |
-- | `job_classifications.job_role` | 분류가 낸 값이 먼저 앉는 자리 |
-- | `job_field_overrides.field_name` 의 CHECK | 사람이 고칠 수 있어야 한다 |
--
-- 세 번째가 표를 다시 만든다. `field_name` 이 `UNIQUE (raw_job_id, field_name)` 의 자동
-- 인덱스에 걸려 있어 SQLite 가 컬럼을 DROP 하지 못하고, 그래서 0012 가 쓴 방법을 그대로 쓴다
-- — 새 CHECK 를 단 표를 만들고, 있는 행을 id 까지 옮기고, 옛 표를 지우고, 이름을 되돌린다
-- (`migrations/0012_override_new_columns.sql`).
--
-- CHECK 의 목록은 0012 의 열여섯에 `job_role` 을 더한 열일곱이다. **0016 이 지운 셋도 그대로
-- 둔다.** 그 셋의 보정 행은 되돌릴 때 필요해서 남겨 둔 것이고, 좁히면 여기서 떨어진다
-- (`migrations/0016_drop_department_category_headcount.sql`).
--
-- `app/normalize/rules.py` 의 `NORMALIZED_FIELDS` 는 **다음 커밋에서** 넓힌다. DB 가 코드보다
-- 넓은 것은 지금도 그렇고(0016 이후) 아무것도 깨뜨리지 않는다 — 반대로 코드만 넓히면 DB 가
-- 거절하고 그 실패는 운영자가 저장을 누른 뒤에야 드러난다. 순서가 그래서 이쪽이다.
--
-- 적용 직후 `job_role` 은 기존 행 전부에서 NULL 이다. 값은 분류를 다시 돌려야 들어온다 —
-- 이 파일에 `normalized_jobs` 나 `job_classifications` 를 대상으로 하는 UPDATE 가 없다.
--
-- 되돌리기: `migrate down` 이 컬럼 둘을 지우고 CHECK 를 0012 의 열여섯으로 되돌린다.
-- **사라지는 것은 직무 값과 직무에 걸린 보정 행뿐이다.** `raw_jobs` 는 어느 방향으로도
-- 건드리지 않으므로, 되돌린 뒤 값이 다시 필요하면 재크롤링 없이 다시 분류하면 된다 —
-- 공고당 모델 호출 하나다 (`../.claude/rules/data-safety.md`). 역적용 전에 사람이 고친 직무가
-- 필요하면 뽑아 둔다:
--
--     SELECT * FROM job_field_overrides WHERE field_name = 'job_role';

-- migrate:up
ALTER TABLE normalized_jobs ADD COLUMN job_role TEXT;

ALTER TABLE job_classifications ADD COLUMN job_role TEXT;

CREATE TABLE job_field_overrides_new (
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

-- 직무에 걸린 보정은 옛 CHECK 에 담을 자리가 없어 여기서 떨어진다
INSERT INTO job_field_overrides_old (id, raw_job_id, field_name, value, created_at, updated_at)
SELECT id, raw_job_id, field_name, value, created_at, updated_at
  FROM job_field_overrides
 WHERE field_name <> 'job_role';

DROP TABLE job_field_overrides;

ALTER TABLE job_field_overrides_old RENAME TO job_field_overrides;

ALTER TABLE job_classifications DROP COLUMN job_role;

ALTER TABLE normalized_jobs DROP COLUMN job_role;
