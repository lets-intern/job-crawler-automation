# Tasks: side-workflows - Push 10

> PRD: `.claude/tasks/todo/prd-side-workflows.md`
> Push 범위: 검수 화면에서 원문을 본다. 읽기만 한다
> 상태: 진행 중

## 관련 파일

- `app/api/review.py` - `_modal_response`, `_read_job`, `_COLUMNS`
- `app/templates/fragments/review_modal.html` - 모달
- `app/templates/fragments/review_table.html` - 표. **열을 늘리지 않는다**
- `.claude/rules/writing.md`

## 선행 조건

- Push 8 완료 (`source_text` 가 있어야 볼 것이 있다)

## 작업

- [ ] 10.0 원문 보기
    - [ ] 10.1 모달에 원문을 읽기 전용으로 붙인다. 고치는 칸이 아니다 — 원문은 수집한 것
          그대로여야 하고, `raw_jobs` 는 append-only 다 (`.claude/rules/data-safety.md`)
        - [ ] 10.1.V 검증(화면): 모달을 열어 원문이 보이고 입력할 수 없는지 확인
    - [ ] 10.2 원문이 없는 건에는 "이 건은 본문으로 분류됐다" 를 적는다. 빈 칸으로 두면
          원문을 못 뽑은 것과 아직 재수집하지 않은 것이 같아 보인다
        - [ ] 10.2.V 검증(화면): 기존 수집분을 열어 그 문장이 나오는지 확인
    - [ ] 10.3 표에는 열을 더하지 않는다. 이미 스물세 개다. 이 Push 가 `review_table.html` 의
          헤더를 건드리지 않았는지 확인한다
        - [ ] 10.3.V 검증(화면): 검수 표를 열어 열 수가 그대로인지 확인
