# Tasks: side-workflows - Push 3

> PRD: `.claude/tasks/todo/prd-side-workflows.md`
> Push 범위: 부가 워크플로우 실행기. 분류 한 종류만 붙이고 `side_runs` 에 남긴다
> 상태: 진행 중

## 관련 파일

- `app/classify/batch.py` - 이미 있는 분류 실행. 대상 고르기만 바꿔 그대로 쓴다
- `app/crawler/runner.py` - 실행 하나가 행 하나를 남기는 구조의 본보기
- `app/normalize/backfill.py` - 겹쳐 돌지 않게 막는 방식의 본보기
- `app/api/classify.py` - 시작은 202, 진행은 GET 인 응답 모양

## 선행 조건

- Push 1 완료 (`side_runs` 와 기록 헬퍼)
- Push 2 완료 (대상 범위)

## 작업

- [ ] 3.0 실행기와 실행 기록
    - [x] 3.1 `app/side/runner.py` 골격. 워크플로우 id 를 받아 표에서 설정을 다시 읽고
          (스케줄러 메모리가 아니라 표가 진실이다), `side_runs` 행을 만들고 끝에 갱신한다
        - [x] 3.1.V 검증(스키마): 성공·실패 두 경로 모두 행이 종료 상태로 닫히는지 pytest
    - [x] 3.1.1 (추가) 기동 시 `app/side/runs.py` 의 `close_orphans` 를 부른다. Push 1 이
          만들어 뒀지만 아무도 부르지 않아, 프로세스가 죽으며 남긴 열린 행이 영원히 진행
          중으로 남는다. 3.3 의 겹침 방지가 그 행을 보고 판단하므로 뒷정리가 없으면 죽은
          실행 하나가 워크플로우를 영구히 막는다
        - [x] 3.1.1.V 검증(스키마): 열린 행을 남긴 채 기동해 `timeout` 으로 닫히는지 pytest
    - [x] 3.2 `classify` 종류를 연결한다. `target_scope` 로 대상을 고르고 `batch_limit` 으로
          자른 뒤 `app/classify/batch.py` 에 넘긴다. 분류 자체의 코드는 고치지 않는다
        - [x] 3.2.V 검증(정규화): 가짜 제공자로 픽스처 DB 를 돌려 처리·실패 건수가
              `side_runs` 에 그대로 들어가는지 pytest
    - [x] 3.3 겹침 방지. 같은 워크플로우가 돌고 있으면 새 실행을 시작하지 않고 건너뛴다.
          건너뛴 사실을 로그와 `side_runs` 에 남긴다 — 조용히 사라지면 주기가 도는지 알 수 없다
        - [x] 3.3.V 검증(스케줄러): 두 번 연달아 부르고 두 번째가 건너뛰기로 기록되는지 pytest
        - [x] 3.3.1 (추가) 겹침 방지를 두 진입점에 다 건다. 이미 있는 `POST /api/classify` 는
              `side_runs` 를 보지 않으므로, 한쪽에만 걸면 화면에서 건 분류와 직접 부른 분류가
              같은 공고에 두 번 돈을 쓴다. 실행기는 `ClassifyRun` 이 도는지 보고, 그 경로는
              열린 분류 실행이 있는지 본다
            - [x] 3.3.1.V 검증(제공 API): 부가 실행이 열려 있는 동안 `POST /api/classify` 가
                  409 로 거절되는지, 반대로 그 경로가 도는 동안 부가 실행이 건너뛰기로
                  기록되는지 pytest
    - [x] 3.4 실패 처리. 제공자 키가 없거나 호출이 전부 실패해도 실행은 닫히고 사유가
          `error_message` 에 남는다. 예외가 스케줄러까지 올라가지 않는다
        - [x] 3.4.V 검증(스케줄러): 키 없는 상태로 돌려 실행이 `failed` 로 닫히는지 pytest
    - [x] 3.5 `POST /api/side/{id}/run` 으로 한 번 돌린다. 응답은 시작했다는 것까지고
          진행은 `GET /api/side/{id}` 로 본다 (`app/api/classify.py` 와 같은 모양)
        - [x] 3.5.V 검증(제공 API): 시작 요청이 202 이고, 도는 동안 GET 이 진행 중을
              돌려주며, 끝난 뒤 건수가 맞는지 확인
