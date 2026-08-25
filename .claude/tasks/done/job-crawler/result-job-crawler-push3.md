# 결과보고서: tasks-job-crawler-push3.md

> 완료일: 2026-08-22
> Push 범위: 크롤링 실행 — 파서, 실패 분류, 재시도, 1회 실행과 `crawl_runs` 기록, 테스트 실행 API
> 브랜치: `feat/job-crawler-pipeline` (푸시하지 않음)

## 구현 요약

| 작업 | 상태 | 커밋 |
|---|---|---|
| 3.1 셀렉터 적용 파서 | 완료 | `12b003e` |
| 3.2 실패 분류 | 완료 | `e6fcae1` |
| 3.3 재시도 정책 | 완료 | `3cc27ef` |
| 3.4.1 테스트 실행용 마이그레이션 (수정 작업) | 완료 | `4df6a05` |
| 3.4 1회 실행 러너 | 완료 | `d518898` |
| 3.5 테스트 실행 API | 완료 | `5df9055` |
| 3.5.V 실사이트 검증 기록 | 완료 | `98dd8b8` |

## 생성·수정 파일

- `app/crawler/parser.py` - 셀렉터 JSON 적용. 추출 텍스트를 정제하지 않는다
- `app/crawler/failures.py` - `transport` / `selector_miss` / `parse` 분류
- `app/crawler/runner.py` - 1회 실행 = `crawl_runs` 행 하나. 해시로 신규 판정, 신규만 상세 추적
- `app/api/crawlers.py` - `POST /api/crawlers/{id}/test-run`
- `migrations/0002_crawl_runs_test_run.sql` - `workflow_id` NULL 허용, `crawler_id` 추가
- `tests/test_parser.py`, `test_failures.py`, `test_retry_policy.py`, `test_runner.py`, `test_api_test_run.py`

## 검증 결과

| 대상 | 검증 | 결과 |
|---|---|---|
| 파서 | 픽스처 pytest | 아이템 25건, 첫 항목 title·link·date 기대값 일치 (9건) |
| 실패 분류 | 픽스처 pytest | 세 상황이 각각 다른 `error_class`. 아이템 0건은 `status=failed` (7건) |
| 재시도 | 로컬 스텁 pytest | 5xx 는 최초 1회 + 재시도, 백오프 1·2·4초. 셀렉터 미스는 요청 1회 (3건) |
| 스키마 | 마이그레이션 적용·역적용 | 0002 up/down 확인. 역적용 시 `workflow_id` 가 NULL 인 행만 버려짐 (15건) |
| 러너 | 픽스처 pytest | 같은 픽스처 2회 실행에 `raw_jobs` 1행, 2회차 `new_count=0`, `crawl_runs` 2행, 기존 행 무변경, 2회차 상세 요청 없음 (8건) |
| 테스트 실행 API | 실사이트 1회 | 아래 표 |

Push 단위 검사: `pytest -m "not live"` 141건 통과, ruff·mypy 오류 0.

## 실사이트 실행 1회

python.org 채용 페이지 대상. 이 Push 에서 실사이트를 때린 유일한 검증이다.

| 항목 | 값 |
|---|---|
| status | success |
| success_count | 3 |
| new_count | 0 |
| fail_count | 0 |
| error_class | NULL |
| 소요 | 15:17:18 시작, 15:17:27 종료 |

요청 4건(목록 1 + 상세 3)에 9초가 걸려 `CRAWL_DELAY_SECONDS=3` 이 실제로 지켜졌다.
`crawlers.status` 는 draft 에서 tested 로 바뀌었다.

`new_count=0` 인 이유는 워크플로우 없는 테스트 실행이 `raw_jobs` 에 적재하지 않기 때문이다.
적재한 것이 0건이지 추출이 0건인 것이 아니고, `success_count=3` 과 `status=success` 가 그것을
실패한 실행과 구분한다.

## 이슈 및 특이사항

- 3.4.1 로 기록: 0001 의 `crawl_runs.workflow_id` 가 NOT NULL 이라 승격 전 테스트 실행이 행을
  만들 수 없었다. 0002 에서 NULL 허용으로 바꾸고 `crawler_id` 를 더했으며 둘 다 NULL 인 행은
  CHECK 로 막았다. 같은 커밋에서 `.claude/docs/data-model.md` 의 `crawl_runs` 표를 고쳤다
- 3.3 은 새 코드 없이 테스트만 추가했다. 재시도 상한과 백오프는 Push 1 의 fetch 클라이언트가
  이미 갖고 있어 두 번째 재시도 경로를 만들지 않았다
- `app/crawler/playwright.py` 는 만들지 않았다. 정적 fetch 가 공고를 정상적으로 돌려주므로
  승격 근거가 없다 (`.claude/rules/crawling.md`)

## 남은 일 (이 Push 범위 밖)

- `.claude/skills/crawl-test/SKILL.md` 가 `python -m app.cli test-run` 과 `app.cli fetch` 를
  안내하는데 `app/cli.py` 에는 `migrate` 밖에 없다. 문서가 없는 명령을 가리키고 있어
  `.claude/rules/writing.md` 위반이다. CLI 명령을 추가할지 문서를 API 기준으로 고칠지 결정이 필요하다
- `CRAWL_USER_AGENT` 기본값이 `job-crawler-automation (contact: unset)` 이다. 운영 전에 `.env` 에
  실제 연락처를 넣어야 한다 (`.claude/rules/crawling.md` 의 정직한 식별)
- python.org 사이트 레시피(정적 fetch 로 충분, 목록 25건/페이지, Playwright 불필요)가 기록으로
  남을 만하다
