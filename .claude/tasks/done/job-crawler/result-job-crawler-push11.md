# 결과보고서: tasks-job-crawler-push11.md

> 완료일: 2026-08-22 (11.5 실사이트 등록은 미완료)
> Push 범위: Playwright 렌더링
> 브랜치: `feat/job-crawler-pipeline` (푸시하지 않음)

## 왜 이 Push 가 생겼나

PRD 6장이 "JS 렌더링 필요한 페이지: Playwright(Python)" 를 명시하고 `architecture.md` 폴더
배치에도 `app/crawler/playwright.py` 가 있으며 `crawlers.render_mode` 컬럼도 0001 에 있었다.
**구현만 없었고, 그것은 Push 분해 단계의 누락이다.** Push 3 의 관련 파일에 이름만 적혀 있고
하위 작업이 없었다.

## 구현 요약

| 작업 | 상태 | 커밋 |
|---|---|---|
| 11.1 렌더 모듈 | 완료 | `77587ea` |
| 11.2 render_mode 경로 연결 | 완료 | `3e60ea0` |
| 11.3 껍데기 감지와 승격 안내 | 완료 | `0fba3cc` |
| 11.4 컨테이너에 Chromium | 완료 | `679e6cc` |
| 11.6 목록 실패 사유 정정 (신규) | 완료 | `015ae53` |
| 11.5 껍데기 판정 수정 | 완료 | `d23c555` |
| 11.5 실사이트 등록 | **미완료** | 기록만 `ed6777b`, `fccab89` |

## 생성·수정 파일

- `app/crawler/playwright.py` - 렌더러
- `app/crawler/shell.py` - 껍데기 판정과 승격 안내
- `app/crawler/fetcher.py` - `Fetcher.guard()` 로 robots·호스트 잠금·딜레이를 렌더에도 적용
- `app/crawler/runner.py`, `parser.py`, `app/selector/generator.py`, `app/api/crawlers.py`
- `Dockerfile`, `pyproject.toml`, `app/config.py`, `.env.example` (`RENDER_TIMEOUT_SECONDS=60`)
- `tests/test_render.py`, `test_render_mode.py`, `test_shell_detection.py`
- `.claude/site-recipes/www-hanwhain-com.md`, `talent-hyundai-com.md`

**요청 경로는 하나로 유지했다.** 렌더는 `Fetcher.guard()` 안에서만 일어나고 robots·딜레이·
User-Agent 가 정적 경로와 같다. 브라우저 위장이나 로그인 우회는 없다.

## 검증 결과

| 대상 | 검증 | 결과 |
|---|---|---|
| 렌더 모듈 | 로컬 스텁 pytest | robots disallow 시 브라우저 미기동, 같은 호스트 3초 딜레이, 브라우저 1회 기동, 타임아웃 시 닫힘 (9건) |
| 경로 연결 | 픽스처 pytest | `static` 은 렌더러를 만들지 않고, `playwright` 는 정적 fetch 0건. 성공·실패 양쪽에서 브라우저 닫힘 (5건) |
| 껍데기 감지 | 픽스처 pytest | 껍데기는 안내 포함 `selector_miss`, 정상 목록은 안내 없음, 자동 승격 없음 (7건) |
| 컨테이너 | `docker compose up -d --build` | 아래 |

테스트 401건 통과. 렌더 경로는 재시도하지 않는다 — 렌더 1회가 정적 타임아웃의 몇 배라
네 번 반복하면 실행 타임아웃을 넘겨 동시 실행 자리를 붙든다.

## 실측 (arm64)

| 항목 | 값 |
|---|---|
| Chromium 이전 이미지 | 510MB |
| Chromium 이후 이미지 | **2.34GB** (브라우저 레이어 1.37GB) |
| `/ms-playwright` | 984MB |
| 메모리: 브라우저 없음 / 렌더 중 / 닫은 뒤 | 34.8MiB / 185.3MiB / 42.3MiB |

**이미지가 사전 추정(약 1GB)의 두 배 이상이다.** 메모리는 추정 범위(150~300MB)에 들어왔고
브라우저를 닫으면 회수된다. 동시 실행 3이면 최악 450MiB 다.

컨테이너 안에서 정적 205자·항목 0개인 페이지가 렌더 후 619자·item 4건이 되는 것을 확인했다.

## 11.5 실사이트 — 두 곳 다 실패

**렌더는 두 곳 다 성공했다.** 막힌 곳은 상세 링크다. 억지로 통과시키지 않았다.

| 사이트 | 정적 본문 | 렌더 후 | status | error_class |
|---|---|---|---|---|
| 한화 | 3자 | 441,363자 | failed | parse |
| 현대자동차 | 13자 | 1,331,820자 | failed | transport |

렌더된 HTML 에 저장 셀렉터를 적용한 목록 필드별 매칭

| 사이트 | item | title | date | link 노드 | href 있음 | 따라갈 수 있는 href |
|---|---|---|---|---|---|---|
| 한화 | 20 | 20 | 20 | 20 | 0 | 0 |
| 현대자동차 | 20 | 20 | 20 | 20 | 20 | 0 |

- 한화: 목록 항목 안에 `a` 태그가 0개다. Vue 라우터로 이동하고 `rtSeq` 가 렌더된 DOM 어디에도 없다
- 현대자동차: `href` 가 전부 `javascript:void(0)` 이고 상세 파라미터가 `li` 의 `data-recuyy`,
  `data-recutype`, `data-recucls` 에 있다. 공용 클라이언트가 http(s) 가 아니라며 거절해 밖으로
  요청이 나가지 않았다

`seeds/sample-sites.json` 이 삼성에 적어 둔 `detail_link_absent` 와 같은 종류다. Push 14 가 이어받는다.

## 함께 드러난 결함

생성 시점 자체 검증이 `list.link` 를 노드 수로만 판정한다. 한화에서 모델이 `h4.recruit-title` 을
골랐는데 20/20 으로 통과했다. 링크가 아닌 요소를 골라도 성공으로 보인다. Push 14 의 14.1 이 받는다.

## 이슈 및 특이사항

- 11.2 의 `app/api/crawlers.py` 변경분이 다른 세션의 커밋 `f0ed764` 에 함께 담겼다.
  내용 손실은 없다. 같은 브랜치에서 여러 에이전트가 동시에 작업한 결과다
- `data/jobs.db` 의 미적용 마이그레이션 0003~0005 를 적용했다. 적용 전 파일을 백업했다
- `CRAWL_USER_AGENT` 가 `job-crawler-automation (contact: unset)` 이다. 규칙이 요구하는
  "이름과 연락처" 를 절반만 만족한다. 운영 전에 `.env` 에 실제 연락처가 필요하다
