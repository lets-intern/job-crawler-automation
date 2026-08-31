-- 회사명 출처 열을 지운다.
--
-- 0004 가 이 열을 둔 이유는 회사명이 한 칸이었기 때문이다. 파싱값과 운영자값을 그 한 칸에
-- 합쳐 넣으면서, 어느 쪽을 썼는지를 `parsed` / `operator` 로 남겼다. 0018 이 칸을 둘로 가른
-- 뒤로 그 질문에는 칸 이름이 답한다 — `company` 에 있으면 사이트가 준 값이고
-- `parent_company` 에 있으면 우리가 채운 값이다 (`migrations/0018_parent_company.sql`).
--
-- 남겨 두면 답이 둘이 된다. 정규화가 더 이상 쓰지 않으므로 새로 들어오는 행은 전부 NULL 이고,
-- 지난 행에는 옛 값이 남는다. 그 열을 읽는 사람은 "출처를 모르는 공고가 이만큼 있다" 로
-- 읽는데 그것은 사실이 아니다.
--
-- **이 마이그레이션은 0018 과 갈라져 있다.** 컬럼을 더하는 것은 DB 가 코드보다 넓어질 뿐이라
-- 아무것도 깨지 않지만(0017 이 같은 이유로 코드를 다음 커밋에서 넓혔다), 지우는 것은 그
-- 컬럼에 쓰는 코드가 손을 놓은 뒤여야 한다. 0018 에서 함께 지웠다면 그 커밋에서
-- `insert_normalized` 가 없는 컬럼에 쓰게 되어 정규화가 한 건도 되지 않는다.
--
-- 지우는 것은 `normalized_jobs` 의 컬럼 하나뿐이다. `raw_jobs` 도 `job_field_overrides` 도
-- 건드리지 않는다 — 출처는 규칙 단계가 정하던 값이라 보정 행이 있을 수 없고, 그래서 0016 처럼
-- 남겨 둘 것을 따질 일도 없다 (`../.claude/rules/data-safety.md`).
--
-- `crawlers.default_company` 는 그대로 둔다. 0004 가 더한 둘 중 그쪽은 운영자가 적어 둔 값이고
-- 지금은 `parent_company` 의 출처다. 이 파일이 지우면 모회사 칸이 크롤러 이름으로만 채워진다.
--
-- 되돌리기: `migrate down` 이 CHECK 까지 같은 모양으로 컬럼을 되살린다. **컬럼은 돌아오지만
-- 값은 돌아오지 않는다** — 전부 NULL 이다. 어느 행이 `parsed` 였는지는 되살린 뒤에도
-- 두 칸으로 읽으면 안다. `company` 에 값이 있으면 그 행이 `parsed` 였다.

-- migrate:up
ALTER TABLE normalized_jobs DROP COLUMN company_source;

-- migrate:down
ALTER TABLE normalized_jobs ADD COLUMN company_source TEXT
    CHECK (company_source IS NULL OR company_source IN ('parsed', 'operator'));
