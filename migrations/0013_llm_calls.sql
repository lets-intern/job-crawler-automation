-- 모델 호출 하나를 행 하나로 남긴다.
--
-- 지금까지 비싼 호출은 셀렉터 생성뿐이었다. 사이트를 등록할 때 한 번이라 로그 줄 하나로
-- 충분했다. 본문 분류는 **공고마다 하나씩 붙는다** — 640건이면 640번이고, 사이트가 늘거나
-- 주기 실행이 새 공고를 물어올 때마다 계속 는다.
--
-- 로그 파일은 컨테이너를 다시 띄우면 사라진다. "이번 달에 토큰을 얼마나 썼나", "분류가
-- 생성보다 비싼가" 는 숫자를 세어야 답할 수 있는 질문이고, 세려면 남아 있어야 한다
-- (`../.claude/rules/llm.md` 의 "모델 ID·토큰 수·지연을 남긴다").
--
-- | 컬럼 | 왜 있나 |
-- |---|---|
-- | `provider` | 지금은 `gemini` 하나다. 두 번째 제공자를 위한 어댑터 층은 두지 않지만, |
-- |            | 이 열이 없으면 나중에 제공자가 바뀐 시점을 데이터에서 알 수 없다 |
-- | `model` | 모델 ID 는 `GEMINI_MODEL` 이 정하고 바뀐다. 그때의 값을 그대로 남긴다 |
-- | `feature` | `selector_generate` / `selector_repair` / `classify`. 무엇이 썼는지 |
-- | `input_tokens`, `output_tokens`, `total_tokens` | 비용 |
-- | `latency_ms` | 640건을 돌릴 때 얼마나 걸릴지 |
-- | `ok`, `error` | 실패한 호출도 토큰을 쓴다. 빼고 세면 합이 실제와 어긋난다 |
--
-- **수집 데이터가 아니라 실행 기록이다.** `raw_jobs` 와 성격이 다르고, 지워도 공고는 그대로다.
--
-- 프롬프트도 응답 본문도 담지 않는다. 남길 이유가 비용을 세는 것뿐인데 본문을 넣으면 이 표가
-- 수집 데이터만큼 커지고, 그 안에 사이트 본문이 한 벌 더 생긴다.
--
-- 조회는 둘이다 — 기간별 합, 기능별 합. 그래서 `called_at` 에만 인덱스를 건다. `feature` 는
-- 값이 셋뿐이라 인덱스가 도움이 되지 않는다.
--
-- 되돌리기: `migrate down` 이 표를 지운다. 사라지는 것은 호출 기록뿐이고 `raw_jobs`,
-- `normalized_jobs` 는 어느 방향으로도 건드리지 않는다. 되돌린 뒤 그 숫자는 다시 얻을 수
-- 없다 — 지난 호출을 다시 부를 수는 없기 때문이다. 역적용 전에 합계가 필요하면 뽑아 둔다:
--
--     SELECT feature, model, count(*), sum(total_tokens) FROM llm_calls GROUP BY 1, 2;

-- migrate:up
CREATE TABLE llm_calls (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    provider      TEXT NOT NULL,
    model         TEXT NOT NULL,
    feature       TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens  INTEGER NOT NULL DEFAULT 0,
    latency_ms    INTEGER NOT NULL DEFAULT 0,
    ok            INTEGER NOT NULL DEFAULT 1 CHECK (ok IN (0, 1)),
    error         TEXT NOT NULL DEFAULT '',
    called_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_llm_calls_called_at ON llm_calls(called_at);

-- migrate:down
DROP INDEX idx_llm_calls_called_at;

DROP TABLE llm_calls;
