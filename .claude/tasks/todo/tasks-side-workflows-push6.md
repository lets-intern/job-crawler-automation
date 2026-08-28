# Tasks: side-workflows - Push 6

> PRD: `.claude/tasks/todo/prd-side-workflows.md`
> Push 범위: `after_crawl` 트리거. 크롤이 새 공고를 적재했을 때만 분류가 이어 돈다
> 상태: 완료 (2026-08-29)

## 관련 파일

- `app/crawler/runner.py` - 실행 끝. `notify_new_jobs` 를 부르는 자리가 본보기다
- `app/notify/new_jobs.py` - 실행 끝에서 부르는 것이 실행을 실패로 만들지 않는 방식
- `app/side/runner.py` - Push 3 에서 만든 실행기

## 선행 조건

- Push 3 완료
- Push 4 완료

## 작업

- [x] 6.0 수집 직후 트리거
    - [x] 6.1 크롤 실행 끝에서 `trigger_kind='after_crawl'` 이고 `status='active'` 인 분류
          워크플로우를 찾아 부른다. 부르는 자리는 알림과 같은 곳이다
        - [x] 6.1.V 검증(스케줄러): `test_새_공고가_있으면_활성_after_crawl_분류가_걸린다`,
              `test_실제로_분류가_돈다` (가짜 제공자로 끝까지) — `run_workflow` 를 실제로
              돌려 `side_runs` 에 행이 생기는지 확인
    - [x] 6.2 적재 건수가 0 이면 부르지 않는다. 신규가 하루 0~1건이라 이 조건이 없으면 대상
          없는 실행이 사이트 수만큼 쌓인다
        - [x] 6.2.V 검증(스케줄러): `test_신규_0건이면_아무것도_하지_않는다`,
              `test_적재_0건이면_시작조차_부르지_않는다`
    - [x] 6.3 여기서 예외가 나가지 않는다. 분류 쪽 사고 하나가 수집을 실패로 만들면 안 된다
          (`app/notify/new_jobs.py` 와 같은 규칙)
        - [x] 6.3.V 검증(크롤링 실행): `test_분류_쪽_사고가_나도_예외를_올리지_않는다` —
              `start` 가 예외를 던지도록 갈아끼우고 `trigger_after_crawl` 이 그대로 돌아오는지
    - [x] 6.4 `side_runs.trigger` 에 `after_crawl` 을 남긴다. 주기로 돈 것과 수집이 부른 것을
          가르지 못하면 "주기가 실제로 도는가" 에 답할 수 없다 (`crawl_runs.trigger` 와 같은 이유)
        - [x] 6.4.V 검증(스키마): `test_새_공고가_있으면_활성_after_crawl_분류가_걸린다` 가
              `run.trigger == "after_crawl"` 을 확인한다. `manual`/`paused` 조합은
              `test_수동_시점의_워크플로우는_걸리지_않는다`,
              `test_멈춘_워크플로우는_걸리지_않는다` 가 본다

## 실행 중 정한 것

`trigger_after_crawl(conn, *, new_count)` 을 `app/side/runner.py` 에 두고
`app/crawler/runner.py` 의 `notify_new_jobs` 바로 뒤에서 부른다 — 순환 임포트가 없다
(`app.side.runner` 는 `app.crawler.runner` 를 들여오지 않는다). 대상 크롤 워크플로우로
좁히지 않는다 — 분류는 `raw_jobs`/`normalized_jobs` 전체를 보는 일이라 어느 크롤이
새 공고를 냈든 활성 `after_crawl` 워크플로우 전부를 건다.

## 검증

`pytest tests/test_after_crawl_trigger.py` 7건, 전체 스위트 `pytest -m "not live"` 1984건
통과. ruff format/check, mypy 에러 0. 실사이트에는 나가지 않았다 — `stub_fetcher` 로 크롤을,
가짜 제공자로 분류를 돌렸다.
