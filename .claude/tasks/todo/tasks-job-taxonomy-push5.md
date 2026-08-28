# Tasks: job-taxonomy - Push 5

> PRD: `.claude/tasks/todo/prd-job-taxonomy.md`
> Push 범위: 검수 화면과 제공 API에 `job_major`/`job_minor` 두 칸을 내보낸다
> 상태: 진행 중

## 관련 파일

- `app/api/jobs.py` - 제공 API. `SELECT`, `JobItem`, `_out()`에 `job_role`이 들어간 자리가
  본보기
- `app/api/review_filter.py` - `FIELD_LABELS`, `EMPTY_NOTES`, 조회 조건 조립
- `app/templates/fragments/review_table.html`, `review_cell_macro.html` - 검수 화면의 칸
- `.claude/docs/api-contract.md` - 소비 측 계약 문서. 필드를 더하면 같은 커밋에서 같이 고친다
  (`.claude/rules/data-safety.md`)

## 선행 조건

- Push 2 완료 (`normalized_jobs.job_major`/`job_minor`가 있어야 한다)
- Push 3 완료 (실제로 값이 채워져야 화면·API에서 확인할 것이 있다)

## 작업

- [ ] 5.0 검수 화면과 제공 API
    - [x] 5.1 검수 화면 표에 `직무 대분류`, `직무 소분류` 두 칸을 더한다. `job_role`(제목에서
          뽑은 자유 텍스트) 칸 옆에 둔다 — 이름이 비슷해 혼동하지 않도록 라벨을 분명히
          가른다("직무"(자유 텍스트) vs "직무 대분류/소분류"(닫힌 목록))
        - [x] 5.1.V 검증(화면): 로컬에서 검수 화면을 열고 두 칸이 보이는지, 값이 있는 건과
              없는 건이 구분되는지 확인 — `tests/test_ui_review_job_major_columns.py`.
              라벨은 `job_major`/`job_minor`가 이미 `OVERRIDABLE_FIELDS`(=`NORMALIZED_FIELDS`)
              에 들어 있어 표에 자동으로 그려졌으나, 표·모달이 함께 쓰는 `_COLUMNS` SELECT 에
              두 컬럼이 빠져 있어 값이 항상 `값 없음`으로만 나오던 버그를 5.1 에서 고쳤다
              (`app/api/review.py`). 열의 물리적 위치는 `job_role` 바로 옆으로 옮기지
              않았다 — `NORMALIZED_FIELDS`(`app/normalize/rules.py`)가 표·모달·규칙
              드롭다운이 공유하는 단일 순서이고, 그 순서는 마이그레이션 추가 이력을 그대로
              따르는 문서화된 관례라 재배치가 관련 없는 화면까지 흔든다. 대신 라벨
              ("직무" vs "직무 대분류"/"직무 소분류")로 분명히 가르는 쪽을 택했다.
    - [x] 5.2 조회 조건에 직무 대분류 필터를 더한다(소분류는 대분류에 종속되므로 대분류
          하나만 먼저 둔다). 목록은 `job_taxonomy`의 켜진 대분류에서 읽는다
        - [x] 5.2.V 검증(화면): 대분류를 골라 조회하면 그 값을 가진 건만 나오는지 확인 —
              `tests/test_ui_review_job_major_filter.py`. 값 자체는 `company` 필터와 같이
              자유 문자열로 받아, 대분류를 끈 뒤에도 이미 그 값으로 분류된 공고를 계속
              조회할 수 있게 했다(닫힌 목록은 select 의 선택지에만 적용된다).
    - [ ] 5.3 제공 API(`GET /api/jobs`)의 `SELECT`·`JobItem`·`_out()`에 `job_major`,
          `job_minor`를 더한다. 값이 없으면 `job_role`과 같은 규칙으로 `null`이다
        - [ ] 5.3.V 검증(제공 API): 커서로 두 번 조회해 두 필드가 응답에 있고 누락·중복이
              없는지 pytest
    - [ ] 5.4 `.claude/docs/api-contract.md`에 두 필드를 더한다. 뜻, 나올 수 있는 값이
          닫힌 목록이 아니라 운영자가 어드민에서 바꾸는 표라는 것, `job_role`과 다른 점을
          적는다
        - [ ] 5.4.V 검증(제공 API): 문서에 적은 필드 이름이 5.3의 응답 키와 정확히 같은지
              대조
