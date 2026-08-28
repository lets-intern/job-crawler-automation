# Tasks: job-taxonomy - Push 1

> PRD: `.claude/tasks/todo/prd-job-taxonomy.md`
> Push 범위: `job_taxonomy` 표, 저장소 모듈, 씨앗 넣기. 분류·화면은 다음 Push다
> 상태: 진행 중

## 관련 파일

- `migrations/0023_job_field_suggestions.sql` - 직전 마이그레이션. 번호와 CHECK·주석 형식의 본보기
- `app/db.py` - 마이그레이션 적용·역적용
- `app/side/store.py`, `app/notify/settings.py` - 저장소 모듈(읽기는 예외를 던지지 않고 쓰기는 검증)의 본보기
- `seeds/job-taxonomy-zighang-20260828.json` - 씨앗. `{note, source, recorded_at, majors: [{name, minors: [str,...]}]}` 모양
- `.claude/rules/data-safety.md` - 마이그레이션 규칙

## 선행 조건

없음. 이 Push가 나머지 전부의 선행 조건이다.

## 작업

- [ ] 1.0 `job_taxonomy` 표와 저장소
    - [ ] 1.1 `migrations/0024_job_taxonomy.sql` 작성. `job_taxonomy(id, parent_id, name,
          sort_order, enabled, note, created_at, updated_at)`. `parent_id` 는 자기 표를
          참조하는 FK이고 NULL이면 대분류다. `(parent_id, name)` UNIQUE로 같은 부모 아래
          이름 중복을 막는다(부모가 둘 다 NULL인 대분류끼리도 이 제약이 걸리게 `parent_id`를
          `-1` 같은 값이 아니라 NULL 그대로 두고 SQLite의 UNIQUE가 NULL을 서로 다르게
          보는 점을 인지해 대분류 이름 중복은 애플리케이션 레벨에서 추가로 막는다). 주석에
          한 표에 2단계를 함께 두는 이유(PRD 1절)와 되돌리는 법을 적는다
        - [ ] 1.1.V 검증(스키마): 마이그레이션 적용·역적용. up 후 표가 있고 down 후 사라지며
              기존 표가 그대로인지 확인
    - [ ] 1.2 `app/taxonomy.py`(또는 `app/job_taxonomy/store.py`)에 읽기·쓰기. 목록(대분류와
          그 아래 소분류를 함께), 한 건 읽기, 만들기, 고치기(이름·순서·메모), 켜기·끄기.
          **지우는 함수는 만들지 않는다** — PRD 1절이 지우지 않고 끄는 이유를 정했다
        - [ ] 1.2.V 검증(스키마): 임시 DB에 만들고 읽어 값이 그대로 오는지, 켜짐·꺼짐이
              반영되는지 pytest
    - [ ] 1.3 값 검증. 이름은 같은 부모 아래 유일해야 하고, 소분류의 `parent_id`는 반드시
          존재하는 대분류(자신도 `parent_id`가 NULL인 행)를 가리켜야 한다 — 소분류 아래에
          또 소분류를 다는 3단계를 막는다. 거절 사유를 문장으로 돌려준다
        - [ ] 1.3.V 검증(스키마): 이름 중복, 존재하지 않는 부모, 소분류를 부모로 삼는
              시도가 각각 사유와 함께 거절되는지 pytest
    - [ ] 1.4 씨앗 넣기 함수. `seeds/job-taxonomy-zighang-20260828.json`을 읽어 대분류마다
          행을 만들고 그 아래 소분류를 순서대로 넣는다. **표가 완전히 비어 있을 때만** 동작
          한다 — 이미 운영자가 고친 표 위에 씨앗을 다시 부으면 손으로 넣은 값이 씨앗과
          뒤섞인다
        - [ ] 1.4.V 검증(스키마): 씨앗을 넣으면 대분류 수와 소분류 총합이 파일과 같은지,
              표에 이미 행이 있으면 씨앗 넣기가 아무것도 하지 않는지 pytest

