---
name: local-env
description: "로컬 개발 서버(FastAPI + APScheduler + SQLite)를 띄우거나 상태를 확인하고 내린다. 사용자가 '로컬 띄워줘', '서버 실행', '로컬 상태', '로컬 내려줘', '도커로 띄워줘' 등을 말할 때 사용한다. 이미 떠 있는 것은 다시 띄우지 않는다."
argument-hint: "[start(기본) | status | stop | docker]"
allowed-tools: Bash, Read
---

# 로컬 실행

컨테이너 하나, 프로세스 하나다. FastAPI 가 API·화면·스케줄러·크롤링 워커를 모두 담고,
SQLite 는 파일 하나다.

## 첫 명령은 status 다

예외 없다. 이미 떠 있는 것은 다시 띄우지 않는다. **이름으로 프로세스를 죽이지 않는다** —
`python` 이나 `uvicorn` 으로 매칭하면 사용자의 다른 작업까지 같이 죽는다. 포트로 확인한다.

```bash
lsof -ti tcp:8000 || echo "8000 비어 있음"
docker compose ps 2>/dev/null
```

## 명령

| 인자 | 동작 |
|---|---|
| 없음 / `start` | 개발 서버를 띄운다 (reload). 이미 떠 있으면 주소만 알려준다 |
| `status` | 포트와 컨테이너 상태만 본다. 아무것도 건드리지 않는다 |
| `stop` | 8000 을 점유한 프로세스만 내린다 |
| `docker` | 배포 구성 그대로 컨테이너로 띄운다 |

```bash
# start
uv run uvicorn app.main:app --reload --port 8000

# docker
docker compose up -d --build
```

`stop` 은 사용자가 명시적으로 요청했을 때만 쓴다.

## 스케줄러 주의

`--reload` 로 띄우면 파일이 바뀔 때마다 프로세스가 다시 뜨고, **APScheduler 도 같이 재등록된다.**
개발 중 워크플로우가 예상 밖에 실행되거나 실행이 끊기는 것은 대개 이것이다. 스케줄 동작을
확인할 때는 reload 없이 띄운다.

로컬에서 워크플로우를 활성 상태로 두면 실제 사이트를 실제 주기로 때린다. 개발 중에는 `paused` 로
두고 `workflow-ops` 의 `run` 으로 1회씩 돌린다.

## 확인

| 주소 | 화면 |
|---|---|
| `http://localhost:8000/` | 크롤러 등록·셀렉터 생성 |
| `http://localhost:8000/workflows` | 워크플로우 목록 |
| `http://localhost:8000/jobs` | 수집 데이터 조회 |
| `http://localhost:8000/docs` | FastAPI 자동 문서 |

## 실패했을 때

포트 점유면 무엇이 잡고 있는지부터 본다. 임포트 에러면 `uv sync` 를 먼저 확인한다.
`.env` 에 `ANTHROPIC_API_KEY` 가 없으면 서버는 뜨지만 셀렉터 생성만 실패한다 — 서버 문제로
오진하기 쉬운 지점이다.
