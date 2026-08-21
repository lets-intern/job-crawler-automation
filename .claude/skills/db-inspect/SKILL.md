---
name: db-inspect
description: "SQLite 에 쌓인 수집 데이터를 조회해 상태를 확인한다. 사용자가 '데이터 몇건 쌓였어', 'DB 확인해줘', '중복 들어갔는지 봐줘', '정규화 안된 데이터 찾아줘', '전달 안된 공고 확인' 등을 말할 때 사용한다."
argument-hint: "[counts(기본) | dupes | unnormalized | undelivered | schema]"
allowed-tools: Read, Bash, Grep
---

# 데이터 확인

운영 중인 SQLite 파일을 읽어 파이프라인 각 단계에 데이터가 제대로 흘렀는지 본다.

`.claude/rules/data-safety.md` 를 먼저 따른다. **이 스킬은 읽기 전용이다.**

## 대상 파일

경로는 `DATABASE_PATH` 환경변수가 정한다. 추측하지 말고 확인한다.

```bash
grep DATABASE_PATH .env 2>/dev/null || grep DATABASE_PATH .env.example
```

## 조회

| 인자 | 보는 것 |
|---|---|
| 없음 / `counts` | 테이블별 행 수. 파이프라인 어느 단계에서 끊겼는지 한눈에 |
| `dupes` | 같은 hash 가 2건 이상 — 중복 감지가 새고 있다는 뜻 |
| `unnormalized` | `raw_jobs` 에는 있는데 `normalized_jobs` 에 없는 건 |
| `undelivered` | `delivered_at IS NULL` 인 정규화 데이터 |
| `schema` | 실제 스키마. 모델 파일이 아니라 DB 가 진실이다 |

```bash
DB=$(grep -h '^DATABASE_PATH=' .env .env.example 2>/dev/null | head -1 | cut -d= -f2)
sqlite3 "$DB" "select 'raw',count(*) from raw_jobs
  union all select 'normalized',count(*) from normalized_jobs
  union all select 'undelivered',count(*) from normalized_jobs where delivered_at is null;"
```

## 읽는 법

`raw` 는 느는데 `normalized` 가 안 늘면 정규화 단계가 죽었다. 규칙 변경 직후라면 그 규칙이 예외를
던지고 있을 가능성이 높다.

`dupes` 가 잡히면 hash 계산에 들어가는 필드가 매 크롤마다 달라지는 값(조회수, 상대 날짜 등)을
포함하고 있는지부터 본다. `.claude/docs/data-model.md` 가 hash 대상 필드를 정한다.

`undelivered` 가 계속 쌓이면 소비 측(채용공고 사이트)이 폴링을 안 하고 있는 것이다. 이쪽 문제가
아닐 수 있으므로 단정하지 말고 마지막 전달 시각과 함께 보고한다.

## 쓰기가 필요할 때

이 스킬은 하지 않는다. `DELETE`, `UPDATE`, `DROP` 은 사용자가 명시적으로 요청했을 때만, 백업 후
별도로 진행한다 (`rules/data-safety.md`).

## 보고 형식

숫자 표 한 개와 이상 징후 한두 줄. 정상이면 정상이라고 한 줄로 끝낸다.
