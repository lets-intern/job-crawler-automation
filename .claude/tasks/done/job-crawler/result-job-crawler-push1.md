# 결과보고서: tasks-job-crawler-push1.md

> 완료일: 2026-08-21
> Push 범위: 기반 — 프로젝트 뼈대, 설정, SQLite 스키마와 마이그레이션, 공용 fetch 클라이언트, 컨테이너 구성
> 브랜치: `feat/job-crawler-pipeline` (푸시하지 않음)

## 구현 요약

| 작업 | 상태 | 커밋 |
|---|---|---|
| 1.1 프로젝트 뼈대와 설정 로딩 | 완료 | `34cdd24` |
| 1.2 SQLite 연결과 마이그레이션 러너 | 완료 | `b8eb971` |
| 1.3 초기 스키마 마이그레이션 | 완료 | `d2fe7cb` |
| 1.4 공용 fetch 클라이언트 | 완료 | `622013c` |
| 1.5 중복 감지 해시 유틸 | 완료 | `028a236` |
| 1.6 컨테이너 구성 | 완료 | `736870d` |

커밋 6개, 추가 1,505줄.

## 생성·수정 파일

- `pyproject.toml` - 의존성과 도구 설정
- `app/config.py` - `.env.example` 의 변수를 전부 읽는 설정 로딩
- `app/main.py` - FastAPI 앱과 `/health`
- `app/db.py` - SQLite 연결, 마이그레이션 적용·역적용
- `app/cli.py` - 마이그레이션 운영 명령
- `app/crawler/fetcher.py` - 유일한 외부 요청 경로. User-Agent, 호스트별 딜레이, robots 확인, 재시도
- `app/crawler/hashing.py` - `source_url + title + deadline + body` 기반 content hash
- `migrations/0001_initial_schema.sql` - 테이블 6개와 인덱스 2개
- `migrations/README.md` - 마이그레이션 작성 규칙
- `Dockerfile`, `docker-compose.yml`, `.dockerignore` - api 컨테이너 1개, SQLite named volume
- `tests/test_config.py`, `test_db.py`, `test_migrations.py`, `test_fetcher.py`, `test_hashing.py`
- `tests/fixtures/raw-job-sample.json`

## 검증 결과

| 대상 | 검증 | 결과 |
|---|---|---|
| 설정 | 로컬 기동 후 `/health` | 200, `{"status":"ok"}` |
| 스키마 | 마이그레이션 적용·역적용 | 빈 DB 에 적용·역적용·재적용 멱등. 테이블 6개와 인덱스 2개 확인, 역적용 후 `schema_migrations` 만 잔존 |
| fetch 클라이언트 | 로컬 스텁 pytest | 호스트별 딜레이, 5xx 3회 재시도, robots disallow 시 요청 없이 실패. robots 를 못 읽을 때 대상을 때리지 않는 것까지 확인 |
| 해시 | 픽스처 pytest | 동일 공고 동일 해시. 조회수·상대 날짜·광고 문구·정렬 순서·크롤링 시각 변동에 불변 |
| 컨테이너 | `docker compose up`·`down`·재기동 | 컨테이너 1개, 볼륨에 `jobs.db` 49,152바이트 생성. 재기동 후 md5 동일, 마이그레이션은 "이미 최신" |

Push 단위 검사: `pytest -q -m "not live"` 53건 통과, `ruff check` 통과, `ruff format --check` 14개 파일 정상, `mypy app` 8개 파일 무오류.

불변식 확인: `httpx` 임포트는 `app/crawler/fetcher.py` 한 곳뿐. 실사이트 요청 0건.

## 실측값

추정이 아니라 이번 컨테이너 검증에서 잰 값이다.

| 항목 | 측정값 |
|---|---|
| 이미지 디스크 | 263MB (콘텐츠 56.5MB) |
| 유휴 컨테이너 메모리 | 35.81MiB, 프로세스 6개 |

이 시점의 의존성은 FastAPI·uvicorn·httpx 뿐이다. BeautifulSoup·APScheduler·Gemini SDK 가 들어오는
Push 2 이후에는 두 값 모두 오른다.

## 이슈 및 특이사항

- 1.4 와 1.5 커밋 직후 API 529 로 에이전트가 중단됐다. 재개 전에 테스트 케이스 이름 단위로
  검증 항목 충족을 확인한 뒤 체크했고, 재개 후에는 1.6 만 실행했다
- 이 머신에 `uv` 가 없어 `.venv` + `pip` 로 진행했다. `.claude/skills/local-env/SKILL.md` 는
  `uv run` 을 적고 있어 문서와 실제가 다르다. 요청 범위 밖이라 문서는 고치지 않았다
- `.claude/rules/git-safety.md` 의 scope 목록에 컨테이너 구성에 해당하는 값이 없어 1.6 은
  무-scope `chore:` 로 커밋했다. scope 목록에 추가할지는 결정이 필요하다
- task 파일들은 untracked 상태다. 체크 결과를 커밋할지 `task-cleaner` 로 아카이브할지 결정이 필요하다
