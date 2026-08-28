-- 운영자가 등록한 직무 분류 체계. LLM이 여기서 고른다.
--
-- `.claude/tasks/todo/prd-job-taxonomy.md`. 대분류와 소분류를 한 표에 함께 둔다 —
-- `parent_id`가 NULL이면 대분류, 아니면 그 값이 가리키는 대분류의 소분류다. 표를 둘로
-- 가르면 같은 CRUD를 두 벌 쓰게 되고, 나중에 3단계로 늘릴 때 표가 또 하나 는다.
--
-- ## 컬럼
--
-- | 컬럼 | 뜻 |
-- |---|---|
-- | `name` | 화면과 모델에 나가는 이름 |
-- | `sort_order` | 화면과 프롬프트에서의 순서 |
-- | `enabled` | 끄면 새 분류에서 빠진다. 이미 그 값으로 분류된 건은 그대로다 |
-- | `note` | 운영자 메모. 모델에 보내지 않는다 |
--
-- **지우는 기능을 만들지 않는다.** 지우면 그 값으로 분류된 공고가 목록에 없는 값을 갖고,
-- 소비 측이 받는 값이 우리 목록 밖이 된다. 켜기·끄기만 둔다.
--
-- ## `(parent_id, name)` UNIQUE와 대분류 이름 중복
--
-- SQLite는 UNIQUE 제약에서 NULL을 서로 다른 값으로 본다. `parent_id`가 둘 다 NULL인
-- 대분류 두 개가 같은 이름이어도 이 제약은 막지 못한다 — 대분류 이름 중복은
-- `app/taxonomy.py`(Push 1.3)가 애플리케이션 레벨에서 막는다. 소분류는 부모가 실제
-- 정수 id라서 이 제약이 그대로 걸린다.
--
-- 3단계(소분류 아래에 또 소분류)를 이 스키마는 막지 않는다 — `app/taxonomy.py`의 값 검증이
-- "부모는 반드시 `parent_id`가 NULL인 행이어야 한다"로 막는다.
--
-- 되돌리기: 표를 지운다. `normalized_jobs.job_major`/`job_minor`(Push 2)는 이 표의 이름을
-- 문자열로 복사해 갖고 있을 뿐 외래키로 참조하지 않으므로, 이 표를 지워도 그 값은 그대로다.

-- migrate:up
CREATE TABLE job_taxonomy (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id  INTEGER REFERENCES job_taxonomy(id),
    name       TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    enabled    INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (parent_id, name)
);

CREATE INDEX idx_job_taxonomy_parent ON job_taxonomy(parent_id);

-- migrate:down
DROP TABLE job_taxonomy;
