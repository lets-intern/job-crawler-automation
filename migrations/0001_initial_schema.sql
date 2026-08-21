-- 초기 스키마. 컬럼은 .claude/docs/data-model.md 를 따른다.

-- migrate:up
CREATE TABLE crawlers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    list_url       TEXT NOT NULL,
    detail_url     TEXT,
    selectors_json TEXT,
    render_mode    TEXT NOT NULL DEFAULT 'static'
                   CHECK (render_mode IN ('static', 'playwright')),
    status         TEXT NOT NULL DEFAULT 'draft'
                   CHECK (status IN ('draft', 'tested', 'promoted')),
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE workflows (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    crawler_id          INTEGER NOT NULL REFERENCES crawlers(id),
    name                TEXT NOT NULL,
    interval_minutes    INTEGER NOT NULL DEFAULT 360,
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'paused')),
    success_count       INTEGER NOT NULL DEFAULT 0,
    fail_count          INTEGER NOT NULL DEFAULT 0,
    last_run_at         TEXT,
    -- NULL 이면 자동 중지 없음
    auto_stop_threshold INTEGER
);

CREATE TABLE crawl_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id   INTEGER NOT NULL REFERENCES workflows(id),
    started_at    TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at   TEXT,
    -- 실행 중에는 NULL. 종료 시 세 값 중 하나로 확정된다
    status        TEXT CHECK (status IS NULL OR status IN ('success', 'failed', 'timeout')),
    success_count INTEGER NOT NULL DEFAULT 0,
    new_count     INTEGER NOT NULL DEFAULT 0,
    fail_count    INTEGER NOT NULL DEFAULT 0,
    error_class   TEXT CHECK (
                      error_class IS NULL
                      OR error_class IN ('transport', 'selector_miss', 'parse')
                  ),
    error_message TEXT
);

-- append-only. 정규화가 이 테이블을 고치지 않는다
CREATE TABLE raw_jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id   INTEGER NOT NULL REFERENCES workflows(id),
    source_url    TEXT NOT NULL,
    raw_data_json TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    crawled_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_raw_jobs_content_hash ON raw_jobs (content_hash);

CREATE TABLE normalized_jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_job_id    INTEGER NOT NULL REFERENCES raw_jobs(id),
    company       TEXT,
    title         TEXT,
    department    TEXT,
    deadline      TEXT,
    body          TEXT,
    requirements  TEXT,
    source_url    TEXT NOT NULL,
    normalized_at TEXT NOT NULL DEFAULT (datetime('now')),
    -- 제공 API 경로만 쓴다
    delivered_at  TEXT
);

CREATE INDEX idx_normalized_jobs_normalized_at ON normalized_jobs (normalized_at);

CREATE TABLE normalization_rules (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    field_name       TEXT NOT NULL,
    rule_type        TEXT NOT NULL
                     CHECK (rule_type IN ('mapping', 'regex', 'trim', 'date_parse')),
    rule_config_json TEXT NOT NULL,
    priority         INTEGER NOT NULL DEFAULT 0,
    enabled          INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1))
);

-- migrate:down
DROP INDEX IF EXISTS idx_normalized_jobs_normalized_at;
DROP INDEX IF EXISTS idx_raw_jobs_content_hash;
DROP TABLE normalization_rules;
DROP TABLE normalized_jobs;
DROP TABLE raw_jobs;
DROP TABLE crawl_runs;
DROP TABLE workflows;
DROP TABLE crawlers;
