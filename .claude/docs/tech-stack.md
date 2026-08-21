# 기술 선택

무엇을 쓰는지보다 **무엇을 안 쓰기로 했는지**가 더 중요하다. 아래 "쓰지 않는 것"을 다시 논의하려면
근거(측정값)를 가져와야 한다.

## 쓰는 것

| 영역 | 선택 | 이유 |
|---|---|---|
| 웹 | FastAPI | API 와 화면을 한 프로세스에서 낸다 |
| 화면 | Jinja2 + HTMX | 빌드 단계 없음. 부분 갱신만 필요하다 |
| 스케줄 | APScheduler | 인프로세스. 브로커가 필요 없다 |
| 정적 크롤링 | httpx + BeautifulSoup | 대부분의 채용 페이지에 충분하다 |
| JS 렌더링 | Playwright (Python) | 사이트별 개별 승격. 기본값 아님 |
| LLM | Anthropic API | 셀렉터 생성. `.claude/rules/llm.md` |
| DB | SQLite | 파일 하나. 볼륨 마운트로 영속화 |
| 품질 | ruff, mypy, pytest | |
| 배포 | Docker Compose, 컨테이너 1개 | |

## 쓰지 않는 것

| 안 쓰는 것 | 대신 | 다시 볼 조건 |
|---|---|---|
| Celery + Redis | APScheduler | 워크플로우가 인프로세스로 감당 안 되는 수치가 나왔을 때 |
| PostgreSQL | SQLite | 동시 쓰기 락이 실제로 문제가 됐을 때 |
| React 등 SPA | HTMX | 운영자 화면에 클라이언트 상태가 실제로 필요해졌을 때 |
| Node 크롤러 | Python 통일 | Python 으로 안 되는 사이트가 실제로 나왔을 때 |
| 별도 web 컨테이너 | api 하나 | 없음 |
| 인증·권한 | 없음 | 운영자가 2명 이상이 됐을 때 |

Node 를 따로 두면 프로세스와 배포가 두 스택으로 갈라진다. 1차는 Python 단일 스택이고, 정말 필요한
사이트가 나오면 그때 별도 워커로 검토한다. "나올 것 같아서" 미리 만들지 않는다.

## 환경변수

`.env.example` 이 이름을 문서화한다. 값은 절대 커밋하지 않는다.

| 이름 | 용도 |
|---|---|
| ANTHROPIC_API_KEY | 셀렉터 생성 |
| DATABASE_PATH | SQLite 파일 경로 |
| CRAWL_USER_AGENT | 이름과 연락처를 담는다. 브라우저 위장 금지 |
| CRAWL_DELAY_SECONDS | 같은 호스트 요청 간 최소 간격 |
| CRAWL_TIMEOUT_SECONDS | 요청 1건 타임아웃 |
| MAX_CONCURRENT_RUNS | 전역 동시 실행 상한 |
| RUN_TIMEOUT_SECONDS | 워크플로우 실행 1회 상한 |

키가 없으면 서버는 뜨고 셀렉터 생성만 실패한다. 서버 문제로 오진하기 쉬운 지점이다.
