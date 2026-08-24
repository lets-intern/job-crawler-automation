# 결과보고서: tasks-job-crawler-push5.md

> 완료일: 2026-08-22
> Push 범위: 정규화 — 규칙 타입, 규칙 엔진, 파이프라인 연결, 규칙 CRUD, 수동 재정규화
> 브랜치: `feat/job-crawler-pipeline` (푸시하지 않음)

## 구현 요약

| 작업 | 상태 | 커밋 |
|---|---|---|
| 5.1 규칙 타입 정의 | 완료 | `caacf84` |
| 5.2 규칙 엔진 | 완료 | `b81384b` |
| 5.3 실행 파이프라인에 연결 | 완료 | `a6cfce7` |
| 5.4 정규화 규칙 CRUD API | 완료 | `519c028` |
| 5.5 수동 재정규화 동작 | 완료 | `da791f3` |
| 결정 사항 문서 반영 | 완료 | `a2685a8` |

마이그레이션은 추가하지 않았다. 기존 `normalization_rules` 로 충분하다.

## 생성·수정 파일

- `app/normalize/rules.py` - `mapping` / `regex` / `trim` / `date_parse` 타입과 설정 스키마
- `app/normalize/engine.py` - `priority` 순 적용. `raw_jobs` 는 SELECT 만 한다
- `app/normalize/backfill.py` - 수동 재정규화. 규칙 CRUD 경로에서 부르지 않는다
- `app/api/rules.py` - 규칙 CRUD 와 재정규화 트리거
- `app/crawler/runner.py` - 실행 흐름에 정규화 단계 연결
- `tests/test_normalize_rules.py`, `test_normalize_engine.py`, `test_normalize_pipeline.py`,
  `test_api_rules.py`, `test_normalize_backfill.py`

## 검증 결과

| 대상 | 검증 | 결과 |
|---|---|---|
| 규칙 타입 | 픽스처 pytest | 타입별 정상 설정 통과, 잘못된 설정 거부 (35건) |
| 규칙 엔진 | 픽스처 pytest | 원문 값 대 정규화 값 단언, raw 무변경 단언 (19건) |
| 파이프라인 | 픽스처 pytest | raw 1행에 normalized 1행. 규칙이 예외를 던져도 raw 는 적재됨 (6건) |
| 규칙 CRUD | 픽스처 pytest | 규칙 변경이 기존 `normalized_jobs` 를 건드리지 않음 (13건) |
| 재정규화 | 픽스처 pytest | 새 규칙 반영, `delivered_at` 보존, 중복 요청 거부 (10건) |

Push 단위 검사: `pytest -m "not live"` 288건 통과, ruff·mypy 55파일 무오류. 실사이트 요청 0건.

### raw 무변경을 어떻게 단언했나

`raw_snabshot()` 이 `raw_jobs` 전 행의 전 컬럼을 구분자로 이어 붙여 SHA-256 을 낸다.
성공 경로 2회와 규칙이 예외를 던지는 실패 경로 1회를 태운 뒤 해시 동일,
`raw_data_json` 이 UTF-8 바이트 수준으로 원래 값과 동일, 행 수 유지를 단언한다.
재정규화 경로에도 같은 해시 비교를 건다.

코드 쪽 보장은 `app/normalize/engine.py` 에서 `raw_jobs` 를 향하는 SQL 이 SELECT 하나뿐이라는 점이다.

### delivered_at 보존을 어떻게 단언했나

`backfill.py` 의 UPDATE 는 규칙이 만드는 여섯 컬럼과 `normalized_at` 만 적는다.
`delivered_at` 은 SET 목록에 없다.

테스트는 제공 API 를 흉내내 1번 행에 `delivered_at` 을 넣고, `trim` 규칙을 추가해 재정규화한 뒤
1번 행의 값이 그대로이고 2번 행은 NULL 임을 단언한다. 같은 테스트에서 `title` 의 개행이 실제로
사라진 것도 확인해 "값이 안 바뀌어서 `delivered_at` 도 그대로" 인 허수 통과를 배제했다.

재정규화가 `crawl_runs` 를 한 행도 건드리지 않는 것과, 규칙 등록·수정·순서변경·삭제 후
`normalized_jobs` 가 `normalized_at` 까지 동일한 것도 각각 단언한다.

## 설계 결정

- `date_parse` 가 못 읽는 값은 예외로 처리해 그 건을 `normalized_jobs` 에 넣지 않는다.
  "상시채용" 같은 값이 `deadline` 컬럼에 날짜인 척 들어가는 것을 막는 쪽을 택했다.
  그런 사이트는 앞 순번 `mapping` 규칙으로 거른다. raw 가 남으므로 규칙을 고친 뒤 재정규화로 복구된다
- 빈 값에는 규칙을 적용하지 않고 NULL 로 둔다. 값이 없는 사실이 규칙 실패로 둔갑하지 않게 한다
- 재정규화 진행 상황은 메모리에 둔다. 단일 프로세스 전제이고 작업이 프로세스 수명을 넘지 않는다.
  이력 조회가 필요해지면 그때 테이블이 필요하다

## 남은 일 (이 Push 범위 밖)

- **`normalized_jobs.company` 가 항상 NULL 이다.** 셀렉터 스키마에 `company` 필드가 없어 어떤
  셀렉터도 이 값을 뽑지 않고, 규칙만으로는 만들 수 없다. 그런데 `.claude/docs/api-contract.md` 의
  응답에는 `company` 가 들어 있다. 셀렉터 스키마 변경이 필요한 사안이라 결정이 필요하다
- 정규화 실패는 `crawl_runs.fail_count` 에만 반영되고 `error_message` 에는 남지 않는다.
  화면에서 사유를 보려면 `RunResult.failures` 를 노출해야 한다
