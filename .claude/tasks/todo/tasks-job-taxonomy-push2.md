# Tasks: job-taxonomy - Push 2

> PRD: `.claude/tasks/todo/prd-job-taxonomy.md`
> Push 범위: `normalized_jobs`에 두 칸을 더하고, 분류 응답 스키마를 표에서 동적으로 만든다
> 상태: 진행 중

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

- [ ] 2.0 저장 칸과 동적 스키마
    - [ ] 2.1 `migrations/0025_job_major_minor.sql`. `normalized_jobs`에 `job_major`,
          `job_minor` 두 칸을 더한다. 기존 행은 둘 다 NULL이다
        - [ ] 2.1.V 검증(스키마): 마이그레이션 적용·역적용. up 후 두 칸이 있고 down 후
              사라지며 기존 칸·값이 그대로인지 확인
    - [ ] 2.2 분류 응답 스키마를 표에서 만드는 함수. `job_taxonomy`의 켜진 대분류·소분류
          이름으로 `job_major`(대분류 이름 + `판단불가`), `job_minor`(전체 소분류 이름 +
          `판단불가`) 두 필드를 갖는 pydantic 모델을 호출 시점에 만든다(`Classification`을
          고치지 않고 별도 모델을 합성하거나 확장한다 — 정적 모델에 동적 필드를 끼워 넣지
          않는다). 표가 비어 있으면(씨앗을 아직 안 넣었으면) 이 두 필드를 아예 요청하지
          않는다 — 선택지가 없는 판정 칸을 모델에 보내면 뭐라도 고르게 강요하는 것과 같다
        - [ ] 2.2.V 검증(정규화): 가짜 taxonomy 표(대분류 2, 소분류 3)로 스키마를 만들어
              enum이 그 이름들과 정확히 같은지, 표가 비었을 때 두 필드가 빠지는지 pytest
    - [ ] 2.3 `job_major`, `job_minor`를 `app/normalize/engine.py`의 분류-덮는 아홉 칸
          목록(개념상 이제 열한 칸)에 더한다. 분류가 있으면 이 두 칸도 함께 덮이고, 분류가
          없으면 그대로 NULL이다 — 다른 판정 칸과 같은 규칙
        - [ ] 2.3.V 검증(정규화): `job_taxonomy` 표 내용을 바꾼 뒤 다시 만든 스키마로 분류를
              흉내 낸 응답을 정규화에 흘려, 표에 없는 이름은 저장되지 않고 표에 있는 이름은
              그대로 `normalized_jobs.job_major`/`job_minor`에 들어가는지 pytest("표를
              바꾸면 스키마가 따라오는지" — PRD 완료 조건 2)
