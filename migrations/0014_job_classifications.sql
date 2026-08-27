-- 본문을 나눈 결과를 담는다. 수집과 따로 돌고, 따로 남는다.
--
-- 왜 `normalized_jobs` 에 바로 쓰지 않는가. 그 표는 `raw_jobs` 에서 규칙으로 다시 만들어지는
-- 표다. 재정규화를 한 번 돌리면 분류가 채운 열한 칸이 통째로 NULL 로 돌아가고, 되살리려면
-- 640번을 다시 불러야 한다. 285만 토큰짜리 실수다.
--
-- 그래서 `job_field_overrides` 와 같은 자리에 둔다. **append-only 인 `raw_jobs` 에 매단다.**
-- 정규화는 규칙 -> 분류 -> 사람 보정 순으로 덮으므로, 재정규화를 몇 번 돌려도 분류 결과가
-- 따라붙고 사람이 고친 값은 그 위에 남는다 (`app/normalize/engine.py`).
--
-- `(raw_job_id)` 가 유일하다. 한 공고에 분류가 둘이면 어느 쪽이 지금 값인지 알 수 없다.
-- 다시 분류하면 같은 행을 덮는다 — 분류는 본문에서 다시 만들 수 있는 값이라 이력을 쌓을
-- 이유가 없고, 본문은 `raw_jobs` 에 그대로 있다.
--
-- 칸은 0011 이 만든 열여섯 중 열한 개다. 수집이 확실히 주는 여섯(제목·본문·모집 시작일·
-- 모집 마감일·회사명·원본 주소)은 여기 없다 — 그 여섯은 본문에서 뽑는 값이 아니다
-- (`.claude/tasks/todo/prd-llm-classify.md`).
--
-- | 컬럼 | 왜 있나 |
-- |---|---|
-- | `dropped_fields` | 모델이 냈지만 본문에서 찾지 못해 버린 칸 이름. 쉼표로 잇는다 |
-- | `model` | 그때의 모델 ID. 모델을 바꾼 뒤 품질이 갈리면 이 열로 가른다 |
-- | `classified_at` | |
--
-- `dropped_fields` 를 남기는 이유는 셈이다. 모델이 무엇을 얼마나 지어내는지는 세어 봐야
-- 알고, 세지 않으면 프롬프트를 고쳐도 나아졌는지 말할 수 없다 (`.claude/rules/llm.md`).
--
-- 분류하지 못한 공고는 **행이 없다.** 빈 행을 넣어 "분류했는데 아무것도 안 나왔다" 와
-- "아직 분류하지 않았다" 를 같은 모양으로 만들지 않는다. 다음 실행이 행 없는 공고를 찾아
-- 다시 돈다 (`app/classify/store.py` 의 `pending_ids`).
--
-- 되돌리기: `migrate down` 이 표를 지운다. **사라지는 것은 분류 결과뿐이다** —
-- `raw_jobs` 와 `normalized_jobs` 는 어느 방향으로도 건드리지 않는다. 되돌린 뒤 그 값이 다시
-- 필요하면 재크롤링 없이 다시 분류하면 되지만, 공고당 한 번씩 모델을 다시 부른다. 역적용
-- 전에 결과가 필요하면 뽑아 둔다:
--
--     SELECT * FROM job_classifications;

-- migrate:up
CREATE TABLE job_classifications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_job_id      INTEGER NOT NULL UNIQUE REFERENCES raw_jobs(id),
    job_category    TEXT,
    work_location   TEXT,
    career_level    TEXT,
    employment_type TEXT,
    headcount       TEXT,
    duties          TEXT,
    preferred       TEXT,
    hiring_process  TEXT,
    requirements    TEXT,
    department      TEXT,
    etc_info        TEXT,
    dropped_fields  TEXT NOT NULL DEFAULT '',
    model           TEXT NOT NULL,
    classified_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- migrate:down
DROP TABLE job_classifications;
