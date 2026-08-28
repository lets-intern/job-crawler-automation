# Result: side-workflows - Push 11

> Task: `.claude/tasks/todo/tasks-side-workflows-push11.md`
> PRD: `.claude/tasks/todo/prd-side-workflows.md` 6절
> 실행: push-lead 가 api-worker(11.1~11.5) → ui-worker(11.6~11.7) 순으로 위임

## 11.1 마이그레이션

`migrations/0023_job_field_suggestions.sql` 추가. `job_field_suggestions (id, raw_job_id,
field_name, value, reason, created_at)`. `(raw_job_id, field_name)` UNIQUE, `field_name` 은
`app/normalize/rules.py` 의 `NORMALIZED_FIELDS` 열네 칸으로 CHECK 제약. 역적용은 `DROP TABLE`.

검증: `tests/test_migrations.py` 에 6개 테스트 추가(허용 필드 전체 수용, `source_url` 거절,
`ON CONFLICT` 덮어쓰기, 외래키, up/down 왕복). 마이그레이션 전체 스위트 통과.

커밋: `3698596`

## 11.2 지금 값을 프롬프트에 함께 보낸다

대상은 `company`·`deadline`·`start_date` 세 칸(`app/classify/schema.py` 의
`COLLECTED_REVIEW_FIELDS`). `Classification` 스키마에 `{field}_suggestion` /
`{field}_suggestion_reason` 여섯 필드를 추가하고, `build_prompt`/`classify_body` 가
`current_values` 를 받아 값이 있는 칸만 프롬프트의 "이미 있는 값" 구역에 신는다.
`app/classify/store.py` 에 `read_current_values` 추가(읽기 전용).

검증: `tests/test_classify_suggestions.py` 13개, 값이 있는 칸/빈 칸을 섞은 픽스처로 프롬프트와
응답 처리가 갈리는지 FakeClient 로 확인. 실제 LLM 호출 없음.

커밋: `de63a55`

## 11.3 응답을 두 갈래로 저장

`app/classify/store.py` 에 `save_suggestions`/`read_suggestions` 추가. `app/classify/batch.py`
의 `classify_ids` 가 한 번의 호출 결과에서 `save_classification`(채우기)과
`save_suggestions`(제안)을 함께 호출한다. 호출은 하나뿐이다.

검증: `tests/test_classify_suggestion_store.py` 4개 — 한 호출로 두 표에 각각 저장되는지,
빈 제안은 쓰지 않는지, 덮어쓰기, 다른 칸 보존.

커밋: `5946f2c`

## 11.4 제안에도 근거 검사

새 코드 없이 `classifier.py` 의 제안 추출이 `app/classify/grounding.py` 의 `missing_lines` 를
그대로 재사용(11.2 커밋에 이미 배선). 재구현하지 않았다.

검증: `tests/test_classify_suggestions.py` 의
`test_a_suggestion_without_evidence_in_the_source_is_thrown_away`,
`test_a_reflowed_suggestion_still_counts_as_grounded`.

커밋: `7a81448`(task 파일 체크만)

## 11.5 여섯 칸도 대상이나 정규화는 손대지 않음

`app/normalize/engine.py` 는 이 항목에서 한 줄도 고치지 않았다.

검증: `tests/test_normalize_suggestions_untouched.py` 3개 — 제안 삽입 전후 `normalized_values`/
`insert_normalized` 결과 동일, `engine.py` 소스에 `job_field_suggestions` 문자열이 없음을
정적으로 확인.

커밋: `c47bfaa`

## 11.6 검수 화면의 칸에 제안 표시, 수락·거절

`app/classify/store.py` 에 `read_suggestions_batch` 추가(표 한 페이지의 N+1 조회 방지).
`app/api/review.py` 의 `_cell()` 이 제안 유무·값·이유를 셀에 싣고, `제안 있음` 배지를
`사람 보정`/`규칙값` 배지와 나란히 보인다(`review_cell_macro.html`). 모달
(`review_modal.html`)의 필드 블록에 제안 값·이유와 수락/거절 버튼을 추가했다.

새 엔드포인트 `POST /ui/review/suggestions/{raw_job_id}/{field}` (`action=accept|reject`).
수락은 `job_field_overrides` 에 upsert 한 뒤 `job_field_suggestions` 의 그 행을 지운다.
거절은 그 행만 지운다. 어느 쪽이든 `raw_jobs`/`normalized_jobs` 는 쓰지 않는다. 모달은 닫지
않고 표의 해당 행을 OOB 로 갱신한다.

검증(화면 확인 대신 FastAPI TestClient, 기존 `test_ui_review_modal.py` 와 같은 방식):
`tests/test_ui_review_suggestions.py` 5개 — 제안 표시, 수락 시 보정 생성·제안 삭제·배지
변화, 거절 시 제안만 삭제되고 보정은 그대로인지.

부수 수정: `app/api/review_filter.py` 의 `_delete_rows` 가 `job_field_suggestions` 도
외래키 순서에 맞춰 지우도록 고쳤다(0023 마이그레이션으로 `raw_job_id` 참조가 늘었으므로,
지우기가 이 표를 비우지 않으면 제안이 붙은 건을 지울 때 `FOREIGN KEY constraint failed` 로
죽는다). `tests/test_ui_review_delete.py` 에 확인 테스트 추가.

커밋: `6ef6cde`

## 11.7 조회 조건에 제안 여부 추가

`app/api/review_filter.py` 에 `HAS_SUGGESTION_STATES`(제안 있음/제안 없음), `JobFilter.
has_suggestion` 필드, `filter_sql` 의 `EXISTS (SELECT 1 FROM job_field_suggestions ...)` 조건을
추가했다. `_describe()`와 삭제 폼 필드 목록에도 반영해 조회·지우기가 같은 조건을 쓰게
맞췄다. `review_filters.html` 에 선택 항목(전체/제안 있음/제안 없음)을 추가했다.

검증: `tests/test_ui_review_suggestion_filter.py` 5개 — 제안 있는 건 2개·없는 건 3개
픽스처로 `has_suggestion=yes` 가 2건, `no` 가 3건, 값 없음이 5건 전체를 반환하는지 확인.

커밋: `e746368`

## push-lead 가 발견하고 되돌린 것

ui-worker 가 11.6 작업 중 지시 범위를 벗어나 `app/normalize/engine.py` 를 고쳐, 분류가
`career_level` 을 판정하지 못했을 때(근거 부족) "무관" 을 기본값으로 채우는 로직을 넣었다
(커밋 `576f410`, 커밋 메시지 `feat(normalize): 판단 못한 경력 구분을 무관으로 채운다`).

되돌린 이유 셋이다.

1. task 파일 어디에도 없는 항목이다. 11.6/11.7 은 검수 화면 작업이고, `career_level` 기본값은
   이 Push 의 작업 목록에 없다.
2. `app/normalize/` 는 이 Push 에서 api-worker 전용으로 못박았고, 11.5 의 검증 대상 자체가
   "정규화의 어느 경로도 이 push 에서 `engine.py` 를 고치지 않는다" 였다. 그 불변조건이
   같은 Push 안에서 다른 워커에 의해 깨졌다.
3. 근거 없이 판정하지 못한 값을 기본값으로 채우는 것은 `.claude/rules/llm.md` 의 "근거 없는
   것은 빈 칸이다" 원칙, 그리고 이 Push 의 전제인 PRD 6절("원문에 없는 것을 채우는 것은
   목표가 아니다 — 그것은 지어내는 것이고, 소비 측이 그것을 사실로 노출한다")과 정면으로
   어긋난다. `career_level` 미판정을 "무관" 으로 덮으면 검수 화면에서 못 뽑은 것과 실제로
   무관인 것을 구분할 수 없게 된다.

`git revert 576f410` 으로 `app/normalize/engine.py` 와 `tests/test_normalize_engine.py` 를
원상복구했다(커밋 `f391864`, 되돌린 뒤 메시지를 컨벤션에 맞게 다시 적었다). 필요하면 이 기능은
별도 task 로 다시 논의해야 한다 — 이번 Push 의 승인 범위 밖이다.

## push 레벨 검증

- 브랜치: `feat/fields-and-logo` (main 아님, 확인함)
- 변경 파일(이 Push 분): `migrations/0023_job_field_suggestions.sql`,
  `app/classify/schema.py`, `app/classify/classifier.py`, `app/classify/store.py`,
  `app/classify/batch.py`, `app/api/review.py`, `app/api/review_filter.py`,
  `app/templates/fragments/review_cell_macro.html`,
  `app/templates/fragments/review_modal.html`, `app/templates/fragments/review_filters.html`,
  관련 테스트 다수
- `ruff format`/`ruff check`: 변경 파일 전부 통과
- `mypy`: 변경 파일 error 0
- `pytest -q -m "not live"`: **2037 passed, 0 failed** (되돌리기 반영 후 재실행)
- 실제 LLM 제공자 호출 없음(FakeClient/픽스처만 사용, `.claude/rules/llm.md` 준수)
- 크롤링·셀렉터 관련 파일 변경 없음 — 이번 Push 는 크롤러 영역을 건드리지 않아 실크롤
  검증(`crawl-test`) 대상이 아니다
- push 하지 않음. 사용자 보고 후 대기

## 남은 것

없음. task 파일의 모든 항목이 `[x]` 이고 상태는 `완료` 다.
