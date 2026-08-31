-- 공고 하나를 담는 칸을 여섯에서 열여섯으로 늘린다.
--
-- 사이트가 이미 나눠서 주는 것을 도로 합쳐 담고 있었다. 칸이 모자라 빈 칸을 채우려다 한화
-- `department` 에 근무지(`ruWorkpl`)가 들어가 있고, 317건 중 `department` 는 대부분이 비어
-- 있다. 칸을 늘려 나뉜 값이 제자리에 들어가게 한다 (`../.claude/tasks/todo/prd-split-body.md`).
--
-- 더하는 칸은 **열한 사이트 응답을 대조해 넷 이상이 주는 것만** 골랐다. 한 사이트만 가진
-- 값을 칸으로 만들면 나머지 열 곳이 비는 칸이 하나 는다. 셈과 자리는
-- `tests/test_split_body_columns.py` 가 픽스처로 들고 있다.
--
-- | 컬럼 | 뜻 | 주는 곳 |
-- |---|---|---|
-- | `start_date` | 모집 시작일 | 9 |
-- | `job_category` | 직군 | 7 |
-- | `work_location` | 근무지 | 7 |
-- | `duties` | 주요 업무 | 7 |
-- | `hiring_process` | 전형 절차 | 7 |
-- | `etc_info` | 기타 | 7 |
-- | `career_level` | 경력 구분(신입/경력) | 5 |
-- | `employment_type` | 고용형태(정규직/인턴/기간제) | 4 |
-- | `headcount` | 모집인원 | 4 |
-- | `preferred` | 우대 조건 | 4 |
--
-- **기존 여섯 칸은 지우지도 이름을 바꾸지도 않는다.** 소비 측이 읽던 것이 사라지면 안 된다
-- (`docs/api-contract.md`). 특히 `deadline` 은 모집 마감일 그대로 두고 모집 시작일을
-- `start_date` 로 새로 더한다 — 이름이 비슷하다고 옮기지 않는다.
--
-- 전부 NULL 을 허용한다. **사이트가 주지 않는 칸은 빈 칸이다** — 없는 값을 다른 값으로 채우지
-- 않는다. 빈 칸은 "이 사이트는 이 값을 주지 않는다" 는 사실이고, 틀린 값은 소비 측이 그대로
-- 노출한다. 기본값을 두지 않는 것도 같은 이유다.
--
-- 이 마이그레이션은 칸을 만들기만 한다. 어느 사이트의 어느 응답이 어느 칸에 들어갈지는
-- Push 2 가 정하므로, 적용 직후 새 칸 열 개는 기존 317건 전부에서 NULL 이다. 기존 여섯 칸의
-- 값은 손대지 않는다 — 이 파일에 `normalized_jobs` 를 대상으로 하는 UPDATE 가 없다.
--
-- `job_field_overrides.field_name` 의 CHECK 는 넓히지 않았다. 사람 손보정은 여섯 칸 그대로다.
-- 그 컬럼은 `UNIQUE (raw_job_id, field_name)` 의 인덱스에 걸려 있어서 0009·0010 이 쓴 방법
-- (새 CHECK 를 단 컬럼 추가 -> 값 이동 -> 옛 컬럼 삭제)이 통하지 않는다 — SQLite 는 인덱스가
-- 걸린 컬럼을 DROP 하지 못한다. 새 칸의 손보정이 필요해지면 그때 따로 다룬다.
--
-- 되돌리기: `migrate down` 이 더한 컬럼 열 개를 역순으로 지운다. 인덱스도 제약도 걸지 않았고
-- 기존 컬럼을 건드리지 않으므로, 되돌리면 0010 시점의 `normalized_jobs` 와 같아진다.
-- **지워지는 것은 새 칸에 들어간 값뿐이다.** 되돌린 뒤 그 값이 다시 필요하면 재크롤링 없이
-- 재정규화하면 된다 — 출처인 `raw_jobs` 는 append-only 라 그대로 남아 있다
-- (`../.claude/rules/data-safety.md`). 다만 Push 2 가 매핑을 바꾼 뒤라면 `raw_jobs` 에 그 값이
-- 들어오기 시작한 시점부터만 되살아난다.

-- migrate:up
-- 모집 시작일. `deadline`(모집 마감일)의 짝이고 그 칸을 대신하지 않는다
ALTER TABLE normalized_jobs ADD COLUMN start_date TEXT;

ALTER TABLE normalized_jobs ADD COLUMN job_category TEXT;

ALTER TABLE normalized_jobs ADD COLUMN employment_type TEXT;

ALTER TABLE normalized_jobs ADD COLUMN career_level TEXT;

ALTER TABLE normalized_jobs ADD COLUMN work_location TEXT;

ALTER TABLE normalized_jobs ADD COLUMN headcount TEXT;

ALTER TABLE normalized_jobs ADD COLUMN duties TEXT;

ALTER TABLE normalized_jobs ADD COLUMN preferred TEXT;

ALTER TABLE normalized_jobs ADD COLUMN hiring_process TEXT;

ALTER TABLE normalized_jobs ADD COLUMN etc_info TEXT;

-- migrate:down
ALTER TABLE normalized_jobs DROP COLUMN etc_info;

ALTER TABLE normalized_jobs DROP COLUMN hiring_process;

ALTER TABLE normalized_jobs DROP COLUMN preferred;

ALTER TABLE normalized_jobs DROP COLUMN duties;

ALTER TABLE normalized_jobs DROP COLUMN headcount;

ALTER TABLE normalized_jobs DROP COLUMN work_location;

ALTER TABLE normalized_jobs DROP COLUMN career_level;

ALTER TABLE normalized_jobs DROP COLUMN employment_type;

ALTER TABLE normalized_jobs DROP COLUMN job_category;

ALTER TABLE normalized_jobs DROP COLUMN start_date;
