-- 크롤링과 따로 도는 작업 — LLM 분류, 스프링 전달 — 의 설정과 실행 기록.
--
-- ## 왜 `workflows` 에 합치지 않는가
--
-- 셋이다.
--
-- `workflows.crawler_id` 는 `NOT NULL` 이고 분류에는 크롤러가 없다. 합치려면 그 제약을 풀어야
-- 하는데, 그 순간 "워크플로우는 크롤러 하나를 돈다" 가 스키마에서 사라진다.
--
-- 세는 것이 다르다. `crawl_runs` 는 신규·건너뜀·실패를 세고, 분류가 셀 것은 처리 건수와 버린
-- 칸이고, 전달이 셀 것은 전송 건수다. 한 표에 넣으면 어느 컬럼이 어느 종류에서만 뜻이 있는지
-- 아무 데도 적혀 있지 않게 된다.
--
-- 이미 결정으로 서 있다. `app/api/classify.py` 와 `app/normalize/backfill.py` 가
-- "`crawl_runs` 에 쓰지 않는다, 섞으면 워크플로우 성공·실패 통계가 크롤링과 무관한 이유로
-- 움직인다" 를 근거로 들고 있다. 이 표는 그 결정을 스키마로 옮긴 것이다.
--
-- ## 컬럼이 받는 값
--
-- | 컬럼 | 값 |
-- |---|---|
-- | `kind` | `classify` / `deliver` |
-- | `status` | `active` / `paused`. **새로 만들면 `paused` 다** |
-- | `trigger_kind` | `interval` / `after_crawl` / `manual` |
-- | `target_scope` | `kind` 마다 다르다. 아래 |
-- | `target_days` | `recent` 일 때만 쓴다. 그 밖에는 NULL |
-- | `batch_limit` | 1회 상한 건수 |
--
-- `target_scope` 가 받는 값이 `kind` 마다 다르다. 분류는 `unclassified`(기본) / `empty_fields`
-- / `recent` / `all` 이고, 전달은 `undelivered`(기본) / `recent` / `all` 이다. 둘을 합집합
-- 하나로 두면 전달 워크플로우에 `unclassified` 가 들어가고, 그 행은 저장될 때가 아니라 실행할
-- 때 대상을 못 찾아서 드러난다. 그래서 CHECK 가 `kind` 와 함께 본다.
--
-- `target_days` 도 같은 이유로 `target_scope` 와 함께 본다. `recent` 가 아닌데 일수가 적혀
-- 있으면 그 값이 언젠가 쓰이는 값인지 남은 값인지 읽는 쪽이 알 수 없다.
--
-- 새로 만들면 `paused` 인 것이 기본값에 들어 있다. 대상 범위를 잘못 고른 채 저장하는 것과
-- 그것이 곧바로 도는 것은 다른 이야기고, `all` 은 640건이면 약 285만 토큰이다.
--
-- **토큰 수 컬럼을 두지 않는다.** `llm_calls` 가 호출마다 남기고 있고 (`app/llm/log.py`), 같은
-- 숫자를 두 곳에서 세면 어느 쪽이 진실인지 매번 확인해야 한다.
--
-- `batch_limit` 의 상한도 두지 않는다. 그 값은 `app/classify/batch.py` 의 `MAX_LIMIT` 이고,
-- 여기에 200 을 적으면 상한을 고치는 일이 마이그레이션이 된다. DB 는 1 미만만 막는다.
--
-- ## 실행 기록
--
-- `side_runs` 는 실행마다 한 행이다. 시작할 때 `status` NULL 로 만들고 끝날 때 확정한다.
-- 기록이 없는 실행이 없어야 한다는 규칙은 크롤 실행과 같다 (`.claude/rules/crawling.md`).
--
-- `skipped` 는 앞 실행이 아직 돌고 있어 이번 차례를 건너뛴 것이다. 행을 남기지 않으면 주기가
-- 도는데 아무것도 안 하는 상태와 주기가 죽은 상태가 같아 보인다. `timeout` 은 프로세스가
-- 끝나기 전에 사라져 아무도 종료를 적지 못한 실행이다.
--
-- `trigger` 는 이 실행을 무엇이 깨웠는지다. `schedule` 은 APScheduler, `after_crawl` 은 크롤
-- 실행이 새 공고를 적재한 직후, `manual` 은 화면에서 누른 것이다. `crawl_runs.trigger` 와 같은
-- 낱말을 쓰되 `test` 는 없다 — 부가 작업에는 승격 전 크롤러 같은 것이 없다.
--
-- 인덱스를 두지 않는다. 실행이 하루 몇 건이라 전체 훑기가 인덱스보다 싸고, 이 표를 읽는 곳은
-- 최근 것부터 몇 건을 보여주는 화면 하나다.
--
-- 되돌리기: `migrate down` 이 두 표를 지운다. 사라지는 것은 부가 워크플로우 설정과 그 실행
-- 기록뿐이다. `workflows`, `crawl_runs`, `raw_jobs`, `normalized_jobs` 는 이 마이그레이션이
-- 건드리지 않으므로 그대로 남는다. 되돌린 뒤 설정은 화면에서 다시 만들어야 하고, 지난 실행
-- 기록은 되살릴 수 없다.

-- migrate:up
CREATE TABLE side_workflows (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    kind             TEXT NOT NULL CHECK (kind IN ('classify', 'deliver')),
    name             TEXT NOT NULL,
    -- 새로 만들면 멈춘 채로 시작한다. 켜는 것은 운영자가 한다
    status           TEXT NOT NULL DEFAULT 'paused'
                     CHECK (status IN ('active', 'paused')),
    trigger_kind     TEXT NOT NULL DEFAULT 'manual'
                     CHECK (trigger_kind IN ('interval', 'after_crawl', 'manual')),
    interval_minutes INTEGER NOT NULL DEFAULT 360 CHECK (interval_minutes >= 1),
    target_scope     TEXT NOT NULL,
    -- `recent` 일 때만 값이 있다
    target_days      INTEGER,
    -- 1회 상한. 위쪽 상한은 `app/classify/batch.py` 의 `MAX_LIMIT` 이 정한다
    batch_limit      INTEGER NOT NULL DEFAULT 50 CHECK (batch_limit >= 1),
    last_run_at      TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),

    -- 받는 대상 범위가 종류마다 다르다
    CHECK (
        (kind = 'classify'
         AND target_scope IN ('unclassified', 'empty_fields', 'recent', 'all'))
        OR (kind = 'deliver' AND target_scope IN ('undelivered', 'recent', 'all'))
    ),
    -- 일수는 `recent` 에만 있고 `recent` 에는 반드시 있다
    CHECK (
        CASE WHEN target_scope = 'recent' THEN target_days IS NOT NULL AND target_days >= 1
             ELSE target_days IS NULL END
    )
);

CREATE TABLE side_runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    side_workflow_id INTEGER NOT NULL REFERENCES side_workflows(id),
    trigger          TEXT NOT NULL
                     CHECK (trigger IN ('schedule', 'after_crawl', 'manual')),
    started_at       TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at      TEXT,
    -- 실행 중에는 NULL. 종료 시 네 값 중 하나로 확정된다
    status           TEXT CHECK (
                         status IS NULL
                         OR status IN ('success', 'failed', 'skipped', 'timeout')
                     ),
    target_count     INTEGER NOT NULL DEFAULT 0,
    processed_count  INTEGER NOT NULL DEFAULT 0,
    failed_count     INTEGER NOT NULL DEFAULT 0,
    -- 사람이 읽는 한 줄. 건너뛴 사유가 여기 들어간다
    note             TEXT,
    error_message    TEXT
);

-- migrate:down
DROP TABLE side_runs;
DROP TABLE side_workflows;
