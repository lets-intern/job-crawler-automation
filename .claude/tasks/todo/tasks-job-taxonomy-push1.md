# Tasks: job-taxonomy - Push 1

> PRD: `.claude/tasks/todo/prd-job-taxonomy.md`
> Push 범위: `job_taxonomy` 표, 저장소 모듈, 씨앗 넣기. 분류·화면은 다음 Push다
> 상태: 완료 (2026-08-28)

## 관련 파일

- `migrations/0023_job_field_suggestions.sql` - 직전 마이그레이션. 번호와 CHECK·주석 형식의 본보기
- `app/db.py` - 마이그레이션 적용·역적용
- `app/side/store.py`, `app/notify/settings.py` - 저장소 모듈(읽기는 예외를 던지지 않고 쓰기는 검증)의 본보기
- `seeds/job-taxonomy-zighang-20260828.json` - 씨앗. `{note, source, recorded_at, majors: [{name, minors: [str,...]}]}` 모양
- `.claude/rules/data-safety.md` - 마이그레이션 규칙

## 선행 조건

없음. 이 Push가 나머지 전부의 선행 조건이다.

## 작업

- [x] 1.0 `job_taxonomy` 표와 저장소
    - [x] 1.1 `migrations/0024_job_taxonomy.sql` 작성. `job_taxonomy(id, parent_id, name,
          sort_order, enabled, note, created_at, updated_at)`. `parent_id` 는 자기 표를
          참조하는 FK이고 NULL이면 대분류다. `(parent_id, name)` UNIQUE로 같은 부모 아래
          이름 중복을 막는다(부모가 둘 다 NULL인 대분류끼리도 이 제약이 걸리게 `parent_id`를
          `-1` 같은 값이 아니라 NULL 그대로 두고 SQLite의 UNIQUE가 NULL을 서로 다르게
          보는 점을 인지해 대분류 이름 중복은 애플리케이션 레벨에서 추가로 막는다). 주석에
          한 표에 2단계를 함께 두는 이유(PRD 1절)와 되돌리는 법을 적는다
        - [x] 1.1.V 검증(스키마): `tests/test_migrations.py` `ALL_VERSIONS`에 0024 추가,
              적용·역적용 전체 테스트 통과 확인
    - [x] 1.2 `app/taxonomy.py`에 읽기·쓰기. 목록(`list_all`/`list_majors`/`list_minors`),
          한 건 읽기, 만들기, 고치기(이름·순서·메모), 켜기·끄기. **지우는 함수는 만들지
          않았다** — PRD 1절이 지우지 않고 끄는 이유를 정했다
        - [x] 1.2.V 검증(스키마): `tests/test_taxonomy_store.py` — 만들고 읽으면 그대로,
              소분류가 대분류 밑에 달리는지, 켜짐·꺼짐이 반영되는지 pytest 통과
    - [x] 1.3 값 검증. 이름은 같은 부모 아래 유일해야 하고(대분류끼리의 중복은
          `_check_name_unique`가 애플리케이션에서 막는다), 소분류의 `parent_id`는 반드시
          존재하는 대분류를 가리켜야 한다. 거절 사유는 `TaxonomyError.reason`
          (`duplicate_name`/`unknown_parent`/`parent_is_minor`/`empty_name`/`not_found`)에
          담는다
        - [x] 1.3.V 검증(스키마): `tests/test_taxonomy_store.py` — 이름 중복(대분류·소분류
              각각), 없는 부모, 소분류를 부모로 삼는 시도, 빈 이름이 각각 사유와 함께
              거절되는지 pytest 통과
    - [x] 1.4 `taxonomy.load_seed()`. `seeds/job-taxonomy-zighang-20260828.json`을 읽어
          대분류마다 행을 만들고 그 아래 소분류를 순서대로 넣는다. **표가 완전히 비어 있을
          때만** 동작한다
        - [x] 1.4.V 검증(스키마): `tests/test_taxonomy_store.py` — 씨앗을 넣으면 대분류
              25개·소분류 296개가 파일과 정확히 같은 수로 들어오고, 표에 이미 행이 있으면
              `(0, 0)`을 돌려주고 아무 것도 넣지 않는지 pytest 통과. 전체 스위트
              2052건 통과

