# Tasks: job-crawler - Push 11

> PRD: `.claude/tasks/todo/prd-job-crawler.md`
> Push 범위: Playwright 렌더링 — 정적 fetch 가 껍데기만 돌려주는 사이트를 등록 가능하게 만든다
> 상태: 진행 중

## 왜 지금 만드는가

PRD 6장이 "JS 렌더링 필요한 페이지: Playwright(Python)" 를 명시하고 `.claude/docs/architecture.md`
폴더 배치에도 `app/crawler/playwright.py` 가 있다. `crawlers.render_mode` 컬럼도 0001 마이그레이션에
`static` / `playwright` 값으로 이미 들어 있다.

**빠진 것은 구현뿐이고, 그것은 Push 분해 단계의 누락이다.** Push 3 의 "관련 파일" 에 파일명만
적혀 있고 하위 작업이 없었다. 워커가 판단으로 뺀 것이 아니라 할 일 목록에 없었다.

2026-08-22 측정 근거 (공용 fetch 클라이언트로 리스트 URL 1회씩, script·nav·header·footer 제거 후 본문):

| 사이트 | 본문 | 반복 항목 | 판정 |
|---|---|---|---|
| 롯데 | 5,685자 | 6 | 정적으로 목록 있음 |
| 삼성 | 816자 | 4 | 확인 필요 |
| SK | 608자 | 0 | JS 렌더 |
| 한화 | 70자 | 0 | JS 렌더 |
| LG | 10자 | 0 | JS 렌더 |
| 현대자동차 | 13자 | 0 | JS 렌더 |

측정값은 `seeds/sample-sites.json` 에 있다. `.claude/rules/crawling.md` 가 요구하는
"정적 fetch 가 껍데기를 돌려주는 것이 입증된 뒤" 조건이 충족됐다.

## 요청 경로는 여전히 하나다

Playwright 를 넣어도 `.claude/rules/crawling.md` 의 "모든 외부 요청은 공용 fetch 클라이언트를
거친다" 는 깨지지 않아야 한다. Playwright 내비게이션이 robots 확인·호스트별 딜레이·타임아웃을
건너뛰면 그 규칙이 사실이 아니게 된다.

렌더 모듈은 `app/crawler/fetcher.py` 가 소유한 정책을 그대로 적용받는다.
robots 확인과 딜레이는 렌더 경로에서도 먼저 일어난다.

## 이미지가 무거워진다

Chromium 이 들어가면 이미지가 314MB 에서 약 1GB 가 되고, 브라우저 인스턴스마다 150~300MB 를
더 쓴다. 동시 실행 상한이 3이면 최악 900MB 가 브라우저에만 나간다.

이것이 Playwright 를 사이트별 승격으로 두는 이유다. 기본 경로는 계속 정적이다.

## 관련 파일

- `app/crawler/playwright.py` - 렌더 후 HTML 반환
- `app/crawler/fetcher.py` - 렌더 경로에도 robots·딜레이 적용
- `app/selector/generator.py`, `app/crawler/runner.py` - `render_mode` 를 따른다
- `Dockerfile` - Chromium 설치
- `pyproject.toml` - `playwright` 의존성

## 선행 조건

- Push 3 완료 (정적 실행 경로가 있어야 승격 대상이 있다)
- 로그인·CAPTCHA 우회는 PRD 비목표다. 렌더링만 한다 (`.claude/rules/crawling.md`)

## 작업

- [ ] 11.0 Playwright 렌더링 (Push 범위)

    - [x] 11.1 렌더 모듈
        - `app/crawler/playwright.py`. URL 을 받아 렌더된 HTML 을 돌려준다
        - robots 확인과 호스트별 딜레이를 정적 경로와 똑같이 적용받는다. 이 모듈이 정책을 다시 만들지 않는다
        - User-Agent 는 `CRAWL_USER_AGENT` 를 그대로 쓴다. 브라우저를 사칭해 차단을 우회하지 않는다
        - 브라우저는 요청마다 새로 띄우지 않고 재사용하되, 실행이 끝나면 반드시 닫는다
        - 렌더 타임아웃을 따로 둔다. 정적 타임아웃보다 길지만 무한정 기다리지 않는다
        - [x] 11.1.V 검증: 로컬 스텁 기반 pytest 작성 및 통과 — robots disallow 시 브라우저를 띄우지 않고 실패,
          딜레이 준수, 타임아웃 시 브라우저가 닫히는지 단언

    - [x] 11.2 render_mode 를 따르는 경로 연결
        - 셀렉터 생성과 크롤링 실행이 `crawlers.render_mode` 를 보고 정적/렌더를 고른다
        - 기본값은 `static` 이다. 명시적으로 올린 사이트만 렌더한다
        - `render_mode` 를 바꾸는 API 와 화면 수단을 둔다
        - [x] 11.2.V 검증: 픽스처 기반 pytest 작성 및 통과 — `static` 인 크롤러가 렌더 경로를 부르지 않고,
          `playwright` 인 크롤러가 렌더 경로를 부르는지 단언

    - [x] 11.3 껍데기 감지와 승격 안내
        - 정적 fetch 결과가 껍데기면(반복 항목이 없고 본문이 짧으면) 그 사실을 실패 사유에 적는다
        - "정적으로 목록을 찾지 못했다. 렌더 모드로 올려 다시 시도할 수 있다" 를 운영자에게 알린다
        - 자동으로 올리지 않는다. 승격은 운영자가 정한다 (`.claude/rules/crawling.md`)
        - [x] 11.3.V 검증: 픽스처 기반 pytest 작성 및 통과 — 껍데기 픽스처가 승격 안내를 내고,
          정상 목록 픽스처는 내지 않는지 단언

    - [ ] 11.4 컨테이너에 Chromium
        - `Dockerfile` 에 Playwright 브라우저 설치. `pyproject.toml` 에 의존성 추가
        - [ ] 11.4.V 검증: `docker compose up -d --build` 후 컨테이너에서 렌더가 실제로 되는지 확인하고,
          이미지 크기와 렌더 중 메모리를 숫자로 기록. 확인 후 이미지 상태를 보고할 것

    - [ ] 11.5 실사이트 등록 확인
        - `seeds/sample-sites.json` 의 JS 렌더 사이트로 실제 등록을 시도한다
        - **한화와 현대자동차 두 곳만 확인한다.** 나머지는 손대지 않는다 — 실사이트 요청을 최소로 유지한다
          (`.claude/rules/crawling.md`)
        - [ ] 11.5.V 검증: 실사이트 1회씩 실행 후 `crawl_runs` 행과 목록 필드별 매칭 개수를 숫자로 확인.
          매칭이 0이면 실패로 보고하고 원인을 적을 것. 억지로 통과시키지 말 것
