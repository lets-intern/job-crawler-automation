# 결과보고서: tasks-job-crawler-push4.md

> 완료일: 2026-08-22
> Push 범위: 워크플로우 — 승격, APScheduler 등록, 운영 설정 저장소, 동시성 상한, 실행 타임아웃, 실패 임계치 자동 중지
> 브랜치: `feat/job-crawler-pipeline` (푸시하지 않음)

## 구현 요약

| 작업 | 상태 | 커밋 |
|---|---|---|
| 4.1 워크플로우 승격 | 완료 | `ce56ecb` |
| 4.2 스케줄러 등록과 갱신 | 완료 | `6057759` |
| 4.3 운영 설정 저장소 | 완료 | `63e393c` |
| 4.4 동시성 상한과 중복 실행 스킵 | 완료 | `4334a7f` |
| 4.5 실행 타임아웃 | 완료 | `bc4d6c2` |
| 4.6 실패 임계치와 자동 중지 | 완료 | `618e1bf` |
| 4.7 워크플로우 CRUD API | 완료 | `81c9a8e` |

17개 파일, 2,200줄 추가.

## 생성·수정 파일

- `app/scheduler.py` - `workflows` 테이블 기준 잡 등록·갱신, 실행 게이트, 스킵 로깅
- `app/settings.py` - DB 에 저장되는 운영 설정. 없으면 환경변수에서 채우고 이후 DB 값이 이긴다
- `app/api/settings.py` - 설정 조회·변경. 동시 실행 상한은 1 이상의 정수만 받는다
- `app/api/workflows.py` - 승격, 목록, 주기 변경, 중지·재개
- `app/crawler/runner.py` - 워크플로우 실행 진입점, 타임아웃, 누적값 갱신, 자동 중지
- `migrations/0003_app_settings.sql`
- `tests/test_scheduler.py`, `test_run_gate.py`, `test_settings.py`, `test_run_timeout.py`,
  `test_auto_stop.py`, `test_api_workflows.py`, `test_workflow_run.py`

## 검증 결과

| 대상 | 검증 | 결과 |
|---|---|---|
| 승격 | 픽스처 pytest | `draft`·`promoted` 승격 거부(409), `tested` 승격 후 `promoted` (6건) |
| 스케줄러 | 짧은 주기 2회 실행 | 아래 표 |
| 스키마 | 마이그레이션 적용·역적용 | 0003 up/down 실행 확인 (12건) |
| 동시성 | 짧은 주기 2개 등록 | 아래 표 |
| 타임아웃 | 픽스처 pytest | 지연 스텁으로 `crawl_runs.status=timeout` 확인 (5건) |
| 자동 중지 | 픽스처 pytest | 임계치 3에서 3연속 실패 후 `paused`, 중간 성공 시 유지 (6건) |
| CRUD API | 픽스처 pytest | 주기 변경 시 잡 주기 변경, `paused` 시 잡 소멸 (11건) |

Push 단위 검사: `pytest -m "not live"` 205건 통과, ruff 통과, mypy 45파일 무오류.
실사이트 요청 0건. 주기 실행 검증은 전부 로컬 픽스처 서버로 돌렸다.

### 4.2.V 주기 실행

1분 주기 워크플로우 1개, 로컬 픽스처 서버 대상.

| 실행 | status | success | new | 시각 |
|---|---|---|---|---|
| 1회차 | success | 25 | 25 | 15:35:22 |
| 2회차 | success | 25 | 0 | 15:36:22 |

정확히 60초 간격이고 `raw_jobs` 는 25행이다. 2회차 `new=0` 이 중복 감지가 동작함을 같이 보여준다.

### 4.4.V 상한 변경이 재시작 없이 반영됨

응답을 1.5초 지연시키는 픽스처 서버, 1분 주기 워크플로우 2개, 초기 상한 1.

```
[  60.4s] 상한(1)에 걸려 대기. 진행 중=1
[ 100.4s] 상한 변경 1 -> 2 (진행 중=1, 게이트가 읽는 값=2)
[ 120.3s] workflow 2: 앞 실행이 끝나지 않아 이번 tick 건너뜀
```

상한 변경 전 최대 동시 실행 1, 변경 후 2. 프로세스를 재시작하지 않았고 진행 중이던 실행은
끊기지 않았으며 다음 획득부터 새 상한이 적용됐다.

## 실행 중 발견한 버그

4.4.1 로 기록. **중복 실행 스킵이 전혀 기록되지 않고 있었다.**

APScheduler 의 `EVENT_JOB_MAX_INSTANCES` 는 `JobExecutionEvent` 가 아니라 `JobSubmissionEvent` 로
오고, 시각 필드도 `scheduled_run_time` 이 아니라 복수형 `scheduled_run_times` 다. 리스너가
`AttributeError` 로 죽어 스킵 로그가 하나도 남지 않았다.

단위 테스트가 잘못된 이벤트 타입을 직접 만들어 통과하고 있었던 것이 이것을 가린 원인이다.
리스너와 테스트를 실제 사건 타입으로 함께 고쳤다. 실제 주기 실행 검증(4.4.V)이 아니었으면
발견되지 않았을 종류의 결함이다.

## 설계 결정

- 동시 실행 상한은 `asyncio.Semaphore` 가 아니라 획득 시점에 값을 다시 읽는 게이트로 구현했다.
  세마포어는 크기가 생성 시 고정이라 값이 바뀔 때마다 다시 만들어야 하고, 그 순간 진행 중
  카운트를 잃는다
- 연속 실패 횟수는 컬럼을 늘리지 않고 `crawl_runs` 를 거슬러 세어 구한다
- `workflows.success_count`·`fail_count` 는 항목 수가 아니라 실행 횟수로 정의하고
  `.claude/docs/data-model.md` 에 명시했다
- `.claude/docs/architecture.md` 의 미결정 항목 "동시 실행 상한값" 을 결정 내용으로 대체하고
  PRD 9장도 갱신했다

## 남은 일 (이 Push 범위 밖)

- 테스트 실행(`POST /api/crawlers/{id}/test-run`) 경로에는 `RUN_TIMEOUT_SECONDS` 를 걸지 않았다.
  4.5 의 범위가 워크플로우 실행이고 테스트 실행은 `limit` 으로 항목 수가 묶여 있어 그대로 뒀다.
  죽은 사이트를 상대로는 fetch 타임아웃까지만 매달린다
- 밖에서 온 취소로 끊긴 실행은 `crawl_runs` 행은 남지만 `workflows` 누적값에는 반영되지 않는다.
  연속 실패 판정은 `crawl_runs` 를 보므로 자동 중지에는 영향이 없다
