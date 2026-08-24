-- 규칙 타입에 `html_text` 를 더한다.
--
-- LG 상세 API 가 `detailContext`, `requiredItem` 을 HTML 조각으로 준다. 수집 단계에서
-- 태그를 지우면 `raw_jobs` 가 원본이 아니게 되므로 정규화가 편다
-- (`.claude/rules/data-safety.md`). `rule_type` 의 CHECK 가 네 가지만 허용하고 있어서
-- 새 타입의 규칙은 저장 자체가 되지 않는다.
--
-- SQLite 는 CHECK 제약만 따로 고치지 못한다. 테이블을 지웠다 다시 만드는 대신 0008 과
-- 같은 방법을 쓴다 — 새 CHECK 를 단 컬럼을 더하고, 값을 옮기고, 옛 컬럼을 지우고, 이름을
-- 되돌린다. 행도 id 도 그대로 남는다.
--
-- 되돌리기: 같은 순서로 네 가지짜리 CHECK 를 단 컬럼을 만들어 되돌린다. 다만 `html_text`
-- 규칙 행은 옛 CHECK 에 담을 자리가 없어 역적용이 지운다. 되돌린 뒤 그 필드의 값에는 다시
-- 태그가 남으므로, 역적용 전에 어느 규칙이 `html_text` 였는지 적어 두고
-- (`seeds/normalization-rules.json` 에 같은 내용이 있다) 되돌린 뒤 재정규화한다.
-- 수집 데이터(`raw_jobs`)는 어느 방향으로도 건드리지 않는다.

-- migrate:up
ALTER TABLE normalization_rules ADD COLUMN rule_type_next TEXT NOT NULL DEFAULT 'trim'
    CHECK (rule_type_next IN ('mapping', 'regex', 'trim', 'date_parse', 'html_text'));

UPDATE normalization_rules SET rule_type_next = rule_type;

ALTER TABLE normalization_rules DROP COLUMN rule_type;

ALTER TABLE normalization_rules RENAME COLUMN rule_type_next TO rule_type;

-- migrate:down
DELETE FROM normalization_rules WHERE rule_type = 'html_text';

ALTER TABLE normalization_rules ADD COLUMN rule_type_prev TEXT NOT NULL DEFAULT 'trim'
    CHECK (rule_type_prev IN ('mapping', 'regex', 'trim', 'date_parse'));

UPDATE normalization_rules SET rule_type_prev = rule_type;

ALTER TABLE normalization_rules DROP COLUMN rule_type;

ALTER TABLE normalization_rules RENAME COLUMN rule_type_prev TO rule_type;
