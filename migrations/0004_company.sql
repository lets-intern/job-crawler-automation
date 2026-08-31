-- 회사명의 두 출처를 따로 저장한다.
--
-- 사이트 하나에 회사 하나가 아니다. 삼성 채용 사이트 하나에 삼성SDS, 삼성전기 공고가 섞여
-- 들어오므로 회사명은 공고 단위로 정해져야 한다. 그런데 회사명이 페이지 어디에도 없는 사이트도
-- 있어서, 그런 사이트는 운영자가 크롤러 단위로 한 번 적어 준다.
--
-- 운영자가 타이핑한 값은 추출 결과가 아니라 `raw_jobs` 에 들어가지 않는다
-- (`../.claude/rules/data-safety.md`). 그래서 `crawlers` 에 둔다. 파싱된 회사명은 다른 필드와
-- 똑같은 추출 결과라 `raw_jobs.raw_data_json` 에 그대로 들어가고, 컬럼이 필요 없다.
--
-- 둘을 합치는 것은 정규화 단계 하나뿐이고, 어느 쪽을 썼는지를 `company_source` 에 남긴다.
-- 그 값이 있어야 운영자값을 고쳐 재정규화할 때 무엇이 바뀌는지 미리 알 수 있다.
--
-- 되돌리기: 두 컬럼을 지운다. `crawlers.default_company` 에 적어 둔 회사명은 사라지고,
-- `normalized_jobs.company` 에 이미 확정된 값은 그대로 남는다.

-- migrate:up
ALTER TABLE crawlers ADD COLUMN default_company TEXT;

ALTER TABLE normalized_jobs ADD COLUMN company_source TEXT
    CHECK (company_source IS NULL OR company_source IN ('parsed', 'operator'));

-- migrate:down
ALTER TABLE normalized_jobs DROP COLUMN company_source;

ALTER TABLE crawlers DROP COLUMN default_company;
