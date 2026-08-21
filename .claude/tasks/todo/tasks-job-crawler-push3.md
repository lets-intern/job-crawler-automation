# Tasks: job-crawler - Push 3

> PRD: `.claude/tasks/todo/prd-job-crawler.md`
> Push 범위: 크롤링 실행 — 파서, 실패 분류, 재시도, 1회 실행과 `crawl_runs` 기록, 테스트 실행 API
> 상태: 진행 중

## 관련 파일

- `app/crawler/parser.py` - 셀렉터 JSON 적용
- `app/crawler/runner.py` - 1회 실행 = `crawl_runs` 행 하나
- `app/crawler/playwright.py` - 정적 fetch 가 껍데기만 돌려주는 것이 확인된 사이트 전용
- `app/api/crawlers.py` - 테스트 실행 라우터
- `tests/fixtures/` - 파서 테스트는 여기만 본다

## 선행 조건

- Push 1 완료 (`raw_jobs`, `crawl_runs`, fetch 클라이언트, 해시 유틸)
- Push 2 완료 (`crawlers.selectors_json`)

## 작업

- [ ] 3.0 크롤링 실행 (Push 범위)

    - [x] 3.1 셀렉터 적용 파서
        - `app/crawler/parser.py`. 리스트 페이지에서 아이템 목록, 상세 페이지에서 필드를 뽑는다
        - 추출 텍스트를 여기서 정제하지 않는다. 지저분한 텍스트는 정규화 문제다 (`CLAUDE.md`)
        - [x] 3.1.V 검증: 픽스처 기반 pytest 작성 및 통과 — 저장 HTML 에서 아이템 수와 필드 값이 기대값과 일치

    - [x] 3.2 실패 분류
        - `transport`(타임아웃·5xx·연결 끊김) / `selector_miss`(가져왔지만 0개 매칭) / `parse`(매칭됐지만 필드를 못 읽음)
        - 아이템 0건은 실패로 확정한다. 신규 0건인 정상 실행과 절대 같은 결과로 남기지 않는다
        - [x] 3.2.V 검증: 픽스처 기반 pytest 작성 및 통과 — 세 가지 상황 픽스처가 각각 다른 `error_class` 를 만들고, 아이템 0건 픽스처가 `status=failed` 로 끝나는지 확인

    - [x] 3.3 재시도 정책
        - `transport` 만 최대 3회 백오프 재시도. `selector_miss` 는 재시도하지 않는다
        - 재시도 상한과 백오프는 Push 1 의 fetch 클라이언트가 이미 가지고 있다. 두 번째 재시도
          경로를 만들지 않고, 정책이 유지되는지 고정하는 테스트만 추가했다
        - 3.3.V 의 "요청 3회" 는 최초 1회 + 재시도 2회로 읽었다. `CRAWL_MAX_RETRIES` 가 2일 때
          3회, 3일 때 4회가 되는 것을 둘 다 단언한다
        - [x] 3.3.V 검증: 로컬 스텁 응답 기반 pytest 작성 및 통과 — 5xx 는 요청 3회, 0개 매칭은 요청 1회

    - [x] 3.4 1회 실행 러너
        - `app/crawler/runner.py`. 실행 시작에 `crawl_runs` 행을 만들고, 어떤 종료 경로에서도 종료 상태와 카운트로 갱신한다
        - 리스트 파싱 → 해시로 신규 판정 → 신규 건만 상세를 따라간다 → `raw_jobs` 에 append
        - 기존 건은 상세를 가져오지 않는다. `raw_jobs` 를 갱신하지 않는다
        - 신규 판정은 두 단계다. `content_hash` 는 상세에서 오는 `body`·`deadline` 까지 넣어
          만들기 때문에 목록 단계에서는 값을 만들 수 없다. 목록에서는 `source_url` 로 아는
          공고인지만 보고, 상세까지 간 건만 `content_hash` 로 한 번 더 확인한다
        - [x] 3.4.1 수정: 승격 전 실행이 `crawl_runs` 행을 만들 수 없다
            - 0001 의 `crawl_runs.workflow_id` 가 NOT NULL 이라 워크플로우가 없는 테스트 실행은
              행 자체를 못 만든다. 3.5.V 가 확인할 행이 없어진다
            - `migrations/0002_crawl_runs_test_run.sql`. `workflow_id` 를 NULL 허용으로 바꾸고
              `crawler_id` 를 더한다. 둘 다 NULL 인 행은 CHECK 로 막는다
            - 되돌리기: `python -m app.cli migrate down --steps 1`. `workflow_id` 가 NULL 인 행
              (테스트 실행 기록)은 0001 스키마에 들어가지 못해 역적용 시 버려진다
            - 같은 커밋에서 `.claude/docs/data-model.md` 의 `crawl_runs` 표를 고친다
        - [x] 3.4.V 검증: 픽스처 기반 pytest 작성 및 통과 — 같은 픽스처로 2회 실행 시 `raw_jobs` 1행, 2회차 `new_count=0`, `crawl_runs` 2행

    - [ ] 3.5 테스트 실행 API
        - 저장된 셀렉터로 실제 페이지를 1회 크롤링하고 필드별 미리보기와 실패 사유를 돌려준다
        - 통과 시 `crawlers.status` 를 `tested` 로 올린다
        - [ ] 3.5.V 검증: 실사이트 1회 실행 후 `crawl_runs` 행과 카운트 확인 (`.claude/skills/crawl-test/SKILL.md`).
          이 Push 에서 실사이트를 때리는 검증은 이것 하나다 (`.claude/rules/crawling.md`)
