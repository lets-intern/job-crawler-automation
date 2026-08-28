# Tasks: side-workflows - Push 1

> PRD: `.claude/tasks/todo/prd-side-workflows.md`
> Push 범위: 부가 워크플로우 표 두 개와 저장소 모듈. 아무것도 실행하지 않는다
> 상태: 끝남

## 관련 파일

- `migrations/0015_classification_evidence.sql` - 직전 마이그레이션. 번호와 형식을 따른다
- `migrations/0007_run_trigger.sql` - CHECK 제약과 되돌리기 주석의 본보기
- `app/db.py` - 마이그레이션 적용·역적용
- `app/settings.py`, `app/notify/settings.py` - 저장소 모듈의 두 가지 본보기
- `.claude/rules/data-safety.md` - 마이그레이션 규칙

## 선행 조건

없음. 이 Push 가 나머지 전부의 선행 조건이다.

## 작업

- [x] 1.0 부가 워크플로우 표와 저장소
    - [x] 1.1 `migrations/0021_side_workflows.sql` 작성. `side_workflows` 와 `side_runs`
          두 표를 만든다. 컬럼과 CHECK 값은 PRD 1절 그대로다. 주석에 왜 `workflows` 에
          합치지 않는지와 되돌리는 법을 적는다
        - [x] 1.1.V 검증(스키마): 마이그레이션 적용·역적용. `app/db.py` 로 up 후 두 표가
              있고, down 후 사라지며, 기존 표가 그대로인지 확인
    - [x] 1.2 `app/side/store.py` 에 읽기·쓰기. 목록, 한 건 읽기, 만들기, 고치기, 지우기.
          `app/notify/settings.py` 처럼 읽기는 예외를 던지지 않고 쓰기는 검증을 지난다
        - [x] 1.2.V 검증(스키마): 임시 DB 에 만들고 읽어 값이 그대로 오는지 pytest
    - [x] 1.3 값 검증을 저장소에 넣는다. `kind` 마다 받는 `target_scope` 가 다르고
          (`classify` 는 넷, `deliver` 는 셋), `target_days` 는 `recent` 일 때만 있으며,
          `batch_limit` 은 1 이상 `MAX_LIMIT` 이하다
        - [x] 1.3.V 검증(스키마): 범위 밖 값이 거절되고 사유 문장이 나오는지 pytest
    - [x] 1.4 `side_runs` 기록 헬퍼. 실행 시작에 행을 만들고, 어떤 종료 경로에서도 상태와
          카운트로 갱신한다. 기록이 없는 실행이 없어야 한다 (`.claude/rules/crawling.md`)
        - [x] 1.4.V 검증(스키마): 시작만 하고 실패한 실행에도 행이 남고 상태가 찍히는지 pytest
