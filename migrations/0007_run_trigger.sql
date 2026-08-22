-- 실행 하나가 어디서 시작됐는지를 남긴다.
--
-- 지금은 `crawl_runs` 만 보고서는 스케줄러가 깨운 실행인지 운영자가 화면에서 누른 1회 실행인지
-- 구분할 수 없다. 그래서 "주기가 실제로 도는가" 라는 질문에 답할 방법이 없다 — 최근 실행이
-- 있어도 그것이 사람이 누른 것이면 주기는 죽어 있는 것이다.
--
-- `schedule` 은 APScheduler 잡, `manual` 은 워크플로우 카드의 지금 1회 실행, `test` 는 승격 전
-- 크롤러의 테스트 실행이다. 셋 밖의 값은 CHECK 가 막는다.
--
-- 기존 행은 NULL 로 남는다. 그 실행들이 어디서 왔는지는 기록되지 않았고, 지금 와서 추측해
-- 채우면 없는 사실을 만드는 것이다. 화면은 NULL 을 `알 수 없음` 으로 적는다.
--
-- 되돌리기: 컬럼을 지운다. 출처 기록만 사라지고 실행 기록 자체는 그대로다.

-- migrate:up
ALTER TABLE crawl_runs ADD COLUMN trigger TEXT CHECK (
    trigger IS NULL OR trigger IN ('schedule', 'manual', 'test')
);

-- migrate:down
ALTER TABLE crawl_runs DROP COLUMN trigger;
