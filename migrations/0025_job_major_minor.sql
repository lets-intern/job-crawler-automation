-- 직무 분류 결과가 앉는 자리. `job_taxonomy`(0024)의 이름을 그대로 옮겨 담는다.
--
-- id 가 아니라 이름을 저장한다. `normalized_jobs` 는 재정규화로 다시 만들어지는 파생
-- 표이고 소비 측이 받는 것도 이름이다 — id 를 넣으면 소비 측이 우리 표를 한 벌 더 갖게
-- 되고, 이름이 바뀌어도 소비 측은 알 방법이 없다 (`../.claude/tasks/todo/prd-job-taxonomy.md`
-- 1절).
--
-- 칸이 두 자리에 는다. `job_role`(0017)과 같은 이유다 — 분류가 낸 값이 먼저
-- `job_classifications` 에 앉고, 정규화가 그 값을 `normalized_jobs` 로 옮긴다
-- (`app/classify/store.py::save_classification` 은 `CLASSIFY_FIELDS` 를 그대로 컬럼
-- 목록으로 써서, 그 표에 이 두 칸이 없으면 저장 자체가 `OperationalError` 로 죽는다).
--
-- `job_major` 만 있고 `job_minor` 는 NULL 인 행이 있을 수 있다 — 대분류는 분명한데
-- 본문으로 소분류가 갈리지 않는 공고다. 그 반대(소분류만 있고 대분류가 없는 행)는 분류
-- 로직이 만들지 않는다(Push 3).
--
-- 적용 직후 두 칸은 기존 행 전부에서 NULL 이다. 값은 분류를 다시 돌려야 들어온다 — 이
-- 파일에 `normalized_jobs` 나 `job_classifications` 를 대상으로 하는 UPDATE 가 없다.
--
-- 되돌리기: 두 표에서 각각 두 칸을 지운다. `job_taxonomy` 표 자체는 건드리지 않으므로,
-- 되돌린 뒤 다시 켜면 재크롤링 없이 재분류만으로 값이 돌아온다.

-- migrate:up
ALTER TABLE normalized_jobs ADD COLUMN job_major TEXT;
ALTER TABLE normalized_jobs ADD COLUMN job_minor TEXT;

ALTER TABLE job_classifications ADD COLUMN job_major TEXT;
ALTER TABLE job_classifications ADD COLUMN job_minor TEXT;

-- migrate:down
ALTER TABLE job_classifications DROP COLUMN job_minor;
ALTER TABLE job_classifications DROP COLUMN job_major;

ALTER TABLE normalized_jobs DROP COLUMN job_minor;
ALTER TABLE normalized_jobs DROP COLUMN job_major;
