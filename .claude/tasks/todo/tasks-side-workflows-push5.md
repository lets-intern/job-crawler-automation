# Tasks: side-workflows - Push 5

> PRD: `.claude/tasks/todo/prd-side-workflows.md`
> Push 범위: 부가 워크플로우 화면. 목록, 등록·수정, 지금 실행, 실행 이력
> 상태: 완료 (2026-08-29)

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

- [x] 5.0 화면
    - [x] 5.1 `NAV` 에 `부가 워크플로우` 를 더하고 `/side` 페이지를 만든다
        - [x] 5.1.V 검증(화면): 로컬에서 열어 네비게이션이 켜지는지 확인 (실사 컨테이너,
              `pytest tests/test_ui_side.py`)
    - [x] 5.2 목록 조각. 종류·이름·상태·실행 시점·대상 범위·마지막 실행·최근 결과를 낱말로
          적는다. 하나도 없을 때 무엇을 하면 되는지 적는다
        - [x] 5.2.V 검증(화면): 0건일 때와 여러 건일 때를 열어 확인 (pytest + 실사)
    - [x] 5.2.1 (Push 4 에서 넘어옴) 등록·수정·삭제 라우트가 저장 직후 `scheduler.sync(conn)`
          을 부른다. 저장은 됐는데 스케줄러만 옛 주기로 도는 상태를 만들지 않는다.
          크롤 쪽 본보기는 `app/api/workflows.py` 와 `app/api/ui_workflows.py` 다.
          Push 4 의 4.3 이 이 라우트가 없어 멈췄고, 그 자리가 여기다
        - [x] 5.2.1.V 검증(스케줄러): `test_켜면_주기가_스케줄러에_등록된다`,
              `test_멈추면_스케줄러에서_빠진다`, `test_주기를_고치면_스케줄러_잡도_바뀐다` —
              저장 직후 `get_scheduler().side_scheduled()` 로 실제 등록·해제·주기 변경을 확인
    - [x] 5.3 등록·수정 폼. `kind` 에 따라 고를 수 있는 `target_scope` 가 달라지고,
          `recent` 를 골랐을 때만 일수 칸이 나온다
        - [x] 5.3.V 검증(화면): 종류를 바꿔 가며 칸이 맞게 나오고, 잘못된 값이 사유와 함께
              거절되는지 확인 (pytest + 실사 컨테이너에서 만들기 왕복)
    - [x] 5.4 `all` 을 고르면 대상 건수와 예상 토큰을 확인 창에 적는다. 확인 없이는 저장되지
          않는다 (PRD 2절)
        - [x] 5.4.V 검증(화면): `all` 저장이 확인 창을 거치는지, 건수가 실제와 맞는지 확인.
              `deliver` 종류는 아직 아무것도 보내지 않으므로 확인을 걸지 않는다 — 그 판단을
              테스트로 고정했다
    - [x] 5.5 지금 실행 단추와 진행 상황. 도는 동안 폴링해 처리·실패 건수를 갱신한다
        - [x] 5.5.V 검증(화면): 가짜 제공자로 실제로 돌려, 도는 동안 카드가 폴링 속성을 달고
              끝나면 결과가 반영되는지 확인 (`tests/test_ui_side.py`, `app/api/side.py` 의
              `get_start` 를 갈아끼우는 방식은 `tests/test_api_side.py` 와 같다).
              실제 모델 호출은 하지 않았다 — Gemini 크레딧 고갈, Qwen 미결제, Claude·GPT 키
              없음
    - [x] 5.6 실행 이력 조각. `side_runs` 를 최근 것부터. 건너뛴 실행과 실패 사유도 보인다
        - [x] 5.6.V 검증(화면): 성공·실패·건너뜀 세 가지가 구분돼 보이는지 확인 (pytest)

## 실행 중 발견한 결함과 고친 것

- **실제 결함**: `/ui/side/{id}/run` 이 실행 스레드가 쓸 연결 팩토리로 요청 연결과 무관한
  `db.connect`(기본 경로)를 그대로 썼다. `app/api/side.py` 처럼 `get_connect_factory` 를
  의존성으로 받아 넘기게 고쳤다. 고치기 전에는 테스트에서 스레드가 다른 DB 파일을 열어
  "no such table" 로 조용히 실패했다 — 화면에서도 같은 값이 나갔을 것이다.
- 카드/목록 폼의 컨텍스트를 `card` 하나로 묶었다(`app/templates/fragments/workflow_card.html`
  이 이미 쓰는 방식). 처음에는 변수를 펼쳐 넘겼는데, 반복 안의 `include` 는 부모 스코프의
  변수만 보고 딕셔너리를 펼쳐 주지 않아 목록에서 카드가 빈 채로 나왔다.
- `all` 확인 뒤 다시 폼을 그릴 때 저장된 값이 아니라 방금 제출한(아직 저장되지 않은) 값을
  보여주게 했다 — 아니면 확인 문구는 "all" 을 말하는데 화면의 대상 범위 select 는 옛 값으로
  되돌아가는 모순이 생긴다.

## 검증

`pytest tests/test_ui_side.py` 21건, 전체 스위트 `pytest -m "not live"` 1953건 통과.
ruff format/check, mypy 에러 0. Docker 실사 컨테이너(`docker compose`, `--reload`)에서
로그인 → `/side` → `/ui/side` → 만들기 → 켜기 → 지우기 왕복을 실제로 확인했다(운영 DB에
남기지 않고 지웠다). 실제 모델 호출이 필요한 5.5 는 가짜 제공자로만 확인했다.
