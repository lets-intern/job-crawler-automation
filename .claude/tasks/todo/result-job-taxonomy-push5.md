# 결과보고서: tasks-job-taxonomy-push5.md

> 완료일: 2026-08-29
> Push 범위: 검수 화면과 제공 API에 `job_major`/`job_minor` 두 칸을 내보낸다

## 구현 요약

| 작업 | 상태 | 커밋 |
|---|---|---|
| 5.1 검수 화면 표에 직무 대분류/소분류 칸 | 완료 | `5f150c0` |
| 5.2 조회 조건에 직무 대분류 필터 | 완료 | `d49319b` |
| 5.3 제공 API에 job_major/job_minor 추가 | 완료 | `7aa4d3b` |
| 5.4 계약 문서에 두 필드 반영 | 완료 | `3b0f37e`(아래 특이사항 참고) |

## 생성·수정 파일

- `app/api/review.py` - `_COLUMNS` SELECT 에 `job_major`/`job_minor` 추가(5.1, 표·모달이
  공유하는 `_BASE` 라 둘 다 고쳐진다), `/ui/review/filters` 조각에 켜진 대분류 목록
  (`job_majors`) 을 실어 보내도록 `list_majors` import·context 추가(5.2)
- `app/api/review_filter.py` - `JobFilter`에 `job_major` 필드, `read_filter`·`as_form`·
  `filter_sql`·`_describe`·`_delete_request` 모두에 반영(5.2)
- `app/templates/fragments/review_filters.html` - 회사 select 옆에 직무 대분류 select 추가
- `app/api/jobs.py` - `_SELECT`·`JobOut`·`_out()`에 `job_major`/`job_minor`를 `job_role`
  다음 자리로 추가(5.3)
- `.claude/docs/api-contract.md` - 응답 예시, `job_role`과의 차이, "닫힌 목록이지만 이
  문서가 값을 고정하지 않는다"는 설명, 필드 표 두 줄 추가(5.4)
- `tests/test_ui_review_job_major_columns.py` (신규) - 5.1.V
- `tests/test_ui_review_job_major_filter.py` (신규) - 5.2.V
- `tests/test_api_jobs.py` - `test_item_shape_matches_contract`에 두 키 추가,
  `test_job_major_minor_go_out_filled_or_null`·`test_job_major_minor_survive_two_cursor_pages`
  신규(5.3.V)
- `tests/test_api_contract_doc.py` (신규) - 계약 문서의 응답 예시 JSON과 실제 응답 키를
  대조(5.4.V)

## 검증 결과

| 대상 | 검증 | 결과 |
|---|---|---|
| 5.1.V 검수 표 칸·값 구분 | `tests/test_ui_review_job_major_columns.py` (머리글 3종 분리, 분류된/안된 건 값 구분) | 통과 |
| 5.2.V 대분류 필터 | `tests/test_ui_review_job_major_filter.py` (켜진 대분류만 select, 필터링, 꺼진 대분류도 기존 분류 조회 가능) | 통과 |
| 5.3.V 커서 두 번 조회 | `tests/test_api_jobs.py::test_job_major_minor_survive_two_cursor_pages` (limit=2로 4건을 두 페이지로 받아 id 누락·중복 없음, 두 필드 존재 확인) | 통과 |
| 5.4.V 문서-응답 키 대조 | `tests/test_api_contract_doc.py` (문서의 JSON 예시 키 집합 == 실제 응답 키 집합; `job_minor`를 문서에서 지워 실패하는지 임시로 확인 후 원복) | 통과 |
| 전체 회귀 | `pytest -q -m "not live"` | 2155 passed |
| 정적 검사 | `ruff format` / `ruff check` / `mypy` (변경 파일) | 통과, 에러 0 |

## 이슈 및 특이사항

- **5.1 작업 중 기존 버그를 발견해 고쳤다.** `job_major`/`job_minor`는 이미 `NORMALIZED_FIELDS`
  (=`OVERRIDABLE_FIELDS`)에 들어 있어 검수 표에 칸 자체는 그려지고 있었지만, 표·모달이
  함께 쓰는 `app/api/review.py`의 `_COLUMNS` SELECT 문에 두 컬럼이 빠져 있어 실제 값과
  무관하게 항상 "값 없음"으로만 나왔다(이전 push의 "fix" 커밋이 헤더·colspan만 맞추고
  이 SELECT는 놓쳤던 것으로 보인다). `_COLUMNS`에 두 컬럼을 더해 고쳤다.
- **열의 물리적 위치는 `job_role` 바로 옆으로 옮기지 않았다.** task 파일이 "job_role 칸
  옆에 둔다"고 적었으나, 표·모달·규칙 화면의 값 칸 순서는 전부 `app/normalize/rules.py`의
  `NORMALIZED_FIELDS` 튜플 하나가 정하고, 그 순서는 마이그레이션이 필드를 더한 이력을 그대로
  따르는 문서화된 관례다(주석에 0011/0016/0017/0025 이력이 적혀 있다). 이 튜플 순서를
  바꾸면 검수 표뿐 아니라 규칙 만들기 드롭다운·재정규화 컬럼 순서까지 함께 흔들려 이 Push의
  범위를 넘어선다고 판단해, 이름 옆(`FIELD_LABELS`의 "직무" vs "직무 대분류"/"직무 소분류")으로
  분명히 가르는 쪽으로 대신했다. 필요하면 별도로 상의 후 진행하는 것을 권한다.
- **동시 세션과 커밋이 섞였다.** 이 브랜치(`feat/fields-and-logo`)에서 다른 세션이 대시보드
  토큰 사용량 그래프 작업을 병행하고 있었다. 5.4 커밋을 준비하며 `git add`로 스테이징한
  직후, 그 세션이 자신의 커밋을 만들면서 내가 스테이징해 둔 `.claude/docs/api-contract.md`,
  `.claude/tasks/todo/tasks-job-taxonomy-push5.md`, `tests/test_api_contract_doc.py`가
  그쪽 커밋(`3b0f37e`, "대시보드 추이 그래프 막대가 안 보이던 CSS 버그를 고친다")에 함께
  들어갔다. 커밋마다 `git branch --show-current`로 브랜치는 매번 확인했으나 이 인터리빙은
  막지 못했다. 커밋 diff를 직접 대조해 5.4의 내용은 정확히 들어가 있음을 확인했고
  (해당 커밋의 diff에 의도한 변경만 있다), 공유 히스토리를 다시 쓰는 위험한 작업
  (rebase 등)은 다른 세션이 계속 진행 중일 수 있어 하지 않았다. 커밋 메시지가 5.4 내용을
  설명하지 않는 점은 그대로 남아 있다.
- 전체 테스트 중 `tests/test_after_crawl_trigger.py::test_신규_0건이면_아무것도_하지_않는다`가
  전체 스위트를 함께 돌릴 때 한 번 타임아웃으로 실패했다가 단독 실행/재실행에서는 통과했다.
  배경 스레드 타이밍에 의존하는 기존 테스트로 보이며, 이번 변경과는 무관하다.
