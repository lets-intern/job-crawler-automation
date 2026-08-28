# Tasks: job-taxonomy - Push 2

> PRD: `.claude/tasks/todo/prd-job-taxonomy.md`
> Push 범위: `normalized_jobs`에 두 칸을 더하고, 분류 응답 스키마를 표에서 동적으로 만든다
> 상태: 완료 (2026-08-28)

## 관련 파일

- `app/classify/schema.py` - 지금은 `Classification`이 고정 `Literal`을 쓰는 정적 pydantic
  모델이다. 판정 칸(`career_level` 등)이 닫힌 목록·근거·`판단불가`를 다루는 방식의 본보기
- `app/llm/base.py`, `app/llm/gemini.py` - `response_schema`는 `Any`로 받는 pydantic
  클래스이므로 호출 시점에 만든 동적 모델을 그대로 넘길 수 있다(`pydantic.create_model`)
- `app/normalize/engine.py` - `CLASSIFY_FIELDS`, `NORMALIZED_FIELDS`, `apply_classification`
- `migrations/0017_job_role.sql` - 칸 하나 더하는 마이그레이션의 본보기

## 선행 조건

- Push 1 완료 (`job_taxonomy` 표가 있어야 목록을 읽을 수 있다)

## 작업

- [x] 2.0 저장 칸과 동적 스키마
    - [x] 2.1 `migrations/0025_job_major_minor.sql`. `normalized_jobs`**와**
          `job_classifications`에 `job_major`, `job_minor` 두 칸을 더한다(계획에는
          `normalized_jobs`만 적었으나, `app/classify/store.py::save_classification`이
          분류 저장 컬럼 목록을 그대로 SQL 컬럼으로 써서 `job_classifications`에도 칸이
          없으면 저장 자체가 `OperationalError`로 죽는다 — `job_role`(0017)과 같은 이유로
          두 표 모두 늘렸다). 기존 행은 전부 NULL이다. **추가로** `migrations/0026_taxonomy_override_suggestion.sql`을
          만들어 `job_field_overrides`·`job_field_suggestions`의 CHECK 목록도 넓혔다 — 두
          표 모두 "`NORMALIZED_FIELDS` 전부를 받는다"고 스스로 정해 둔 약속이라, 칸을 넓히면
          CHECK도 같이 넓어져야 그 표들의 기존 테스트(`tests/test_migrations.py`)가 깨지지
          않는다
        - [x] 2.1.V 검증(스키마): `tests/test_migrations.py` — `ALL_VERSIONS`에 0025·0026
              추가, `EXPECTED_COLUMNS`에 `job_taxonomy`(Push 1에서 빠뜨렸던 것도 이번에
              같이 채움)와 `normalized_jobs`의 새 칸 반영, 적용·역적용 포함 전체 통과
    - [x] 2.2 `app/classify/schema.py::build_classification_model()`. `job_taxonomy`의 켜진
          대분류·소분류 이름으로 `job_major`(대분류 이름 + `판단불가`), `job_minor`(전체
          소분류 이름 + `판단불가`) 두 필드를 갖는 pydantic 모델을 호출 시점에 만든다.
          `Classification`은 손대지 않는다 — `pydantic.create_model(__base__=Classification, ...)`으로
          별도 모델을 합성한다. 표가 비어 있으면 `Classification`을 그대로 돌려주고, 대분류만
          있고 켜진 소분류가 없으면 `job_minor` 필드 없이 만든다
        - [x] 2.2.V 검증(정규화): `tests/test_classify_taxonomy_schema.py` 5건 — 빈 표,
              대분류 2·소분류 5로 enum이 정확히 그 이름들과 같은지, 꺼진 값이 목록에서
              빠지는지, 대분류만 있을 때 소분류 필드가 없는지, 만든 모델이 기존 아홉 칸도
              그대로 가지는지 pytest 통과
    - [x] 2.3 `job_major`, `job_minor`를 정규화가 분류 결과로 덮는 경로에 잇는다. **계획을
          바꿨다** — `CLASSIFY_FIELDS`(아홉 칸) 자체에 더하지 않고 별도의
          `TAXONOMY_FIELDS`/`STORED_CLASSIFY_FIELDS`(아홉 칸 + 직무 분류 둘)를 새로 두어
          `app/classify/store.py`(분류 결과 읽기·쓰기)와 `app/normalize/engine.py::apply_classification`이
          그 확장된 목록을 쓰게 했다. `CLASSIFY_FIELDS`를 그대로 넓히면
          `set(EXTRACT_FIELDS) | set(JUDGE_FIELDS) == set(CLASSIFY_FIELDS)`
          (`tests/test_classify_body.py`, "이 아홉 칸은 전부 정적 `Classification` 모델의
          필드다")가 깨진다 — 직무 분류는 동적 모델의 필드라 그 불변식에 속하지 않는다.
          분류가 있으면 이 두 칸도 함께 덮이고, 분류가 없으면 그대로 NULL이다
        - [x] 2.3.V 검증(정규화): `tests/test_normalize_engine.py` 3건 — 분류 결과에
              `job_major`/`job_minor`가 있으면 그대로 채워지는지, 대분류만 있으면 소분류가
              `None`인지, 분류가 없으면 둘 다 비는지 pytest 통과("표를 바꾸면 스키마가
              따라오는지"는 2.2.V가, "저장 경로가 두 칸을 함께 옮기는지"는 이 항목이 본다 —
              "표에 없는 이름은 저장되지 않는다"는 근거 검사가 하는 일이라 Push 3로 미뤘다).
              부수적으로 검수 화면의 값 칸 반복이 `OVERRIDABLE_FIELDS`를 그대로 따라가
              열이 23→25로 늘어난 것을 `tests/test_ui_review_source_text.py`·
              `app/templates/fragments/review_table.html`의 colspan에 반영. 전체 스위트
              2063건 통과
