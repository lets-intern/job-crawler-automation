-- 테스트 실행도 crawl_runs 에 행을 남긴다.
--
-- 승격 전 크롤러의 1회 실행에는 워크플로우가 없다. 0001 의 crawl_runs.workflow_id 는 NOT NULL
-- 이라 그 실행은 행 자체를 만들 수 없었고, 기록이 없는 실행은 아무도 디버깅하지 못한다.
--
-- workflow_id 를 NULL 허용으로 바꾸고 crawler_id 를 더한다. 둘 다 NULL 인 행은 어디에도
-- 속하지 않으므로 CHECK 로 막는다. SQLite 는 컬럼의 NOT NULL 을 떼지 못해 테이블을 다시 만든다.
--
-- 되돌리기: workflow_id 가 NULL 인 행(테스트 실행 기록)은 0001 스키마에 들어가지 못한다.
-- down 은 그 행들을 버리고 워크플로우 실행 기록만 옮긴다.

-- migrate:up
ALTER TABLE crawl_runs RENAME TO crawl_runs_0001;

CREATE TABLE crawl_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 워크플로우 실행이면 workflow_id, 승격 전 테스트 실행이면 crawler_id 가 채워진다
    workflow_id   INTEGER REFERENCES workflows(id),
    crawler_id    INTEGER REFERENCES crawlers(id),
    started_at    TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at   TEXT,
    status        TEXT CHECK (status IS NULL OR status IN ('success', 'failed', 'timeout')),
    success_count INTEGER NOT NULL DEFAULT 0,
    new_count     INTEGER NOT NULL DEFAULT 0,
    fail_count    INTEGER NOT NULL DEFAULT 0,
    error_class   TEXT CHECK (
                      error_class IS NULL
                      OR error_class IN ('transport', 'selector_miss', 'parse')
                  ),
    error_message TEXT,
    CHECK (workflow_id IS NOT NULL OR crawler_id IS NOT NULL)
);

INSERT INTO crawl_runs (id, workflow_id, started_at, finished_at, status,
                        success_count, new_count, fail_count, error_class, error_message)
SELECT id, workflow_id, started_at, finished_at, status,
       success_count, new_count, fail_count, error_class, error_message
FROM crawl_runs_0001;

DROP TABLE crawl_runs_0001;

-- migrate:down
ALTER TABLE crawl_runs RENAME TO crawl_runs_0002;

CREATE TABLE crawl_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id   INTEGER NOT NULL REFERENCES workflows(id),
    started_at    TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at   TEXT,
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

INSERT INTO crawl_runs (id, workflow_id, started_at, finished_at, status,
                        success_count, new_count, fail_count, error_class, error_message)
SELECT id, workflow_id, started_at, finished_at, status,
       success_count, new_count, fail_count, error_class, error_message
FROM crawl_runs_0002
WHERE workflow_id IS NOT NULL;

DROP TABLE crawl_runs_0002;
