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

- [x] 11.0 Playwright 렌더링 (Push 범위)

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

    - [x] 11.4 컨테이너에 Chromium
        - `Dockerfile` 에 Playwright 브라우저 설치. `pyproject.toml` 에 의존성 추가
        - [x] 11.4.V 검증: `docker compose up -d --build` 후 컨테이너에서 렌더가 실제로 되는지 확인하고,
          이미지 크기와 렌더 중 메모리를 숫자로 기록. 확인 후 이미지 상태를 보고할 것

        측정 (2026-08-22, arm64/Apple Silicon):

        | 항목 | 값 |
        |---|---|
        | Chromium 이전 이미지 | 510MB (`job-crawler-automation-api:latest`) |
        | Chromium 이후 이미지 | 2.34GB (`job-crawler-playwright:check`) |
        | 브라우저 설치 레이어 | 1.37GB |
        | `/ms-playwright` | 984MB (chromium 641MB + headless shell 340MB + ffmpeg 3.3MB) |
        | 컨테이너 메모리, 브라우저 없음 | 34.8MiB |
        | 컨테이너 메모리, 렌더 중 | 185.3MiB |
        | 컨테이너 메모리, 브라우저 닫은 뒤 | 42.3MiB |

        렌더 확인은 컨테이너 안에 띄운 정적 서버의 JS 목록 페이지로 했다. 정적 본문 205자에
        항목 0개, 렌더 후 619자에 item 4건 매칭이고 title·link·date 가 전부 값이 있다.

        브라우저 하나가 약 150MiB 다. 동시 실행 상한이 3이면 최악 450MiB 를 브라우저가 쓴다.
        추정치(150~300MB)의 아래쪽이다.

        사용자가 보는 포트 8000 컨테이너는 재빌드하지 않았다. 지금 도는 이미지에는 Chromium 이
        없어서, 재빌드 전까지 `render_mode=playwright` 크롤러는 그 컨테이너에서 실패한다.

    - [x] 11.6 목록 실패 사유에 실제로 못 읽은 필드만 적기 (11.5 에서 나온 수정)
        - `parse_list` 가 항목을 하나도 남기지 못했을 때 필수 필드 이름을 통째로 적고 있었다.
          한화는 title 이 정상인데 link 만 없는 사이트인데도 "title, link 를 읽지 못했다" 가 나와
          원인 판정을 한 번 헛짚게 만들었다
        - [x] 11.6.V 검증: 픽스처 기반 pytest 작성 및 통과 — link 만 못 읽은 경우 사유에 link 만 있고
          title 은 없는지 단언

    - [x] 11.5 실사이트 등록 확인
        - `seeds/sample-sites.json` 의 JS 렌더 사이트로 실제 등록을 시도한다
        - **한화와 현대자동차 두 곳만 확인한다.** 나머지는 손대지 않는다 — 실사이트 요청을 최소로 유지한다
          (`.claude/rules/crawling.md`)
        - [x] 11.5.V 검증: 실사이트 1회씩 실행 후 `crawl_runs` 행과 목록 필드별 매칭 개수를 숫자로 확인.
          매칭이 0이면 실패로 보고하고 원인을 적을 것. 억지로 통과시키지 말 것

        **결과: 두 사이트 모두 등록은 되고 실행은 실패했다.** 렌더 경로 자체는 동작한다.
        막힌 곳은 상세 링크이고, 렌더링이 아니라 셀렉터 스키마의 문제다.

        측정 (2026-08-22, `data/jobs.db`):

        | 사이트 | 정적 본문 | 렌더 후 HTML | crawler | run | status | error_class |
        |---|---|---|---|---|---|---|
        | 한화 | 3자 / 반복 0 | 441,363자 | 2 | 3 | failed | parse |
        | 현대자동차 | 13자 / 반복 0 | 1,331,820자 | 3 | 4 | failed | transport |

        렌더된 HTML 에 저장된 셀렉터를 적용한 목록 필드별 매칭:

        | 사이트 | item | title | date | company | link 노드 | href 있음 | 따라갈 수 있는 href |
        |---|---|---|---|---|---|---|---|
        | 한화 | 20 | 20 | 20 | 20 | 20 | 0 | 0 |
        | 현대자동차 | 20 | 20 | 20 | 0 | 20 | 20 | 0 |

        원인은 사이트마다 다르지만 같은 종류다.

        한화는 목록 항목 안에 `a` 태그가 하나도 없다. 상세 이동이 JS 라우터이고 `rtSeq` 는
        렌더된 DOM 어디에도 없다. 생성 모델은 `list.link` 로 `h4.recruit-title` 을 골랐고,
        자체 검증이 노드 수만 세기 때문에 20/20 으로 통과했다.

        현대자동차는 `a` 가 있지만 `href` 가 전부 `javascript:void(0)` 다. 상세 URL 파라미터는
        `li` 의 `data-recuyy`, `data-recutype`, `data-recucls` 속성에 있다. `href` 만 읽는
        지금 스키마로는 URL 을 만들 수 없다. 실행은 `javascript:;` 를 상세 URL 로 넘겼고,
        공용 fetch 클라이언트가 http(s) 가 아니라고 거절해 밖으로 요청은 나가지 않았다.

        `seeds/sample-sites.json` 이 삼성에 대해 적어 둔 `detail_link_absent` 와 같은 종류다.
        해결하려면 `list.link` 가 `href` 외에 data 속성과 URL 템플릿을 받을 수 있어야 한다.
        그것은 셀렉터 스키마 변경이라 이 Push 범위 밖이다.

## 11.5 결과 (2026-08-22 마감)

이 Push 안에서는 두 사이트 다 실패했다. 렌더는 됐고 상세 링크에서 막혔다. 그 뒤 Push 14 가
`list.link_template` 을 만들면서 한쪽이 풀렸다.

| 사이트 | 렌더 | 최종 |
|---|---|---|
| 현대자동차 | 3자 → 441,363자 | **성공.** 브라우저로 등록해 테스트 실행 전 필드 3/3 통과 |
| 한화 | 13자 → 1,331,820자 | 실패. 이 방식으로 풀리지 않는다 |

현대자동차는 `data-recuyy`·`data-recutype`·`data-recucls` 를 URL 템플릿에 끼워 상세를 따라간다.
생성 모델이 `list.link` 를 채우지 못했지만 크롤러가 `draft` 로 남아 손으로 채울 수 있었다 —
그 동작은 커밋 `9a82b81` 이 만들었다.

한화는 렌더된 442,933자 어디에도 `rtSeq` 가 없고 항목 안 `a` 태그가 0개다. 항목의 속성은 Vue
스코프 표시 하나뿐이라 템플릿에 끼울 값이 없다. **셀렉터로 풀 수 있는 문제가 아니다.**
다음 단서는 목록을 채우는 XHR 응답이고, 그것은 별개 수집 방식이라 판단을 남겨 둔다.
`.claude/site-recipes/www-hanwhain-com.md` 에 기록돼 있다.
