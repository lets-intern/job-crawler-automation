# 결과보고서: tasks-job-crawler-push7.md

> 완료일: 2026-08-22
> Push 범위: 회사명 해결 — 운영자 입력값과 파싱값을 따로 저장하고 정규화 단계에서 하나로 정한다
> 브랜치: `feat/job-crawler-pipeline` (푸시하지 않음)

## 구현 요약

| 작업 | 상태 | 커밋 |
|---|---|---|
| 7.1 스키마와 운영자 입력 | 완료 | `834ae61` |
| 7.2 셀렉터의 company 선택 필드 | 완료 | `415e453` |
| 7.3 정규화의 회사명 해결 | 완료 | `f5df70d` |
| 7.4 재정규화 반영 | 완료 | `caffdfc` |
| 7.5 화면 반영 | 완료 | `46024ac` |

테스트 288건에서 317건으로 증가. ruff·mypy 무오류.

## 생성·수정 파일

- `migrations/0004_company.sql` - `crawlers.default_company`, `normalized_jobs.company_source`
- `app/selector/schema.py` - `company` 를 선택 필드로 추가
- `app/normalize/engine.py` - 파싱값 우선, 없으면 운영자값, 둘 다 없으면 NULL
- `app/crawler/runner.py` - 적재 시 회사명 해결 연결
- `app/api/crawlers.py` - `default_company` 입력과 `PUT /api/crawlers/{id}/company`
- `app/templates/` - 등록 화면 입력란, 조회 화면 회사명 열과 출처 표시
- `tests/test_company_selector.py`, `test_company_resolution.py`, `test_company_renormalize.py`
- `tests/fixtures/affiliates-list-20260822.html` - 계열사 혼재 픽스처

## 검증 결과

| 대상 | 검증 | 결과 |
|---|---|---|
| 스키마 | 마이그레이션 적용·역적용 | 기존 행이 `default_company` NULL 로 남고, 역적용 후 두 컬럼만 사라진다. `company_source` CHECK 가 세 번째 값 거절 |
| 셀렉터 | 픽스처 pytest | `company` 없는 기존 JSON 통과, 있는 JSON 도 통과 (8건) |
| 해결 | 픽스처 pytest | 아래 표 (8건) |
| 재정규화 | 픽스처 pytest | 아래 표 (5건) |
| 화면 | 로컬에서 열기 | 입력란·회사명 열·출처 표시·필터 확인 |

### 계열사 혼재 확인

한 목록에 삼성SDS 건과 삼성전기(주) 건이 섞인 픽스처로 워크플로우를 1회 실행했다.

| 조건 | 결과 |
|---|---|
| 회사명 셀렉터 있음 | `[("삼성SDS", parsed), ("삼성전기(주)", parsed)]` |
| 같은 크롤러에 `default_company="삼성전자"` 도 있음 | 파싱값이 이김. 위와 동일 |
| 셀렉터 없고 운영자값만 | `[("삼성전자", operator) × 2]` |
| 둘 다 없음 | `[(NULL, NULL) × 2]` |

`mapping` 규칙을 걸면 `삼성전기(주)` 가 `삼성전기` 로 바뀌는 것까지 단언했다.
**공고마다 다른 회사명이 나온다** — 사이트 하나에 계열사가 섞여도 구분된다.

### parsed 행이 운영자값 변경에 영향받지 않음

| 동작 | 결과 |
|---|---|
| `operator` 행의 `default_company` 변경 후 재정규화 | 그 2건만 갱신. `normalized_jobs.id` 유지, 새 행 없음 |
| `parsed` 행의 크롤러 `default_company` 를 엉뚱한 값으로 변경 후 재정규화 | 파싱값 그대로. `company_source` 도 `parsed` 유지 |
| `raw_jobs` 전체 바이트 해시 | 불변 |
| `delivered_at` 4건 | 전부 원래 값 유지 |
| 운영자값을 NULL 로 지움 | 빈 문자열이 아니라 `company`·`company_source` 모두 NULL 로 복귀 |

## 이슈 및 특이사항

- 기존 테스트 3건의 기대값을 새 스키마로 옮겼다. 선택 필드가 저장 시 `company: ""` 로 채워지고
  `normalize_fields` 반환에 `company_source` 키가 늘어난 것을 반영한 것이고, 단언을 약화시키지 않았다
- CSS 는 넣지 않았다. 7.5 시점의 조건이 Push 6 과 같았다

## 남은 일 (이 Push 범위 밖)

- **운영자 회사명 수정 UI 가 없다.** `PUT /api/crawlers/{id}/company` 는 있지만 7.5 가 등록 화면
  입력란만 요구해서 편집 폼을 넣지 않았다. 잘못 넣은 회사명을 고치려면 API 를 직접 호출해야 한다
- `.claude/docs/api-contract.md` 는 손대지 않았다. `company` 를 실제로 내보내는 것은 Push 8 의 몫이다
