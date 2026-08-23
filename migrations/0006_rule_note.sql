-- 규칙에 사람이 읽는 메모를 붙인다.
--
-- 정규식만 늘어놓으면 몇 주 뒤에 그 규칙이 무엇을 하려던 것인지 아무도 모른다. 지금 등록된
-- 24개 규칙 중 deadline 하나에만 7개가 걸려 있고, 각각이 기간 표기를 자르고 시각을 떼고
-- 요일을 떼는 서로 다른 일을 한다. 이름이 없으면 지우지도 고치지도 못한다.
--
-- 비워도 된다. 기존 행은 NULL 로 남는다.
--
-- 되돌리기: 컬럼을 지운다. 메모만 사라지고 규칙 동작에는 영향이 없다 — 정규화 엔진은 이
-- 컬럼을 읽지 않는다.

-- migrate:up
ALTER TABLE normalization_rules ADD COLUMN note TEXT;

-- migrate:down
ALTER TABLE normalization_rules DROP COLUMN note;
