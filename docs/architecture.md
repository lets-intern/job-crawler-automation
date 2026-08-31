# 아키텍처

## 이 서비스의 위치

최종 사용자용 채용공고 사이트가 **아니다.** 그 사이트에 넘길 데이터를 만드는 백엔드 파이프라인이다.
산출물은 정규화된 채용공고 데이터고, 소비자는 별도 서비스다.

```
채용 사이트들 ──fetch──> [이 서비스] ──REST──> 채용공고 사이트(별도)
                            │
                      운영자 웹 화면
```

운영자는 한 명이라고 가정한다. 인증·권한은 1차 범위 밖이다 (PRD 비목표).

## 파이프라인 6단계

각 단계는 다음 단계에 넘기는 것 외에는 서로를 모른다.

| 단계 | 입력 | 출력 | 실패하면 |
|---|---|---|---|
| 셀렉터 생성 | 리스트 URL, 상세 URL | 셀렉터 JSON | 크롤러 등록 안 됨. 데이터에 영향 없음 |
| 경로 판정 | 리스트 URL, 셀렉터 JSON | `list_mode`, `detail_mode`, `api_config_json` | 운영자가 고른 모드로 등록되고 사유가 화면에 남는다 |
| 크롤링 실행 | 셀렉터 JSON, 경로 | `raw_jobs` 행 | `crawl_runs` 에 실패 기록, 놓친 공고는 `crawl_run_failures` |
| 스케줄링 | 워크플로우 주기 | 주기적 실행 | 해당 워크플로우만 멈춤 |
| 정규화 | `raw_jobs` | `normalized_jobs` | raw 는 남아 있으므로 규칙 고치고 재실행 |
| 제공 | `normalized_jobs` | REST 응답 | 소비 측이 다음 폴링에 따라잡음 |

정규화가 raw 를 건드리지 않는 것이 이 구조의 핵심이다. 잘못된 정규화 규칙 하나가 수집 데이터를
영구 손상시키지 않는다.

## 프로세스 구성

컨테이너 하나, 프로세스 하나다.

```
api (FastAPI)
├── REST API          운영 화면용 + 외부 제공용
├── Jinja2 + HTMX     서버 렌더링 화면. 빌드 단계 없음
├── APScheduler       워크플로우 주기 실행. 인프로세스
└── 크롤링 워커        같은 프로세스의 async 태스크
    └── SQLite (볼륨 마운트된 파일 1개)
```

Celery·Redis·별도 web 컨테이너를 두지 않는다. 이유는 [tech-stack.md](tech-stack.md).

## 폴더 배치

```
app/
├── main.py             FastAPI 앱, 라우터 등록, 스케줄러 기동
├── config.py           환경변수
├── db.py               SQLite 연결, 마이그레이션 실행
├── settings.py         DB 에 저장되는 운영 설정 (동시 실행 상한)
├── crawler/
│   ├── fetcher.py      공용 HTTP 클라이언트. 유일한 외부 요청 경로
│   ├── collect.py      이 실행이 목록·상세를 무엇으로 가져올지 고른다
│   ├── api_source.py   JSON·HTML 조각 API 목록과 상세
│   ├── parser.py       셀렉터 JSON 적용
│   ├── failures.py     실패 분류 (transport, detail_empty ...)
│   ├── runner.py       1회 실행 = crawl_runs 행 하나
│   ├── click_probe.py  등록할 때 항목을 눌러 상세에 닿았는지 판정한다
│   └── playwright.py   브라우저 렌더. 등록의 경로 판정과 렌더 크롤러만 이 경로로 간다
├── selector/
│   ├── cleaner.py      HTML 정제·샘플링
│   ├── generator.py    Gemini API 호출
│   ├── discovery.py    등록할 때 상세로 가는 길을 찾는다
│   ├── detail_path.py  알아낸 요청을 상세 API 설정으로 옮긴다
│   ├── api_schema.py   API 설정(`api_config_json`) 스키마와 검증
│   └── schema.py       셀렉터 JSON 스키마와 검증
├── scheduler.py        APScheduler 등록·갱신·동시성 상한
├── normalize/
│   ├── engine.py       규칙 적용
│   ├── rules.py        규칙 타입 정의
│   └── backfill.py     수동 재정규화
├── api/                라우터
├── templates/          Jinja2
└── cli.py              운영 명령 (test-run, workflow, fetch)
tests/
├── fixtures/           저장된 HTML. 파서 테스트는 여기만 본다
└── ...
```

## 요청이 나가는 경로는 하나다

`crawler/fetcher.py` 만 외부에 요청한다. 셀렉터 생성이 페이지를 가져올 때도 이 클라이언트를 쓴다.
딜레이·User-Agent·robots 확인·재시도가 전부 여기 있고, 다른 경로가 생기는 순간 레포에 적힌
어떤 rate limit 도 사실이 아니게 된다. `../.claude/rules/crawling.md` 참조.

## 가져오는 방식은 크롤러마다, 목록과 상세가 따로 갈린다

`crawlers.list_mode` 와 `crawlers.detail_mode` 가 각각 `static` / `api` / `playwright` 중
하나다. 섞어 쓰는 것이 정상적인 선택지다 — 목록은 JSON API 로 오고 상세는 서버가 그려 주는
문서인 사이트가 있다(SK). `api` 가 부를 엔드포인트와 응답에서 읽을 자리는
`crawlers.api_config_json` 에 있고 형식은 `app/selector/api_schema.py` 가 강제한다.

이 실행이 무엇으로 가져올지 고르는 곳은 `app/crawler/collect.py` 의 `open_collectors()` 다.
브라우저는 실제로 필요한 쪽에서만 뜬다 — 목록이 `api` 면 목록 때문에 뜨지 않는다.

화면에는 낱말로 적는다 (`app/api/ui.py` 의 `describe_path()`).

| 무엇 | 낱말 |
|---|---|
| 목록을 얻는 법 | `목록 API` / `목록 렌더` / `정적 목록` |
| 상세로 가는 법 | `상세 API` / `링크` / `항목 속성` |

경로는 등록할 때 정해지고 운영자가 크롤러 등록 화면에서 바꾼다
(`PUT /api/crawlers/{crawler_id}/collect-modes`). 바꾼 값을 자동 판정이 덮어쓰지 않는다.

## 상세로 가는 길은 등록할 때 알아낸다

운영자는 목록 URL 하나만 넣는다. `app/selector/discovery.py` 의 `discover_detail_path()` 가
정적 fetch → 렌더 → 항목 클릭 → 알아낸 요청 재확인 순서로 돌고, 앞 단계로 풀리면 뒤 단계는
하지 않는다. **브라우저는 이 판정에서 정적으로 안 될 때만 뜬다** (`Renderer.open_probe`).

판정 결과와 근거 문장은 등록 결과 화면에 그대로 나온다. 왜 그 경로로 정해졌는지가 없으면
다음 사람이 처음부터 다시 잰다. 판정하지 못해도 등록은 남고, 사유와 다음 행동이 화면에 적힌다.

2026-08-25 측정에서는 여섯 사이트 전부 목록·상세를 `httpx` 로 받는다. 정규 실행에 브라우저가
필요한 사이트는 없다 (`../.claude/site-recipes/`).

## 실행 1회의 흐름

1. 스케줄러가 워크플로우를 깨운다. 이미 실행 중이면 스킵하고 로그를 남긴다
2. 전역 세마포어를 얻는다. 못 얻으면 대기한다
3. `crawl_runs` 행을 시작 상태로 만든다
4. 목록을 가져와 파싱한다. item 0건이면 실패로 확정한다
5. 각 항목의 hash 로 신규 여부를 판정한다. 이미 아는 공고와 마감이 지난 공고는 상세를 열지
   않고 `crawl_runs.skipped_count` 로 센다. **건너뜀은 실패가 아니라 따로 센다**
6. 남은 건만 상세를 가져와 `raw_jobs` 에 넣는다. 상세에 못 갔거나 본문이 비면 넣지 않고
   `crawl_run_failures` 에 사유·제목·목록에서 읽은 주소로 남긴다
7. 정규화 규칙을 적용해 `normalized_jobs` 에 넣는다
8. `crawl_runs` 행을 종료 상태와 카운트로 갱신한다

어떤 경로로 끝나든 8번은 실행된다. 행이 없는 실행은 아무도 디버깅할 수 없다.

5번의 건너뜀을 6번의 실패에 합치면 마감 날짜 형식이 바뀌어 전부 걸러진 사이트가 "새 공고
0건" 인 정상 실행으로 보인다. 화면도 두 숫자를 나눠 적는다 (워크플로우 카드, 테스트 실행 요약).

## 동시 실행 상한

고정값이 아니라 어드민 화면에서 바꾸는 운영 설정이다 (2026-08-21 결정).

`.env` 의 `MAX_CONCURRENT_RUNS` 는 값이 아직 없을 때 한 번 넣어 주는 초기값이고, 그 뒤로는
`app_settings` 테이블이 진실이다. 값이 바뀌면 프로세스를 다시 띄우지 않고 다음 실행부터
새 상한이 적용된다. 이미 돌고 있는 실행은 끊지 않는다.

읽고 쓰는 곳은 `app/settings.py`, 상한을 실제로 거는 곳은 `app/scheduler.py` 다.

## 기존 데이터 재정규화

규칙을 저장해도 기존 `normalized_jobs` 는 그대로다 (2026-08-21 결정). 운영자가 재정규화를
명시적으로 실행했을 때만 `raw_jobs` 를 다시 읽어 갱신한다.

규칙 저장에 재처리를 묶지 않는 이유는 하나다. 규칙 다섯 개를 손보는 동안 같은 데이터를
다섯 번 다시 쓰게 된다.

재정규화는 크롤링 실행이 아니라 `crawl_runs` 에 쓰지 않고, `delivered_at` 도 건드리지 않는다.
진행 상황은 한 프로세스 안의 메모리에 두고, 돌고 있는 동안 들어온 요청은 거부한다.

동작은 `app/normalize/backfill.py`, 트리거는 `app/api/rules.py` 의 `/api/rules/renormalize` 다.

## 미결정 사항

PRD 9장의 항목들. 결정되면 이 문서와 해당 rule 을 같이 고친다.

- 셀렉터 생성 실패 시 재시도 정책의 상세 — 현재는 `rules/llm.md` 의 "깨진 응답만 1회"
