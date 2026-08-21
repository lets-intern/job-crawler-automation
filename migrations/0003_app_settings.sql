-- 어드민에서 바꾸는 운영 설정 저장소.
--
-- 동시 실행 상한은 고정값이 아니라 운영 중에 바꾸는 값으로 결정됐다 (2026-08-21).
-- `.env` 의 MAX_CONCURRENT_RUNS 는 값이 아직 없을 때 넣어 주는 초기값일 뿐이고, 한 번 들어간
-- 뒤로는 이 테이블이 진실이다.
--
-- 키를 늘리지 않는다. 지금 들어가는 것은 max_concurrent_runs 하나뿐이고, 환경변수로 충분한
-- 값을 여기에 옮기면 같은 설정이 두 곳에 생긴다.
--
-- 되돌리기: 테이블을 지운다. 지우면 상한은 다시 환경변수 값으로 돌아간다.

-- migrate:up
CREATE TABLE app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- migrate:down
DROP TABLE app_settings;
