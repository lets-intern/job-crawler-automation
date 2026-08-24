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
-- 되돌리기: `migrate down` 이 `skipped_count` 컬럼을 지운다. 지워지는 것은 건너뛴 건수
-- 기록뿐이고, 실행 기록 자체와 수집 데이터는 어느 방향으로도 건드리지 않는다.

-- migrate:up
ALTER TABLE crawl_runs ADD COLUMN skipped_count INTEGER NOT NULL DEFAULT 0;

-- migrate:down
ALTER TABLE crawl_runs DROP COLUMN skipped_count;
