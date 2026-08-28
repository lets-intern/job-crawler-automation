# Tasks: side-workflows - Push 2

> PRD: `.claude/tasks/todo/prd-side-workflows.md`
> Push 범위: 분류 대상 범위 네 가지. 무엇을 돌릴지 고르는 조회만 만든다
> 상태: 끝남

## 관련 파일

- `app/classify/store.py` - `pending_ids`, `pending_count`, `_BODY`
- `app/classify/schema.py` - `CLASSIFY_FIELDS` 열한 칸
- `migrations/0014_job_classifications.sql` - 분류 결과가 어디에 남는지
- `tests/fixtures/` - 픽스처

## 선행 조건

- Push 1 완료 (`target_scope` 값이 저장소에 정의돼 있어야 한다)

## 작업

- [x] 2.0 분류 대상 범위
    - [x] 2.1 범위 이름을 상수로 정하고 `unclassified` 를 지금 `pending_ids` 에 연결한다.
          최근 수집분부터 도는 순서는 그대로 둔다 (2026-08-27 결정)
        - [x] 2.1.V 검증(정규화): 픽스처 DB 에 분류된 건과 안 된 건을 넣고 안 된 것만
              나오는지 pytest
    - [x] 2.2 `empty_fields`. 분류 행은 있는데 열한 칸이 전부 빈 건을 고른다
        - [x] 2.2.V 검증(정규화): 일부만 빈 건은 대상이 아니고 전부 빈 건만 나오는지 pytest
    - [x] 2.3 `recent`. `raw_jobs.crawled_at` 이 최근 N 일 안인 건을 고른다. 분류 여부와
          무관하게 고른다 — 다시 분류하는 범위다
        - [x] 2.3.V 검증(정규화): 경계일 앞뒤 건으로 포함·제외가 갈리는지 pytest
        - [x] 2.3.1 (수정) 경계 검사가 헛돌았다. `datetime('now', '-7 days, +1 minutes')`
              처럼 수정자를 붙여 쓰면 SQLite 가 NULL 을 주고, 그 NULL 이 `coalesce` 로
              지금 시각이 되어 두 건 다 대상에 들어왔다. 수정자를 하나씩 넘기고 NULL 이면
              픽스처가 먼저 걸리게 했다
    - [x] 2.4 `all`. 본문이 있는 건 전부. 이미 분류된 것도 포함한다
        - [x] 2.4.V 검증(정규화): 본문 없는 건은 어느 범위에도 안 들어가는지 pytest
    - [x] 2.5 범위별 대상 건수를 세는 함수. 화면의 확인 창이 이 숫자를 쓴다
        - [x] 2.5.V 검증(정규화): 건수와 실제 id 목록 길이가 같은지 pytest
