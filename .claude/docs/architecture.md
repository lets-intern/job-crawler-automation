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

## 파이프라인 5단계

각 단계는 다음 단계에 넘기는 것 외에는 서로를 모른다.

| 단계 | 입력 | 출력 | 실패하면 |
|---|---|---|---|
| 셀렉터 생성 | 리스트 URL, 상세 URL | 셀렉터 JSON | 크롤러 등록 안 됨. 데이터에 영향 없음 |
| 크롤링 실행 | 셀렉터 JSON | `raw_jobs` 행 | `crawl_runs` 에 실패 기록, 실패 카운터 증가 |
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
├── models/             테이블 모델
├── crawler/
│   ├── fetcher.py      공용 HTTP 클라이언트. 유일한 외부 요청 경로
│   ├── parser.py       셀렉터 JSON 적용
│   ├── runner.py       1회 실행 = crawl_runs 행 하나
│   └── playwright.py   JS 렌더링이 필요한 사이트 전용
├── selector/
│   ├── cleaner.py      HTML 정제·샘플링
│   ├── generator.py    Anthropic API 호출
│   └── schema.py       셀렉터 JSON 스키마와 검증
├── scheduler.py        APScheduler 등록·갱신·동시성 상한
├── normalize/
│   ├── engine.py       규칙 적용
│   └── rules.py        규칙 타입 정의
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
어떤 rate limit 도 사실이 아니게 된다. `.claude/rules/crawling.md` 참조.

## 실행 1회의 흐름

1. 스케줄러가 워크플로우를 깨운다. 이미 실행 중이면 스킵하고 로그를 남긴다
2. 전역 세마포어를 얻는다. 못 얻으면 대기한다
3. `crawl_runs` 행을 시작 상태로 만든다
4. 리스트 페이지를 가져와 파싱한다. item 0건이면 실패로 확정한다
5. 각 항목의 hash 로 신규 여부를 판정한다. 기존 건은 상세를 따라가지 않는다
6. 신규 건만 상세를 가져와 `raw_jobs` 에 넣는다
7. 정규화 규칙을 적용해 `normalized_jobs` 에 넣는다
8. `crawl_runs` 행을 종료 상태와 카운트로 갱신한다

어떤 경로로 끝나든 8번은 실행된다. 행이 없는 실행은 아무도 디버깅할 수 없다.

## 미결정 사항

PRD 9장의 항목들. 결정되면 이 문서와 해당 rule 을 같이 고친다.

- 동시 실행 상한값 (세마포어 크기)
- 정규화 규칙 변경 시 기존 데이터 일괄 재처리 방식
- 셀렉터 생성 실패 시 재시도 정책의 상세 — 현재는 `rules/llm.md` 의 "깨진 응답만 1회"
