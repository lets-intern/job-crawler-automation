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
| list_mode | 목록을 무엇으로 가져오는가. `static` / `api` / `playwright` |
| detail_mode | 상세를 무엇으로 가져오는가. 같은 세 값 |
| api_config_json | `api` 모드가 쓰는 endpoint·본문·응답 경로. 안 쓰면 NULL |
| status | `draft` / `tested` / `promoted` |
| default_company | 운영자가 적어 둔 회사명. 선택. NULL 이면 안 적은 것 |
| created_at | |

`status` 는 `tested` 를 거쳐야 `promoted` 가 된다. 테스트 없이 워크플로우로 올라가지 않는다.

목록과 상세는 따로 고른다. 섞어 쓰는 것이 정상적인 선택지다 — 목록이 JSON API 로 오고 상세는
브라우저가 있어야 그려지는 사이트가 있다. 두 값을 하나로 합치면 그 사이트를 담을 자리가 없다
(`migrations/0008_collect_modes.sql`).

`api_config_json` 의 형식은 `app/selector/api_schema.py` 가 강제한다. 목록은 `url`, `method`,
`body`, `items_path`, `fields`, `id_field`, `link_template` 을, 상세는 `url`, `method`, `body`,
`fields` 를 갖는다.

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
| fail_count | 실패한 항목 수 |
| skipped_count | 상세를 열지 않고 넘긴 수. 마감이 지났거나 이미 저장한 공고다. 0010 이전 행은 0 |
| error_class | `transport` / `selector_miss` / `parse` / `list_empty` / `detail_unreachable` / `detail_empty` |
| error_message | |
| trigger | 무엇이 실행을 시작했는지. `schedule` / `manual` / `test`. 0007 이전 행은 NULL |

`workflow_id` 와 `crawler_id` 가 둘 다 NULL 인 행은 CHECK 가 막는다. 어느 쪽에도 걸리지 않은
실행은 나중에 누구도 추적하지 못한다.

`skipped_count` 는 `fail_count` 와 따로 센다. 건너뜀은 실패가 아니라 상세를 열 이유가 없어
넘긴 것이고, 둘을 한 숫자로 합치면 마감 날짜 형식이 바뀌어 전부 걸러진 사이트가 "새 공고 0건" 인
정상 실행과 같은 모습이 된다.

`trigger` 는 스케줄러가 깨운 실행(`schedule`), 워크플로우 카드의 지금 1회 실행(`manual`),
승격 전 크롤러의 테스트 실행(`test`)을 가른다. 이것이 없으면 최근 실행이 있어도 주기가 실제로
도는 것인지 사람이 눌러 온 것인지 알 수 없다. NULL 은 기록되기 전의 실행이고 화면에
`알 수 없음` 으로 나온다.

`error_class` 가 여러 값으로 나뉘어 있는 이유는 조치가 각각 다르기 때문이다.
`transport` 만 재시도 대상이다. 뒤의 셋은 공고가 상세에 도달하지 못한 경우를 가른다 — 목록을
못 읽은 것(`list_empty`), 상세로 가지 못한 것(`detail_unreachable`), 갔는데 본문이 빈 것
(`detail_empty`)은 고치는 자리가 다르다. 값의 목록은 `app/crawler/failures.py` 의
`ERROR_CLASSES` 가 갖고 있고 두 CHECK 제약이 그것과 같아야 한다.
`.claude/rules/crawling.md` 참조.

### crawl_run_failures

실행 하나가 놓친 공고를 한 줄씩 남긴다. **수집 데이터가 아니라 실행 기록이다** — `raw_jobs` 와
성격이 다르다.

| 컬럼 | 설명 |
|---|---|
| id | |
| run_id | 어느 실행이 놓쳤는지. `crawl_runs(id)`, `ON DELETE CASCADE` |
| reason | `crawl_runs.error_class` 와 같은 값. 분류하지 못한 실패는 NULL |
| title | 목록에서 읽은 제목 |
| source_url | 목록에서 읽은 주소 |
| message | 실패 내용 |
| created_at | |

건수만으로는 고칠 수 없어서 제목과 목록에서 읽은 주소까지 남긴다. 조회는 실행 하나의 실패를
모아 보는 것 하나뿐이라 `run_id` 에만 인덱스(`idx_crawl_run_failures_run_id`)를 건다.

보관 기한을 따로 두지 않는다. 실행 기록이 지워지면 같이 지워진다. 실패 목록은 그 실행을
설명하는 것이지 혼자 남아 뜻이 있는 기록이 아니다.

### raw_jobs

원본 수집 데이터. **append-only.** 정규화가 이 테이블을 고치지 않는다.

| 컬럼 | 설명 |
|---|---|
| id, workflow_id | |
| source_url | 공고 원문 URL |
| raw_data_json | 셀렉터로 뽑은 필드 그대로. 정제 전. 상세 원문을 뽑았으면 `source_text` 키가 함께 있다 |
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
| deadline | 정규화된 모집 마감일 |
| start_date | 정규화된 모집 시작일. `deadline` 의 짝이다 |
| job_category | 직군 |
| employment_type | 고용형태. 정규직 / 인턴 / 기간제 |
| career_level | 경력 구분. 신입 / 경력 |
| work_location | 근무지 |
| headcount | 모집인원 |
| job_role | 직무. 제목에서 뽑는 자유 텍스트다. 닫힌 목록이 아니다 |
| duties | 주요 업무 |
| preferred | 우대 조건 |
| hiring_process | 전형 절차 |
| etc_info | 기타 |
| body, requirements | 정제된 텍스트 |
| source_url | |
| normalized_at | |
| delivered_at | 소비 측이 가져간 시각. **제공 API 경로만 쓴다** |

`start_date` 부터 `etc_info` 까지 열 칸은 0011 이 더했다. 여섯 칸에 담느라 사이트가 이미
나눠서 주는 것을 도로 합치고 있었고, 빈 칸을 채우려다 한화 `department` 에 근무지가 들어갔다.

더할 칸은 **열한 사이트 응답을 대조해 넷 이상이 주는 것만** 골랐다. 한 사이트만 가진 값을 칸으로
만들면 나머지 열 곳이 비는 칸이 하나 는다. 어느 사이트의 어느 자리가 어느 칸인지는
`tests/test_split_body_columns.py` 가 픽스처로 들고 있다.

**사이트가 주지 않는 칸은 NULL 이다.** 없는 값을 다른 값으로 채우지 않는다. 빈 칸은 "이
사이트는 이 값을 주지 않는다" 는 사실이고, 틀린 값은 소비 측이 그대로 노출한다.

`department` 는 둘(LG·현대)만 주는 칸이라 새 기준이었다면 만들지 않았을 것이다. **이미 있는
칸이라 지우지 않는다** — 소비 측이 읽던 것이 사라지면 안 된다.

`job_category` 부터 `etc_info` 까지와 `requirements`·`department` 열한 칸은 이제 대부분
`job_classifications` 에서 온다. 수집이 그 칸을 별도 필드로 주는 사이트는 그 값이 이기고,
없으면 본문을 나눈 결과가 들어간다.

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

고칠 수 있는 필드는 위 여섯 개뿐이고 CHECK 가 나머지를 막는다. `source_url` 은 공고의
신원이라 고치지 않고, `normalized_at` 과 `delivered_at` 은 아예 받지 않는다.

0011 이 더한 열 칸은 여기 들어오지 않는다. 이 컬럼이 `UNIQUE (raw_job_id, field_name)` 의
인덱스에 걸려 있어 0009·0010 이 쓴 CHECK 넓히기(새 컬럼 추가 -> 값 이동 -> 옛 컬럼 삭제)가
통하지 않는다 — SQLite 는 인덱스가 걸린 컬럼을 DROP 하지 못한다. 새 칸의 손보정이 필요해지면
그때 따로 다룬다.

정규화는 규칙을 먼저 적용하고 그 위에 보정을 덮는다. 규칙을 개선하면 보정하지 않은 필드는
같이 좋아지고, 보정한 필드는 사람이 정한 값을 유지한다. 보정 행을 지우면 다음 정규화에서
규칙이 만든 값으로 돌아간다.

`company_source` 는 규칙 단계가 고른 출처만 말한다. 사람이 고쳤는지는 이 테이블에 행이
있는지로 안다.

### job_classifications

본문을 나눈 결과. 공고 하나가 행 하나다.

| 컬럼 | 설명 |
|---|---|
| id | |
| raw_job_id | 어느 수집 건의 분류인지. `normalized_jobs.id` 가 아니다. 유일하다 |
| job_category, work_location, career_level, employment_type, headcount | |
| duties, preferred, hiring_process, requirements, department, etc_info | |
| job_role | 0017 이 더했다. 값이 본문이 아니라 제목에서 온다 |
| dropped_fields | 모델이 냈지만 근거가 없어 버린 칸 이름. 쉼표로 잇는다 |
| evidence_json | 판정 칸을 그렇게 고른 근거 문장. `{"career_level": "본문 문장"}` |
| model | 그때의 모델 ID |
| classified_at | |

수집은 어느 사이트나 확실히 주는 여섯(제목·본문·모집 시작일·모집 마감일·회사명·원본 주소)만
하고, 나머지 열한 칸은 본문을 읽어 나눈다. 사이트마다 칸 매핑을 적는 방식은 열한 사이트
640건에서 절반도 채우지 못했다 (`.claude/tasks/memos/보류/llm-classify/prd-llm-classify.md`).

**`normalized_jobs` 에 바로 쓰지 않는 이유가 있다.** 그 표는 `raw_jobs` 에서 규칙으로 다시
만들어진다. 재정규화를 한 번 돌리면 분류가 채운 칸이 통째로 NULL 로 돌아가고, 되살리려면
공고 수만큼 모델을 다시 불러야 한다. 그래서 `job_field_overrides` 와 같이 append-only 인
`raw_jobs` 에 매단다.

정규화는 **규칙 -> 분류 -> 사람 보정** 순으로 덮는다. 분류가 있으면 그 열한 칸은 전부 분류
값이다 — 규칙이 만든 값이 있어도 덮고, 분류가 빈 칸을 냈으면 빈 칸이 된다. 칸의 출처가 하나여야
소비 측이 한 가지 규칙으로 읽는다 (2026-08-26 결정).

빈 칸까지 덮는 것이 핵심이다. 채워진 칸만 덮으면 2026-08-26 이전에 수집된 행에 옛 매핑이 넣어
둔 값(`IT - 구축/운영/최적화`, `Permanent`)이 남고, 판정 칸 셋의 닫힌 목록이 640건에 대해
성립하지 않는다 (`.claude/docs/api-contract.md`).

수집이 주는 여섯 칸(`title` `body` `company` `deadline` `start_date` `source_url`)은 분류가
건드리지 않는다. 분류가 없는 공고는 규칙이 만든 값을 그대로 유지한다. 분류가 낸 값에는 규칙을
태우지 않는다.

**분류하지 못한 공고는 행이 없다.** 빈 행을 넣으면 "분류했는데 아무것도 안 나왔다" 와 "아직
분류하지 않았다" 가 같은 모양이 되고, 다음 실행이 어느 쪽을 다시 돌아야 할지 모른다.

칸이 두 가지다. **뽑는 칸** 여덟(`duties` `requirements` `preferred` `hiring_process`
`work_location` `headcount` `department` `etc_info`)은 본문 글자를 그대로 옮기고, 값이
본문에 없으면 버린다. **판정 칸** 셋(`job_category` `employment_type` `career_level`)은
본문을 읽고 닫힌 목록에서 고른다 — `백엔드 개발자 채용` 어디에도 "직군: 개발" 이라고 적혀
있지 않아서 글자 일치를 요구하면 이 셋은 영원히 빈다.

판정 칸의 목록은 응답 스키마의 enum 이 강제하고, 목록과 그 근거는
`.claude/tasks/memos/보류/llm-classify/tasks-llm-classify.md` 에 있다. 목록을 정하지 않으면 같은 일이 사이트마다
다른 이름으로 쌓인다 — 이 표가 생기기 전 640건에 `Permanent` 71건과 `정규직` 7건과 `정규`
3건이 따로 있었다.

판정 칸에는 근거 문장이 따라온다. 그 문장이 본문에 없으면 읽고 고른 것이 아니라 지어낸
것이라 판정을 버린다.

`dropped_fields` 는 셈을 위한 것이다. 모델이 무엇을 얼마나 지어내는지는 세어 봐야 알고,
세지 않으면 프롬프트를 고쳐도 나아졌는지 말할 수 없다. 값이 본문에 있는지 보는 잣대는
`app/classify/grounding.py` 가 정한다.

다시 분류하면 같은 행을 덮는다. 이력을 쌓지 않는 것은 본문이 `raw_jobs` 에 그대로 있어
언제든 다시 만들 수 있기 때문이다.

### normalization_rules

| 컬럼 | 설명 |
|---|---|
| id, field_name | 적용 대상 필드 |
| rule_type | `mapping` / `regex` / `trim` / `date_parse` / `html_text` |
| rule_config_json | 타입별 설정 |
| priority | 같은 필드에 여러 규칙일 때 적용 순서 |
| enabled | |

`html_text` 는 HTML 조각을 평문으로 편다. 설정이 없고, 블록 태그는 줄바꿈이 되고 나머지
태그는 사라지고 엔티티는 원래 글자로 돌아온다. 값에 태그도 엔티티도 없으면 손대지 않는다.
어디서 줄이 바뀌는지는 `app/crawler/parser.py` 의 `BLOCK_TAGS` 하나가 정한다. API 가 본문을
HTML 로 주는 사이트(LG)를 위한 것이고, 수집 단계에서 태그를 지우지 않으므로 `raw_jobs` 는
원본으로 남는다.

규칙 변경은 **이후 신규 데이터부터** 적용된다. 기존 데이터 일괄 재정규화는 별도 동작이고,
`raw_jobs` 를 다시 읽어 `normalized_jobs` 를 갱신한다.

### llm_calls

모델 호출 1회 = 행 1개. **수집 데이터가 아니라 실행 기록이다.**

| 컬럼 | 설명 |
|---|---|
| id | |
| provider | 지금은 `gemini` 하나 |
| model | 그때의 모델 ID. `GEMINI_MODEL` 이 정하고 바뀐다 |
| feature | `selector_generate` / `selector_repair` / `classify` |
| input_tokens, output_tokens, total_tokens | 비용 |
| latency_ms | |
| ok | 성공이면 1. 실패한 호출도 남긴다 |
| error | 실패 사유. 성공이면 빈 문자열 |
| called_at | |

지금까지 비싼 호출은 셀렉터 생성뿐이라 로그 줄 하나로 충분했다. 본문 분류는 **공고마다 하나씩
붙는다** — 로그 파일은 컨테이너를 다시 띄우면 사라지고, "이번 달에 얼마나 썼나" 는 세어야
답할 수 있는 질문이다 (`.claude/rules/llm.md`).

프롬프트도 응답 본문도 담지 않는다. 남길 이유가 비용을 세는 것뿐인데 본문을 넣으면 이 표
안에 사이트 본문이 한 벌 더 생긴다.

실패한 호출도 토큰을 쓴다. 빼고 세면 합이 실제와 어긋나므로 `ok=0` 으로 같이 남긴다.

**기록 실패는 호출 실패가 아니다.** 표가 없거나 DB 가 잠겨 있어도 분류는 계속 간다. 못 남긴
사실은 경고 로그로 남는다 (`app/llm/log.py`).

조회는 기간별 합과 기능별 합 둘이라 `called_at` 에만 인덱스(`idx_llm_calls_called_at`)를
건다. `feature` 는 값이 셋뿐이라 인덱스가 도움이 되지 않는다.

### app_settings

어드민 화면에서 바꾸는 운영 설정. 키-값 한 쌍이다.

| 컬럼 | 설명 |
|---|---|
| key | 설정 키. 아래 두 묶음이 이 표를 같이 쓴다 |
| value | 문자열로 저장하고 읽는 쪽이 형으로 바꾼다 |
| updated_at | 마지막 변경 시각 |

읽고 쓰는 곳이 둘이고, 키로 갈린다. 표는 하나다 — 설정이 늘어도 새 표를 만들지 않는다.

| 키 | 읽고 쓰는 곳 | 환경변수 짝 |
|---|---|---|
| `max_concurrent_runs` | `app/settings.py` | `MAX_CONCURRENT_RUNS` 가 초기값 |
| `ntfy_enabled`, `ntfy_server_url`, `ntfy_topic`, `ntfy_priority`, `ntfy_min_new_count`, `ntfy_click_base` | `app/notify/settings.py` | 없음 |

동시 실행 상한은 값이 아직 없을 때만 환경변수에서 채운다. 한 번 들어간 뒤로는 이 테이블이
진실이고, 환경변수를 나중에 고쳐도 저장된 값을 덮지 않는다.

알림 설정에는 환경변수 짝이 없다. 배포가 정할 값이 아니라 운영자가 화면에서 정하는 값이고,
짝을 만들면 같은 설정이 두 곳에 생긴다. 저장된 값이 없으면 코드의 기본값을 쓰고, 읽기는
저장을 하지 않는다 — 지킬 환경변수가 없어서 미리 얼려 둘 이유가 없다.

읽는 쪽을 나눈 이유는 값의 모양이다. `app/settings.py` 는 정수 하나를 다루고 `/api/settings`
가 `dict[str, int]` 로 내보내는데, 알림 값은 켜기·끄기와 주소와 낱말이 섞여 있다.

알림 설정을 읽는 자리는 크롤링 실행의 끝이다(`app/notify/new_jobs.py`). 그래서 읽기는 예외를
던지지 않는다 — 손으로 넣은 깨진 값 하나가 수집을 멈추게 두지 않고, 기본값으로 떨어뜨린 뒤
로그에 남긴다. 쓰기는 반대로 전부 검증을 지난다.

배포가 정하는 값(`CRAWL_DELAY_SECONDS`, `RUN_TIMEOUT_SECONDS` 등)은 여기로 옮기지 않는다.
같은 설정이 두 곳에 있으면 어느 쪽이 진실인지 매번 확인해야 한다.

## 중복 감지 hash

`content_hash` 에 들어가는 것:

```
source_url + title + deadline + body
```

들어가면 안 되는 것: 조회수, 상대 날짜("3일 전"), 광고 문구, 정렬 순서, 크롤링 시각.
매 크롤마다 값이 달라지는 것이 하나라도 섞이면 같은 공고가 매번 신규로 들어온다.

**상세 원문(`raw_data_json.source_text`)도 들어가지 않는다.** 원문은 본문 밖의 지원 버튼·공유
문구·상태 표시까지 담아서, 배너 하나만 바뀌어도 같은 공고가 신규가 된다. 원문은 분류가 읽는
입력이지 공고를 가르는 기준이 아니다.

`db-inspect dupes` 로 중복이 잡히면 여기부터 본다.

## 상태 전이

```
crawler:  draft ──테스트 통과──> tested ──워크플로우 등록──> promoted
workflow: active <──> paused          (수동, 또는 연속 실패 임계치 초과)
job:      raw ──분류(본문)──> classified ──정규화──> normalized ──제공 API 응답──> delivered
```

되돌아가는 화살표는 workflow 하나뿐이다. 데이터는 앞으로만 간다.

## 데이터 파일 가져오기

다른 서버에서 쓰던 SQLite 파일을 운영 설정 화면에서 올려 기존 데이터에 더한다. 배포된 서버는
빈 DB 로 시작하므로, 로컬에 쌓인 수집 데이터를 옮길 길이 화면에 없으면 `docker cp` 밖에 남지
않는다. 구현은 `app/api/import_data.py` 다.

**더하기만 한다.** 기존 행을 고치는 문장은 이 경로에 없다. 없는 것만 넣고, 있는 것은 건너뛴
건수로 보고한다.

| 테이블 | 가져오는가 | 같은 것으로 보는 기준 |
|---|---|---|
| crawlers | 가져온다. 셀렉터·렌더 방식·상태·기본 회사명까지 | 이름 + 리스트 URL |
| workflows | 가져온다. 주기·상태·자동 중지 임계치까지 | 크롤러 + 이름 |
| normalization_rules | 가져온다 | field_name + rule_type + rule_config_json + priority |
| raw_jobs | 가져온다 | 워크플로우 + content_hash |
| job_field_overrides | 가져온다 | 공고 + 필드명 |
| normalized_jobs | 가져오지 않는다. 이 서버 규칙으로 다시 만든다 | |
| crawl_runs | 가져오지 않는다. 저쪽 서버의 실행 기록이다 | |

`workflows` 의 `success_count`, `fail_count`, `last_run_at` 도 실행 기록이라 가져오지 않는다.
이 서버에서는 0 에서 시작한다.

`delivered_at` 은 가져오지 않는다. 저쪽에서 전달된 행이라도 이 서버의 소비 측은 받은 적이
없고, 표시를 들여오면 그 공고는 영영 전달되지 않는다.

`content_hash` 는 파일에 적힌 값을 믿지 않고 `raw_data_json` 에서 다시 계산한다. 이 서버가
이미 가진 행과 같은 잣대로 비교되어야 중복 판정이 성립한다.

id 는 다시 매긴다. 올린 파일의 id 를 그대로 쓰면 기존 행과 부딪힌다.

전부 한 트랜잭션이다. 중간에 틀어지면 아무것도 들어가지 않는다. 다만 공고 한 건의 정규화
실패는 되돌리기 사유가 아니다 — `raw_jobs` 는 남고 규칙을 고쳐 재정규화하면 복구된다.

올라온 파일은 손대기 전에 검증한다. SQLite 인가, 읽을 테이블과 컬럼이 있는가, 마이그레이션
버전이 이 서버보다 앞서지 않는가, 크기가 상한(64MB) 안인가. 앞선 버전은 거절한다 — 이 서버가
모르는 컬럼은 읽을 수 없다.
