# Tasks: side-workflows - Push 5

> PRD: `.claude/tasks/todo/prd-side-workflows.md`
> Push 범위: 부가 워크플로우 화면. 목록, 등록·수정, 지금 실행, 실행 이력
> 상태: 진행 중

## 관련 파일

- `app/api/ui.py` - `NAV`, `render`, `render_page`
- `app/templates/pages/workflows.html`, `app/templates/fragments/workflow_list.html` - 본보기
- `app/templates/fragments/renormalize.html` - 진행 상황 폴링과 확인 창의 본보기
- `app/templates/macros.html` - `empty`, `notice_box`, `wait`
- `.claude/rules/writing.md` - 상태는 낱말로 적는다

## 선행 조건

- Push 3 완료 (실행과 진행 조회)
- Push 4 완료 (주기 설정이 실제로 반영돼야 화면이 거짓말을 하지 않는다)

## 작업

- [ ] 5.0 화면
    - [ ] 5.1 `NAV` 에 `부가 워크플로우` 를 더하고 `/side` 페이지를 만든다
        - [ ] 5.1.V 검증(화면): 로컬에서 열어 네비게이션이 켜지는지 확인
    - [ ] 5.2 목록 조각. 종류·이름·상태·실행 시점·대상 범위·마지막 실행·최근 결과를 낱말로
          적는다. 하나도 없을 때 무엇을 하면 되는지 적는다
        - [ ] 5.2.V 검증(화면): 0건일 때와 여러 건일 때를 열어 확인
    - [ ] 5.2.1 (Push 4 에서 넘어옴) 등록·수정·삭제 라우트가 저장 직후 `scheduler.sync(conn)`
          을 부른다. 저장은 됐는데 스케줄러만 옛 주기로 도는 상태를 만들지 않는다.
          크롤 쪽 본보기는 `app/api/workflows.py` 와 `app/api/ui_workflows.py` 다.
          Push 4 의 4.3 이 이 라우트가 없어 멈췄고, 그 자리가 여기다
        - [ ] 5.2.1.V 검증(스케줄러): 1분 주기로 등록해 2회 실행되는 것을 확인한 뒤 원복
    - [ ] 5.3 등록·수정 폼. `kind` 에 따라 고를 수 있는 `target_scope` 가 달라지고,
          `recent` 를 골랐을 때만 일수 칸이 나온다
        - [ ] 5.3.V 검증(화면): 종류를 바꿔 가며 칸이 맞게 나오고, 잘못된 값이 사유와 함께
              거절되는지 확인
    - [ ] 5.4 `all` 을 고르면 대상 건수와 예상 토큰을 확인 창에 적는다. 확인 없이는 저장되지
          않는다 (PRD 2절)
        - [ ] 5.4.V 검증(화면): `all` 저장이 확인 창을 거치는지, 건수가 실제와 맞는지 확인
    - [ ] 5.5 지금 실행 단추와 진행 상황. 도는 동안 폴링해 처리·실패 건수를 갱신한다
        - [ ] 5.5.V 검증(화면): 실행 중에 숫자가 오르고 끝나면 폴링이 멈추는지 확인
    - [ ] 5.6 실행 이력 조각. `side_runs` 를 최근 것부터. 건너뛴 실행과 실패 사유도 보인다
        - [ ] 5.6.V 검증(화면): 성공·실패·건너뜀 세 가지가 구분돼 보이는지 확인
