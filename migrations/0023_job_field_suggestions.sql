-- 값이 있는 칸에 모델이 다른 값을 낸 것을 저장한다. 자동으로 덮지 않는다.
--
-- PRD 6절이 세 상황을 가른다 — 칸이 비어 있고 원문에 값이 있으면 채우고(`job_classifications`
-- 로, 지금 경로 그대로), 칸에 값이 있는데 원문과 다르면 이 표에 제안으로 남기고, 원문에도
-- 없으면 빈 칸으로 둔다. 값이 있는 칸을 모델 판단 하나로 덮지 않는 이유는
-- `.claude/tasks/todo/prd-side-workflows.md` 6절에 있다 — `deadline` 은 마감 지난 공고를
-- 거르는 데 쓰이고 `company` 는 계열사를 가르는 값이라, 이 둘이 본문 판독 하나로 바뀌면 안
-- 된다.
--
-- ## 대상 필드
--
-- `field_name` 은 `app/normalize/rules.py` 의 `NORMALIZED_FIELDS` 열네 칸 전부를 받는다.
-- 분류가 채우는 아홉 칸(`app/classify/schema.py` 의 `CLASSIFY_FIELDS`)뿐 아니라 수집이
-- 채우는 다섯 칸(`company`, `title`, `deadline`, `body`, `start_date`)도 대상이다 —
-- PRD 6절이 "수집이 채우는 여섯 칸도 제안 대상에 넣되 자동으로 덮지 않는다" 고 정했고,
-- `source_url` 은 공고의 신원이라 제외한 나머지 다섯이 그 여섯 칸 중 이 표에 들어오는 것이다.
-- `job_field_overrides` 와 같은 목록을 쓰는 것은 우연이 아니다 — 제안이 수락되면 그 표로
-- 옮겨 가야 하고, 옮겨 갈 칸이 옮겨 가지 못하는 칸보다 넓으면 수락이 저장 단계에서 거절된다.
--
-- ## 같은 칸에 제안은 하나뿐이다
--
-- `(raw_job_id, field_name)` 이 유일하다. 같은 칸에 제안이 둘이면 사람이 어느 것을 보고 있는지
-- 알 수 없다. 새 분류 실행이 같은 칸에 다시 제안을 내면 옛 제안을 덮어써야 하고, 그 덮어쓰기는
-- `INSERT ... ON CONFLICT(raw_job_id, field_name) DO UPDATE` 로 한다 — UNIQUE 가 없으면 이
-- 문장 자체가 성립하지 않는다.
--
-- `reason` 은 모델이 적은 "왜 다른가" 한 줄이다. NOT NULL 이되 빈 문자열은 허용한다 — 근거
-- 검사(`app/classify/grounding.py`)를 통과해 제안이 된 값은 이유가 있는 것이 정상이지만,
-- 이유 한 줄이 없다고 제안 자체를 막을 이유는 없다. 값이 다르다는 사실 자체가 검수자에게
-- 이미 신호다.
--
-- `value` 는 채우기(`job_classifications`)와 달리 빈 문자열을 담을 이유가 없다 — 빈 칸을
-- "다른 값" 으로 제안하는 것은 뜻이 서지 않는다. 그래서 NOT NULL 이고 빈 문자열도 막지 않는
-- 대신, 빈 값을 넣지 않는 것은 이 표를 쓰는 코드(`app/classify/*`)의 책임으로 둔다 — 스키마가
-- 막으면 "왜 비었는지" 검사가 여기와 코드 두 곳에 나뉜다.
--
-- ## 정규화는 이 표를 읽지 않는다
--
-- `app/normalize/engine.py` 의 어느 경로도 이 표를 참조하지 않는다. 제안은 사람이 검수 화면에서
-- 수락해야만 `job_field_overrides` 로 옮겨 가고, 그 전까지는 `raw_jobs` 도 `normalized_jobs` 도
-- 이 표의 존재를 모른다 (PRD 6절, `.claude/rules/llm.md` — 모델은 제안자이지 권위가 아니다).
--
-- 되돌리기: 테이블을 지운다. 사라지는 것은 아직 수락하지 않은 제안뿐이다. 수락된 제안은 이미
-- `job_field_overrides` 에 옮겨져 있으므로 영향받지 않는다.

-- migrate:up
CREATE TABLE job_field_suggestions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_job_id INTEGER NOT NULL REFERENCES raw_jobs(id),
    field_name TEXT NOT NULL CHECK (
                   field_name IN (
                       'company', 'title', 'job_role', 'deadline', 'body', 'requirements',
                       'start_date', 'employment_type', 'career_level', 'work_location',
                       'duties', 'preferred', 'hiring_process', 'etc_info'
                   )
               ),
    value      TEXT NOT NULL,
    reason     TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (raw_job_id, field_name)
);

-- migrate:down
DROP TABLE job_field_suggestions;
