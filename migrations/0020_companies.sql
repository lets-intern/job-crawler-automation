-- 회사 표를 만든다.
--
-- 로고는 공고 단위가 아니라 회사 단위 값이다. `normalized_jobs` 에 칸을 더하면 같은 주소가
-- 그 회사의 공고 수만큼 복사되고, 로고를 한 번 바꾸는 일이 100행을 고치는 일이 된다
-- (`.claude/tasks/todo/prd-fields-and-logo.md` 4장).
--
-- | 칸 | 무엇이 들어오나 |
-- |---|---|
-- | `name` | 그 공고의 자회사, 없으면 모회사. 유일하다 |
-- | `parent_name` | 그 회사의 모회사. 자회사가 없어 이름이 곧 모회사면 NULL 이다 |
-- | `logo_url` | 운영자가 올린 로고의 공개 주소. 만들어질 때는 비어 있다 |
--
-- 행은 정규화가 만든다. 처음 보는 회사명을 만나면 로고가 빈 행이 생기고, 운영자는 화면에서
-- 로고만 채운다. 자동으로 만들지 않으면 운영자가 회사명을 손으로 다시 치게 되고, 오타 하나면
-- 그 로고는 어느 공고에도 붙지 않는다.
--
-- **공고와 외래키로 잇지 않는다.** 잇는 값은 회사명이다. 공고가 다 지워져도 이 행은 남아야
-- 하는데(로고를 지우는 것은 운영자가 한다), 외래키를 걸면 그 순간 남길지 지울지를 DB 가
-- 정하게 된다. `normalized_jobs.company` 는 재정규화로 값이 바뀌는 칸이라 참조 대상으로도
-- 맞지 않는다.
--
-- `name` 이 유일한 것이 이 표의 전부다. 같은 이름이 두 행이면 로고가 둘이 되고, 공고가 어느
-- 쪽을 볼지 정할 방법이 없다. 다만 `삼성전기` 와 `삼성전기(주)` 는 DB 가 다른 이름으로 보므로
-- 이름을 맞추는 것은 여전히 `company` 의 mapping 규칙이 할 일이다.
--
-- `updated_at` 은 응용이 적는다. 트리거를 두지 않는 것은 이 표를 쓰는 자리가
-- `app/companies.py` 하나뿐이라, 갱신 시각이 어디서 정해지는지 코드에서 읽히는 편이 낫기
-- 때문이다.
--
-- 되돌리기: `migrate down` 이 표를 통째로 지운다. 사라지는 것은 운영자가 올린 로고 주소이고,
-- 파일 자체는 저장소에 남는다. 회사명과 모회사는 재정규화가 다시 만든다.

-- migrate:up
CREATE TABLE companies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    parent_name TEXT,
    logo_url    TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- migrate:down
DROP TABLE companies;
