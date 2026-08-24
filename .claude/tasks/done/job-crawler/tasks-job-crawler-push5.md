# Tasks: job-crawler - Push 5

> PRD: `.claude/tasks/todo/prd-job-crawler.md`
> Push 범위: 정규화 — 규칙 타입, 규칙 엔진, 파이프라인 연결, 규칙 CRUD, 일괄 재정규화
> 상태: 완료

## 관련 파일

- `app/normalize/rules.py` - 규칙 타입 정의
- `app/normalize/engine.py` - 규칙 적용
- `app/api/rules.py` - 규칙 CRUD 라우터, 수동 재정규화 트리거
- `app/normalize/backfill.py` - 수동 재정규화 동작
- `app/crawler/runner.py` - 실행 흐름 7단계에서 정규화를 부른다
- `tests/fixtures/` - 원문 값과 기대 정규화 값

## 선행 조건

- Push 3 완료 (`raw_jobs` 에 데이터가 들어와야 정규화할 것이 있다)
- **결정됨 (2026-08-21): 기존 데이터 재정규화는 자동으로 돌지 않는다. 수동 버튼으로만 분리한다.**
  PRD 9장의 미결정 항목이 이 형태로 닫혔다. 규칙을 저장해도 기존 `normalized_jobs` 는 그대로고,
  운영자가 버튼을 눌렀을 때만 `raw_jobs` 를 다시 읽어 갱신한다.
  규칙 저장에 재처리를 묶지 않는다 — 규칙 하나 고칠 때마다 전체 재처리가 도는 것을 막기 위한 결정이다.
  결정 내용을 `.claude/docs/architecture.md` 의 미결정 항목에서 지운다
- 버튼 자체는 Push 6 에서 화면에 붙인다. 이 Push 는 동작과 API 까지다

## 작업

- [x] 5.0 정규화 (Push 범위)

    - [x] 5.1 규칙 타입 정의
        - `mapping` / `regex` / `trim` / `date_parse`. 타입별 `rule_config_json` 스키마를 명시한다
        - 설정이 스키마에 맞지 않는 규칙은 저장 단계에서 거부한다
        - [x] 5.1.V 검증: 픽스처 기반 pytest 작성 및 통과 — 타입별 정상 설정 통과, 잘못된 설정 거부

    - [x] 5.2 규칙 엔진
        - `app/normalize/engine.py`. 같은 필드에 여러 규칙이면 `priority` 순으로 적용하고 `enabled=false` 는 건너뛴다
        - `raw_jobs` 를 읽고 `normalized_jobs` 에만 쓴다. raw 는 어떤 경우에도 수정하지 않는다 (`.claude/rules/data-safety.md`)
        - [x] 5.2.V 검증: 픽스처 기반 pytest 작성 및 통과 — 원문 값 입력 대 정규화 값 출력을 타입별로 단언하고, 실행 후 `raw_jobs` 행이 바이트 단위로 그대로인지 단언

    - [x] 5.3 실행 파이프라인에 연결
        - `raw_jobs` 적재 직후 정규화를 돌려 `normalized_jobs` 에 넣는다 (`.claude/docs/architecture.md` 실행 흐름 7단계)
        - 정규화 실패는 실행 전체를 죽이지 않는다. raw 는 남기고 실패를 기록한다
        - [x] 5.3.V 검증: 픽스처 기반 pytest 작성 및 통과 — 1회 실행 후 `raw_jobs` 1행에 `normalized_jobs` 1행, 규칙이 예외를 던지는 픽스처에서도 raw 는 적재됨

    - [x] 5.4 정규화 규칙 CRUD API
        - 등록·수정·삭제·순서 변경. 변경은 이후 신규 데이터부터 적용된다
        - [x] 5.4.V 검증: 픽스처 기반 pytest 작성 및 통과 — 규칙 추가 후 새로 정규화한 건에는 적용되고 기존 `normalized_jobs` 행은 변하지 않음

    - [x] 5.5 수동 재정규화 동작
        - 운영자가 명시적으로 실행할 때만 도는 별도 동작. 규칙 CRUD 경로에서 부르지 않는다
        - `raw_jobs` 를 다시 읽어 `normalized_jobs` 를 갱신한다. `raw_jobs` 와 `delivered_at` 은 건드리지 않는다
          (`.claude/rules/data-safety.md`)
        - 백그라운드로 돌리고 진행 상황(대상 건수, 처리 건수, 실패 건수)을 조회할 수 있게 한다.
          `crawl_runs` 에 섞어 쓰지 않는다 — 크롤링 실행이 아니다
        - 실행 중 중복 요청은 거부한다. 같은 재정규화가 두 번 돌지 않게 한다
        - [x] 5.5.V 검증: 픽스처 기반 pytest 작성 및 통과 — 규칙을 바꾼 뒤 재정규화하면 값이 새 규칙을 따르고,
          `delivered_at` 과 `raw_jobs.raw_data_json` 은 이전 값 그대로이며, 실행 중 재요청이 거부되는지 단언
