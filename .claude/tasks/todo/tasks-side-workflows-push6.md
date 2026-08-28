# Tasks: side-workflows - Push 6

> PRD: `.claude/tasks/todo/prd-side-workflows.md`
> Push 범위: `after_crawl` 트리거. 크롤이 새 공고를 적재했을 때만 분류가 이어 돈다
> 상태: 진행 중

## 관련 파일

- `app/crawler/runner.py` - 실행 끝. `notify_new_jobs` 를 부르는 자리가 본보기다
- `app/notify/new_jobs.py` - 실행 끝에서 부르는 것이 실행을 실패로 만들지 않는 방식
- `app/side/runner.py` - Push 3 에서 만든 실행기

## 선행 조건

- Push 3 완료
- Push 4 완료

## 작업

- [ ] 6.0 수집 직후 트리거
    - [ ] 6.1 크롤 실행 끝에서 `trigger_kind='after_crawl'` 이고 `status='active'` 인 분류
          워크플로우를 찾아 부른다. 부르는 자리는 알림과 같은 곳이다
        - [ ] 6.1.V 검증(스케줄러): 워크플로우를 켜 두고 크롤 1회를 돌려 분류 실행이
              이어지는지 pytest
    - [ ] 6.2 적재 건수가 0 이면 부르지 않는다. 신규가 하루 0~1건이라 이 조건이 없으면 대상
          없는 실행이 사이트 수만큼 쌓인다
        - [ ] 6.2.V 검증(스케줄러): 신규 0건 실행 뒤 `side_runs` 에 행이 생기지 않는지 pytest
    - [ ] 6.3 여기서 예외가 나가지 않는다. 분류 쪽 사고 하나가 수집을 실패로 만들면 안 된다
          (`app/notify/new_jobs.py` 와 같은 규칙)
        - [ ] 6.3.V 검증(크롤링 실행): 분류를 강제로 실패시키고 `crawl_runs` 가 성공으로
              닫히는지 pytest
    - [ ] 6.4 `side_runs.trigger` 에 `after_crawl` 을 남긴다. 주기로 돈 것과 수집이 부른 것을
          가르지 못하면 "주기가 실제로 도는가" 에 답할 수 없다 (`crawl_runs.trigger` 와 같은 이유)
        - [ ] 6.4.V 검증(스키마): 세 트리거가 각각 그 값으로 남는지 pytest
