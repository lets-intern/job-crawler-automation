# 데이터 모델

SQLite 파일 하나. 경로는 `DATABASE_PATH` 가 정하고 Docker named volume 으로 영속화한다.

실제 스키마는 DB 가 진실이다. 이 문서와 다르면 DB 를 보고 이 문서를 고친다.

## 테이블

### crawlers

셀렉터를 가진 크롤러 정의. 워크플로우로 승격되기 전 단계.

| 컬럼 | 설명 |
|---|---|
| id | |
| name | |
| list_url | 리스트 페이지 URL |
| detail_url | 셀렉터 생성 시 참고한 상세 페이지 URL |
| selectors_json | 생성 또는 수동 보정된 셀렉터 |
| render_mode | `static` 또는 `playwright` |
| status | `draft` / `tested` / `promoted` |
| default_company | 운영자가 적어 둔 회사명. 선택. NULL 이면 안 적은 것 |
| created_at | |

`status` 는 `tested` 를 거쳐야 `promoted` 가 된다. 테스트 없이 워크플로우로 올라가지 않는다.

### workflows

| 컬럼 | 설명 |
|---|---|
| id, crawler_id, name | |
| interval_minutes | 기본은 느리게. 360분이 대부분에 충분하다 |
| status | `active` / `paused` |
| success_count, fail_count | 누적 실행 횟수. 항목 수가 아니다. 화면 배지가 읽는 값 |
| last_run_at | 마지막으로 끝난 실행의 시각 |
| auto_stop_threshold | 연속 실패가 이 값에 닿으면 자동 `paused`. NULL 이면 자동 중지 안 함 |

성공이 아닌 종료는 전부 실패로 센다. `timeout` 도 마찬가지다.

연속 실패 횟수는 컬럼으로 두지 않고 `crawl_runs` 를 마지막부터 거슬러 세어 구한다. 세는 곳과
기록하는 곳이 갈리면 둘이 어긋나고, 어긋난 쪽을 믿을 근거가 없다.

### crawl_runs

실행 1회 = 행 1개. 타임아웃·크래시 포함 **모든 종료 경로에서 기록된다.**

| 컬럼 | 설명 |
|---|---|
| id | |
| workflow_id | 워크플로우 실행이면 채워지고, 승격 전 테스트 실행이면 NULL |
| crawler_id | 승격 전 테스트 실행이면 채워지고, 워크플로우 실행이면 NULL |
| started_at, finished_at | |
| status | `success` / `failed` / `timeout` |
| success_count | 정상 파싱된 항목 수 |
| new_count | 신규로 적재된 수 |
| fail_count | |
| error_class | `transport` / `selector_miss` / `parse` |
| error_message | |

`workflow_id` 와 `crawler_id` 가 둘 다 NULL 인 행은 CHECK 가 막는다. 어느 쪽에도 걸리지 않은
실행은 나중에 누구도 추적하지 못한다.

`error_class` 가 세 가지로 나뉘어 있는 이유는 조치가 각각 다르기 때문이다.
`transport` 만 재시도 대상이다. `.claude/rules/crawling.md` 참조.

### raw_jobs

원본 수집 데이터. **append-only.** 정규화가 이 테이블을 고치지 않는다.

| 컬럼 | 설명 |
|---|---|
| id, workflow_id | |
| source_url | 공고 원문 URL |
| raw_data_json | 셀렉터로 뽑은 필드 그대로. 정제 전 |
| content_hash | 중복 감지용. 아래 참조 |
| crawled_at | |

워크플로우가 없는 테스트 실행은 이 테이블에 적재하지 않는다. 적재할 워크플로우가 없고, 테스트가
원하는 것은 미리보기이지 수집 데이터가 아니다. 그 실행의 `crawl_runs.new_count` 는 0 이다.

원본 HTML 은 저장하지 않는다. 실패 디버깅용 스냅샷만 `debug_snapshots/` 에 보존 기한을 두고
남긴다 (`.claude/rules/data-safety.md`).

### normalized_jobs

| 컬럼 | 설명 |
|---|---|
| id, raw_job_id | |
| company, title, department | |
| company_source | 회사명이 어디서 왔는지. `parsed` / `operator`. 회사명이 없으면 NULL |
| deadline | 정규화된 날짜 |
| body, requirements | 정제된 텍스트 |
| source_url | |
| normalized_at | |
| delivered_at | 소비 측이 가져간 시각. **제공 API 경로만 쓴다** |

`delivered_at` 을 크롤링·재정규화·수동 수정이 건드리면 소비 측에 같은 데이터가 다시 간다.

회사명은 출처가 둘이다. 공고에서 뽑은 값(`raw_jobs.raw_data_json` 의 `company`)과 운영자가
크롤러에 적어 둔 값(`crawlers.default_company`). 사이트 하나에 계열사 공고가 섞여 들어오므로
공고 단위인 파싱값이 이기고, 파싱값이 없을 때만 운영자값을 쓴다. 둘 다 없으면 `company` 와
`company_source` 가 모두 NULL 이다 — 빈 문자열로 채우지 않는다. 합치는 것은 정규화 단계
하나뿐이다.

### job_field_overrides

사람이 검수하며 고친 값. 공고 하나의 필드 하나가 행 하나다.

| 컬럼 | 설명 |
|---|---|
| id | |
| raw_job_id | 어느 수집 건의 보정인지. `normalized_jobs.id` 가 아니다 |
| field_name | `company` / `title` / `department` / `deadline` / `body` / `requirements` |
| value | 사람이 정한 값. 빈 문자열은 "비어 있는 것이 맞다" 는 판단이다 |
| created_at, updated_at | |

`(raw_job_id, field_name)` 이 유일하다. 같은 필드에 보정이 둘이면 어느 쪽이 사람의 뜻인지
알 수 없다.

`normalized_jobs` 행은 재정규화로 다시 만들어지므로 거기에 매달면 보정이 떨어져 나간다.
append-only 인 `raw_jobs` 에 매달아야 몇 번을 다시 정규화해도 보정이 따라붙는다.

고칠 수 있는 필드는 규칙이 만드는 여섯 개뿐이고 CHECK 가 나머지를 막는다. `source_url` 은
공고의 신원이라 고치지 않고, `normalized_at` 과 `delivered_at` 은 아예 받지 않는다.

정규화는 규칙을 먼저 적용하고 그 위에 보정을 덮는다. 규칙을 개선하면 보정하지 않은 필드는
같이 좋아지고, 보정한 필드는 사람이 정한 값을 유지한다. 보정 행을 지우면 다음 정규화에서
규칙이 만든 값으로 돌아간다.

`company_source` 는 규칙 단계가 고른 출처만 말한다. 사람이 고쳤는지는 이 테이블에 행이
있는지로 안다.

### normalization_rules

| 컬럼 | 설명 |
|---|---|
| id, field_name | 적용 대상 필드 |
| rule_type | `mapping` / `regex` / `trim` / `date_parse` |
| rule_config_json | 타입별 설정 |
| priority | 같은 필드에 여러 규칙일 때 적용 순서 |
| enabled | |

규칙 변경은 **이후 신규 데이터부터** 적용된다. 기존 데이터 일괄 재정규화는 별도 동작이고,
`raw_jobs` 를 다시 읽어 `normalized_jobs` 를 갱신한다.

### app_settings

어드민 화면에서 바꾸는 운영 설정. 키-값 한 쌍이다.

| 컬럼 | 설명 |
|---|---|
| key | 설정 키. 지금은 `max_concurrent_runs` 하나 |
| value | 문자열로 저장하고 읽는 쪽이 형으로 바꾼다 |
| updated_at | 마지막 변경 시각 |

값이 아직 없을 때만 환경변수에서 채운다. 한 번 들어간 뒤로는 이 테이블이 진실이고, 환경변수를
나중에 고쳐도 저장된 값을 덮지 않는다. 읽고 쓰는 곳은 `app/settings.py` 하나다.

배포가 정하는 값(`CRAWL_DELAY_SECONDS`, `RUN_TIMEOUT_SECONDS` 등)은 여기로 옮기지 않는다.
같은 설정이 두 곳에 있으면 어느 쪽이 진실인지 매번 확인해야 한다.

## 중복 감지 hash

`content_hash` 에 들어가는 것:

```
source_url + title + deadline + body
```

들어가면 안 되는 것: 조회수, 상대 날짜("3일 전"), 광고 문구, 정렬 순서, 크롤링 시각.
매 크롤마다 값이 달라지는 것이 하나라도 섞이면 같은 공고가 매번 신규로 들어온다.

`db-inspect dupes` 로 중복이 잡히면 여기부터 본다.

## 상태 전이

```
crawler:  draft ──테스트 통과──> tested ──워크플로우 등록──> promoted
workflow: active <──> paused          (수동, 또는 연속 실패 임계치 초과)
job:      raw ──정규화──> normalized ──제공 API 응답──> delivered
```

되돌아가는 화살표는 workflow 하나뿐이다. 데이터는 앞으로만 간다.
