# Tasks: side-workflows - Push 4

> PRD: `.claude/tasks/todo/prd-side-workflows.md`
> Push 범위: 주기 실행. APScheduler 가 부가 워크플로우도 등록한다
> 상태: 진행 중 (4.3 은 Push 5 대기)

## 관련 파일

- `app/scheduler.py` - `sync()`, `job_id()`, `JOB_PREFIX`, `RunGate`
- `.claude/rules/crawling.md` - 표가 진실이고 스케줄러는 사본이다
- `.claude/docs/architecture.md` - 동시 실행 상한

## 선행 조건

- Push 3 완료 (돌릴 것이 있어야 한다)

## 작업

- [x] 4.0 스케줄러 등록
    - [x] 4.1 잡 id 네임스페이스를 가른다. 지금 `workflow:<id>` 하나뿐이라 부가 워크플로우가
          같은 이름을 쓰면 크롤 잡을 덮는다. `side:<id>` 를 더하고 `workflow_id_of` 가
          남의 잡을 우리 것으로 읽지 않는지 확인한다
        - [x] 4.1.V 검증(스케줄러): 두 종류를 같은 id 로 등록해도 잡이 둘인지 pytest
    - [x] 4.2 `sync()` 를 넓힌다. `side_workflows` 에서 `status='active'` 이고
          `trigger_kind='interval'` 인 행만 등록하고, 표에 없는 잡은 지운다. 부분 갱신 경로를
          따로 두지 않는다
        - [x] 4.2.V 검증(스케줄러): 표를 바꾸고 `sync()` 를 다시 불러 잡 목록이 따라오는지 pytest
    - [x] 4.3 (Push 5 의 5.2.1 로 넘김) 주기·상태를 고치면 그 자리에서 `sync()` 를 부른다. 저장은 됐는데 스케줄러만
          옛 주기로 도는 상태를 만들지 않는다
        - [x] 4.3.V (Push 5 의 5.2.1.V 로 넘김) 검증(스케줄러): 1분 주기로 등록해 2회 실행되는 것을 확인한 뒤 원복
        - 막힌 이유(2026-08-28): **부를 자리가 아직 없다.** `side_workflows` 의 설정을 고치는
          코드는 `app/side/store.py` 의 `create`·`update`·`delete` 뿐이고, 그것을 부르는
          라우트가 하나도 없다. `app/api/side.py` 는 실행과 조회만 열려 있고 스스로 "등록·
          수정·삭제는 Push 5" 라고 적는다. 크롤 쪽 본보기(`app/api/workflows.py`,
          `app/api/ui_workflows.py`)는 라우트가 저장한 뒤 `scheduler.sync(conn)` 을 부르는
          모양이므로, 이 항목은 Push 5 가 등록·수정 라우트를 만들 때 그 라우트 안에서
          끝난다. 여기서 라우트를 미리 만들면 Push 5 의 범위를 가져오는 것이고, `store` 가
          스케줄러를 부르게 하면 `app.scheduler` 와 순환 import 가 되며 표만 다루는 모듈이
          전역 스케줄러에 묶인다
    - [x] 4.4 부가 잡은 크롤 동시 실행 상한(`RunGate`)을 쓰지 않는다. 분류는 사이트를 때리지
          않으므로 크롤 슬롯을 잡으면 수집이 밀린다. 대신 자기 겹침 방지(3.3)만 건다
        - [x] 4.4.V 검증(스케줄러): 상한을 1로 두고 크롤과 분류가 동시에 도는지 pytest
