-- 실행이 무엇을 놓쳤는지 남길 자리를 만든다.
--
-- 지금은 상세에 도달하지 못한 공고를 목록에서 읽은 값만으로 `raw_jobs` 에 넣고 성공으로
-- 넘긴다. 그 결과 `normalized_jobs.body` 가 빈 행이 216건 중 86건이고, 그 86건은
-- `source_url` 이 목록 주소인 행과 정확히 같다. 앞으로는 넣지 않는 대신 실행 기록에 남긴다.
--
-- 여기 들어가는 것은 수집 데이터가 아니라 **실행 기록**이다. `raw_jobs` 와 성격이 다르다.
--
-- `skipped_count` 는 실패가 아니다. 마감이 지났거나 이미 저장한 공고라 상세를 열지 않은
-- 건수다. `fail_count` 와 반드시 따로 센다 — 합치면 날짜 형식이 바뀌어 전부 걸러진 사이트가
-- "새 공고 0건" 인 정상 실행으로 보인다. 이 저장소가 처음부터 막으려던 실패다.
--
-- `crawl_run_failures` 는 실행 하나가 놓친 공고를 한 줄씩 남긴다. 건수만으로는 고칠 수 없어서
-- 제목과 목록에서 읽은 주소까지 같이 남긴다. 조회는 실행 하나의 실패를 모아 보는 것 하나뿐이라
-- `run_id` 에만 인덱스를 건다.
--
-- `reason` 은 `app/crawler/failures.py` 의 `ERROR_CLASSES` 와 같은 값이어야 한다. 분류를
-- 모르는 실패는 NULL 이다 — 모르는 실패를 아는 실패로 위장하면 그 사이트를 계속 잘못 고치게
-- 된다.
--
-- 보관 기한을 따로 두지 않는다. 실행 기록이 지워지면 같이 지워진다(`ON DELETE CASCADE`).
-- 실패 목록은 그 실행을 설명하는 것이지 혼자 남아 뜻이 있는 기록이 아니다.
--
-- `crawl_runs.error_class` 의 CHECK 도 같은 여섯 값으로 넓힌다. 0001 이 만든 세 가지 그대로면
-- `detail_empty` 로 끝난 실행은 기록되는 순간 거절되고, 기록이 없는 실행은 아무도 디버깅하지
-- 못한다 (`../.claude/rules/crawling.md`). SQLite 는 CHECK 제약만 따로 고치지 못하므로 0009 와
-- 같은 방법을 쓴다 — 새 CHECK 를 단 컬럼을 더하고, 값을 옮기고, 옛 컬럼을 지우고, 이름을
-- 되돌린다. 표를 지웠다 다시 만들지 않으므로 행도 id 도 그대로 남는다.
--
-- 되돌리기: `migrate down` 이 `crawl_runs.error_class` 를 세 가지 CHECK 로 되돌리고,
-- `crawl_run_failures` 를 지우고, `skipped_count` 컬럼을 지운다. 옛 CHECK 에 담을 자리가 없는
-- 새 사유 세 가지는 NULL 로 내려온다 — 실행 기록 자체와 `error_message` 는 남고 분류만
-- 사라진다. 지워지는 것은 실패 목록과 건너뛴 건수 기록뿐이고, 수집 데이터(`raw_jobs`)는 어느
-- 방향으로도 건드리지 않는다. 역적용 전에 실패 목록이 필요하면 따로 뽑아 둔다.

-- migrate:up
ALTER TABLE crawl_runs ADD COLUMN skipped_count INTEGER NOT NULL DEFAULT 0;

-- 수집 데이터가 아니라 실행 기록이다. `raw_jobs` 가 아니다
CREATE TABLE crawl_run_failures (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     INTEGER NOT NULL REFERENCES crawl_runs(id) ON DELETE CASCADE,
    -- 분류하지 못한 실패는 NULL 로 두고 `message` 에 남긴다
    reason     TEXT CHECK (
                   reason IS NULL
                   OR reason IN ('transport', 'selector_miss', 'parse',
                                 'list_empty', 'detail_unreachable', 'detail_empty')
               ),
    -- 목록에서 읽은 값. 어느 공고였는지 아는 유일한 단서다
    title      TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    message    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_crawl_run_failures_run_id ON crawl_run_failures (run_id);

-- `crawl_run_failures.reason` 과 같은 값이어야 한다. 둘이 갈리면 항목 실패는 남았는데 실행
-- 기록은 그 분류를 담지 못하는 상태가 된다
ALTER TABLE crawl_runs ADD COLUMN error_class_next TEXT CHECK (
    error_class_next IS NULL
    OR error_class_next IN ('transport', 'selector_miss', 'parse',
                            'list_empty', 'detail_unreachable', 'detail_empty')
);

UPDATE crawl_runs SET error_class_next = error_class;

ALTER TABLE crawl_runs DROP COLUMN error_class;

ALTER TABLE crawl_runs RENAME COLUMN error_class_next TO error_class;

-- migrate:down
-- 옛 CHECK 에 담을 자리가 없다. 실행 기록은 남기고 분류만 비운다
UPDATE crawl_runs
   SET error_class = NULL
 WHERE error_class IN ('list_empty', 'detail_unreachable', 'detail_empty');

ALTER TABLE crawl_runs ADD COLUMN error_class_prev TEXT CHECK (
    error_class_prev IS NULL
    OR error_class_prev IN ('transport', 'selector_miss', 'parse')
);

UPDATE crawl_runs SET error_class_prev = error_class;

ALTER TABLE crawl_runs DROP COLUMN error_class;

ALTER TABLE crawl_runs RENAME COLUMN error_class_prev TO error_class;

DROP INDEX IF EXISTS idx_crawl_run_failures_run_id;

DROP TABLE crawl_run_failures;

ALTER TABLE crawl_runs DROP COLUMN skipped_count;
