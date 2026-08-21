# Tasks: job-crawler - Push 4

> PRD: `.claude/tasks/todo/prd-job-crawler.md`
> Push 범위: 워크플로우 — 승격, APScheduler 등록, 운영 설정 저장소, 동시성 상한, 실행 타임아웃, 실패 임계치 자동 중지
> 상태: 진행 중

## 관련 파일

- `app/scheduler.py` - APScheduler 등록·갱신·동시성 상한
- `app/settings.py` - DB 에 저장되는 운영 설정 읽기·쓰기
- `app/api/workflows.py` - 워크플로우 CRUD 라우터
- `app/crawler/runner.py` - 스케줄러가 부르는 실행 진입점
- `app/main.py` - 기동 시 `workflows` 테이블에서 잡 등록
- `migrations/` - `app_settings` 테이블 추가 마이그레이션

## 선행 조건

- Push 3 완료 (1회 실행이 되어야 스케줄링할 것이 있다)
- **결정됨 (2026-08-21): 동시 실행 상한은 고정값이 아니라 어드민 화면에서 바꾸는 운영 설정이다.**
  PRD 9장의 미결정 항목이 이 형태로 닫혔다. `.env` 의 `MAX_CONCURRENT_RUNS` 는 최초 기동 시
  넣어 주는 초기값일 뿐이고, 이후로는 DB 에 저장된 값이 진실이다.
  값이 바뀌면 프로세스 재시작 없이 반영돼야 한다. 결정 내용을 `.claude/docs/architecture.md` 의
  미결정 항목에서 지우고 이 내용으로 대체한다
- 설정 화면 자체는 Push 6 에서 만든다. 이 Push 는 저장소와 API 까지다

## 작업

- [ ] 4.0 워크플로우 (Push 범위)

    - [x] 4.1 워크플로우 승격
        - `crawlers.status=tested` 인 것만 승격한다. 이름과 주기를 받아 `workflows` 행을 만들고 `promoted` 로 바꾼다
        - 테스트를 거치지 않은 크롤러의 승격 요청은 거부한다
        - [x] 4.1.V 검증: 픽스처 기반 pytest 작성 및 통과 — `draft` 승격 거부, `tested` 승격 성공 후 상태가 `promoted`

    - [x] 4.2 스케줄러 등록과 갱신
        - `app/scheduler.py`. 기동 시 `workflows` 에서 `active` 인 것을 전부 등록한다
        - 주기·상태가 바뀌면 잡을 갱신한다. 테이블이 진실이고 스케줄러 메모리가 아니다 (`.claude/rules/crawling.md`)
        - [x] 4.2.V 검증: 짧은 주기로 등록해 2회 실행 확인 후 원복.
          대상 URL 은 로컬 픽스처를 서빙하는 주소로 둔다. 실사이트를 주기 실행에 걸지 않는다

    - [x] 4.3 운영 설정 저장소
        - `app_settings` 테이블 마이그레이션(키, 값, 수정 시각)과 `app/settings.py`
        - 최초 기동 시 값이 없으면 환경변수에서 채우고, 이후에는 DB 값이 이긴다
        - 조회·변경 API. 변경 시 검증한다 — 동시 실행 상한은 1 이상의 정수만 받는다
        - 키를 남발하지 않는다. 이번에 넣는 것은 동시 실행 상한 하나다 (`.claude/rules/core.md` 단순함 우선)
        - [x] 4.3.V 검증: 마이그레이션 적용·역적용 확인, 그리고 픽스처 기반 pytest — 값이 없을 때 환경변수 기본값이 들어가고, 변경 후에는 DB 값이 읽히며, 0 과 음수는 거부되는지 단언
        - [x] 4.3.1 (수정) `tests/test_migrations.py::test_down_keeps_workflow_runs_and_drops_test_runs` 가
          `steps=1` 로 0002 를 되돌리는 것을 전제하고 있어 0003 추가로 깨졌다.
          되돌릴 단계 수를 마이그레이션 개수에서 계산하도록 고쳤다

    - [x] 4.4 동시성 상한과 중복 실행 스킵
        - 전역 세마포어 하나로 동시 실행을 제한한다. 상한값은 4.3 의 설정에서 읽는다
        - 설정이 바뀌면 재시작 없이 반영한다. 진행 중인 실행을 죽이지 않고, 다음 획득부터 새 상한을 적용한다
        - 앞 실행이 끝나지 않은 채 다음 tick 이 오면 건너뛰고, 건너뛴 사실을 로그로 남긴다
        - [x] 4.4.V 검증: 짧은 주기로 워크플로우 2개를 로컬 픽스처 주소에 등록해 상한 초과분이 대기하는지와 스킵 로그가 남는지 확인하고, 실행 중에 상한을 바꿔 다음 실행부터 반영되는지 확인 후 원복
        - [x] 4.4.1 (수정) 스킵 로그가 운영에서 나지 않았다. `EVENT_JOB_MAX_INSTANCES` 는
          `JobExecutionEvent` 가 아니라 `JobSubmissionEvent` 로 오고 시각 필드도
          `scheduled_run_times` (복수)다. 리스너가 AttributeError 로 죽어 스킵이 기록되지
          않았다. 리스너와 테스트를 실제 사건 타입으로 고쳤다

    - [ ] 4.5 실행 타임아웃
        - 모든 실행을 `RUN_TIMEOUT_SECONDS` 로 감싼다. 죽어도 `crawl_runs` 행은 `status=timeout` 으로 남는다
        - [ ] 4.5.V 검증: 픽스처 기반 pytest 작성 및 통과 — 응답을 지연시키는 스텁으로 실행해 `crawl_runs` 에 `timeout` 행이 남는지 확인

    - [ ] 4.6 실패 임계치와 자동 중지
        - 실행 결과로 `success_count`·`fail_count`·`last_run_at` 을 갱신한다
        - 연속 실패가 `auto_stop_threshold` 를 넘으면 `paused` 로 바꾼다. NULL 이면 자동 중지하지 않는다
        - [ ] 4.6.V 검증: 픽스처 기반 pytest 작성 및 통과 — 임계치 3에서 연속 3회 실패 후 `paused`, 중간에 성공이 끼면 유지

    - [ ] 4.7 워크플로우 CRUD API
        - 목록(이름, 대상, 주기, 최근 실행, 누적 성공·실패), 주기 변경, 수동 중지·재개
        - 상태 변경은 스케줄러 잡 갱신까지 이어져야 한다
        - [ ] 4.7.V 검증: 픽스처 기반 pytest 작성 및 통과 — 주기 변경 후 등록된 잡의 주기가 바뀌고, `paused` 로 바꾸면 잡이 사라지는지 확인
