# Tasks: 본문 채우기 - Push 1

> PRD: `.claude/tasks/todo/prd-fill-body.md`
> Push 범위: 실패한 공고를 저장하지 않고도 무엇을 놓쳤는지 아는 자리를 만든다 (스키마)
> 상태: 진행 중

## 배경 (PRD 를 안 봐도 되도록)

`normalized_jobs.body` 가 빈 행이 216건 중 86건이다. 86건은 `source_url` 이 목록 주소인 행과
정확히 같다 — 상세에 도달하지 못해 목록에서 읽은 값만 넣고 성공으로 넘긴 것들이다.

앞으로는 **상세에서 본문을 못 얻으면 `raw_jobs` 에 넣지 않는다.** 대신 실행 기록에 남긴다.
그래야 `body` 가 빈 행이 생기지 않고, 놓친 것은 실행 기록에서 본다.

남길 것은 셋이다. 몇 건인가, 왜인가, **어느 공고인가**(제목과 목록에서 읽은 주소).
건수만으로는 고칠 수 없다.

## 관련 파일

- `migrations/` - 0009 까지 있다. 새 파일은 `0010_` 으로 시작한다
- `app/crawler/failures.py` - `ERROR_CLASSES` 튜플과 `classify()`, `run_status()` 가 있다
- `app/crawler/runner.py:109` - `RunResult` 데이터클래스. `crawl_runs` 행에 들어가는 값이다
- `app/crawler/runner.py:102` - `ItemFailure` 데이터클래스
- `app/crawler/runner.py:571` - `_finish_run()` 이 `crawl_runs` 를 갱신한다
- `app/db.py` - 연결과 트랜잭션

## 현재 스키마

```
crawl_runs: id, workflow_id, crawler_id, started_at, finished_at, status,
            success_count, new_count, fail_count, error_class, error_message, trigger
crawlers:   id, name, list_url, detail_url, selectors_json, status, created_at,
            default_company, list_mode, detail_mode, api_config_json
```

`failures.ERROR_CLASSES` 는 지금 `("transport", "selector_miss", "parse")` 셋이다.

## 선행 조건

- 없음

## 작업

- [ ] 1.0 실패와 건너뜀을 기록할 자리를 만든다
    - [x] 1.1 마이그레이션 0010: `crawl_runs` 에 건너뛴 수를 더한다
        - `skipped_count INTEGER NOT NULL DEFAULT 0` 를 더한다
        - 건너뜀은 실패가 아니다. 마감이 지났거나 이미 저장한 공고라 상세를 안 연 건수다
        - `fail_count` 와 **반드시 따로 센다.** 합치면 날짜 형식이 바뀌어 전부 걸러진 사이트가
          "새 공고 0건" 인 정상 실행으로 보인다
        - 되돌리는 법을 파일 주석에 적는다
        - [x] 1.1.V 검증: 마이그레이션 적용·역적용 확인. 적용 후 기존 `crawl_runs` 행이 그대로
              남고 새 열이 0 인지 pytest 로 확인
    - [x] 1.2 마이그레이션 0010: `crawl_run_failures` 표를 만든다
        - 열: `id`, `run_id`(`crawl_runs(id)` 를 가리킨다), `reason`, `title`, `source_url`, `message`,
          `created_at`
        - `run_id` 에 인덱스를 건다. 실행 하나의 실패를 모아 보는 것이 유일한 조회 방식이다
        - **`raw_jobs` 가 아니다.** 여기 들어간 것은 수집 데이터가 아니라 실행 기록이다
        - 보관: 실행 기록이 지워지면 같이 지워진다. `ON DELETE CASCADE` 를 건다
        - [x] 1.2.V 검증: 마이그레이션 적용·역적용 확인. 행을 넣고 `crawl_runs` 행을 지우면
              같이 지워지는지 pytest 로 확인
    - [x] 1.3 실패 종류를 넓힌다
        - `app/crawler/failures.py` 의 `ERROR_CLASSES` 에 넷을 더한다
        - `list_empty` — 목록에서 반복 항목을 못 잡았다
        - `detail_unreachable` — 링크·속성·클릭 어느 것으로도 상세에 못 갔다
        - `detail_empty` — 상세에 갔는데 본문이 비었다
        - 기존 `transport`, `selector_miss`, `parse` 는 그대로 둔다
        - 각 사유에 운영자가 할 다음 행동을 `app/api/ui.py` 의 `NEXT_STEPS` 에 더한다
        - [x] 1.3.V 검증: 픽스처 기반 pytest — 사유마다 `NEXT_STEPS` 에 문구가 있고,
              `ERROR_CLASSES` 에 없는 값을 넣으면 거절되는지
    - [x] 1.3.1 마이그레이션 0010: `crawl_runs.error_class` 의 CHECK 를 새 사유까지 넓힌다
        - 실행 중 추가. 1.3 이 `ERROR_CLASSES` 를 여섯으로 늘렸는데 `crawl_runs.error_class` 의
          CHECK 는 0001 이 만든 세 가지 그대로다. `app/crawler/failures.py` 는 두 값이 같아야
          한다고 스스로 적어 두고 있고, 1.4 의 `_finish_run()` 은 항목 실패의 분류를
          `crawl_runs.error_class` 에 그대로 쓴다 — 넓히지 않으면 `detail_empty` 로 끝난 실행이
          기록되는 순간 IntegrityError 로 죽는다
        - 0009 와 같은 방법을 쓴다. 새 CHECK 를 단 컬럼을 더하고, 값을 옮기고, 옛 컬럼을 지우고,
          이름을 되돌린다. 표를 지웠다 다시 만들지 않는다
        - 되돌리는 법을 파일 주석에 적는다
        - [x] 1.3.1.V 검증: 마이그레이션 적용·역적용 확인. `ERROR_CLASSES` 의 여섯 값이 모두
              저장되고, 밖의 값은 거절되고, 역적용이 실행 기록을 남기는지 pytest 로 확인
    - [ ] 1.4 `RunResult` 와 `_finish_run` 이 새 값을 나른다
        - `app/crawler/runner.py:109` 의 `RunResult` 에 `skipped_count: int = 0` 과
          `failures: list[ItemFailure]` 를 더한다
        - `ItemFailure` 에 `title: str = ""` 을 더한다. 목록에서 읽은 제목이다
        - `_finish_run()` 이 `skipped_count` 를 쓰고 `crawl_run_failures` 에 행을 넣는다
        - **한 트랜잭션이다.** 실행 기록과 실패 목록이 갈라지면 안 된다
        - [ ] 1.4.V 검증: 픽스처 기반 pytest — 실패 3건을 담은 `RunResult` 를 기록하고
              `crawl_runs.fail_count` 가 3, `crawl_run_failures` 가 3행인지 확인

## 하지 않는 것

- 실행 로직 변경. Push 2 다
- 화면 표시. Push 5 다
- 데이터 비우기. Push 6 다
