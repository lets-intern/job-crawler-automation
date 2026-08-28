-- 부서·직군·모집인원 세 칸을 지운다.
--
-- 소비 측이 실제로 쓰는 칸만 남긴다 (`.claude/tasks/todo/prd-fields-and-logo.md`). 세 칸은
-- 값이 자리에 맞게 들어오지 않는다 — 2026-08-26 기록에 한화는 부서에 근무지가, SK 는 부서에
-- 직무가, 네이버는 회사에 부서가 들어가 있었다
-- (`seeds/site-configs-20260826.json` 의 `why_the_mappings_were_removed`). 모집인원은 적지
-- 않는 사이트가 많아 계약 문서의 예시값이 `"0명"` 이다.
--
-- **규칙 행을 먼저 지운다.** `normalization_rules` 에 지운 칸의 규칙이 남아 있으면
-- `load_rules` 가 `RuleConfigError`(`unknown_field`)를 던지고, 그 예외는 그 칸 하나가 아니라
-- 정규화 전체를 세운다 (`app/normalize/engine.py`). 읽히지 않는 것이 아니라 읽다가 터진다.

-- migrate:up
-- 지운 칸에 걸린 정규화 규칙. 2026-08-28 기준 `department` 에 둘이 있고 나머지 둘은 없다
DELETE FROM normalization_rules
 WHERE field_name IN ('department', 'job_category', 'headcount');

-- migrate:down
-- 되돌리기는 `seeds/normalization-rules.json` 에 있던 `department` 규칙 둘만 되살린다.
-- 운영자가 화면에서 더 넣은 규칙이 있었다면 그것은 돌아오지 않는다 — 무엇이 있었는지 이
-- 파일이 알 방법이 없다.
INSERT INTO normalization_rules (field_name, rule_type, rule_config_json, priority, enabled, note)
VALUES ('department', 'trim', '{"collapse_whitespace": true}', 0, 1, NULL),
       ('department', 'regex',
        '{"pattern": "^[\\s·\\-/|>]+|[\\s·\\-/|>]+$", "replacement": ""}', 10, 1,
        '부서명 앞뒤에 붙어 오는 구분기호를 뗀다');
