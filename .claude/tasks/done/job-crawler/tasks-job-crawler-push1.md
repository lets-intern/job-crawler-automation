# Tasks: job-crawler - Push 1

> PRD: `.claude/tasks/todo/prd-job-crawler.md`
> Push 범위: 기반 — 프로젝트 뼈대, 설정, SQLite 스키마와 마이그레이션, 공용 fetch 클라이언트, 컨테이너 구성
> 상태: 진행 중

## 관련 파일

- `app/main.py` - FastAPI 앱, 라우터 등록, 스케줄러 기동
- `app/config.py` - 환경변수 로딩
- `app/db.py` - SQLite 연결, 마이그레이션 실행
- `app/models/` - 테이블 모델
- `app/crawler/fetcher.py` - 유일한 외부 요청 경로
- `migrations/` - 마이그레이션 파일
- `tests/fixtures/` - 파서·클라이언트 테스트용 저장 HTML
- `.env.example` - 변수 이름만 문서화. 값은 넣지 않는다
- `docker-compose.yml`, `Dockerfile` - api 컨테이너 1개, SQLite named volume

## 선행 조건

- 없음. 이 Push 가 첫 배포 단위다
- 참조: `.claude/docs/data-model.md` 의 테이블 정의, `.claude/rules/crawling.md`, `.claude/rules/data-safety.md`

## 작업

- [x] 1.0 기반 (Push 범위)

    - [x] 1.1 프로젝트 뼈대와 설정 로딩
        - `pyproject.toml`, `app/main.py`, `app/config.py`
        - `.env.example` 의 변수를 `config.py` 가 전부 읽는다. 기본값은 보수적으로 둔다
        - [x] 1.1.V 검증: 로컬에서 서버 기동 후 `/health` 응답 확인 (`.claude/skills/local-env/SKILL.md`)

    - [x] 1.2 SQLite 연결과 마이그레이션 러너
        - `app/db.py`. 적용된 마이그레이션 버전을 기록하는 테이블 포함
        - DB 파일 삭제로 스키마를 새로 만드는 경로는 만들지 않는다 (`.claude/rules/data-safety.md`)
        - [x] 1.2.V 검증: 빈 DB 에 마이그레이션 적용·역적용 확인

    - [x] 1.3 초기 스키마 마이그레이션
        - `crawlers`, `workflows`, `crawl_runs`, `raw_jobs`, `normalized_jobs`, `normalization_rules`
        - 컬럼은 `.claude/docs/data-model.md` 를 그대로 따른다. 추측으로 컬럼을 늘리지 않는다
        - `raw_jobs.content_hash`, `normalized_jobs.normalized_at` 에 인덱스
        - [x] 1.3.V 검증: 마이그레이션 적용·역적용 확인, 6개 테이블과 인덱스 존재 확인

    - [x] 1.4 공용 fetch 클라이언트
        - `app/crawler/fetcher.py`. User-Agent, 호스트별 딜레이, 타임아웃, robots.txt 확인, 재시도 3회 백오프
        - transport 실패만 재시도한다. 이 모듈 밖에서 `httpx`·`requests` 를 직접 부르지 않는다
        - [x] 1.4.V 검증: 로컬 스텁 응답 기반 pytest 작성 및 통과 — 호스트별 딜레이 준수, 5xx 3회 재시도, robots disallow 시 요청 없이 실패

    - [x] 1.5 중복 감지 해시 유틸
        - `source_url + title + deadline + body` 만 들어간다 (`.claude/docs/data-model.md`)
        - 조회수·상대 날짜·크롤링 시각은 들어가지 않는다
        - [x] 1.5.V 검증: 픽스처 기반 pytest 작성 및 통과 — 같은 공고 두 번 계산 시 동일 해시, 조회수만 다른 입력도 동일 해시

    - [x] 1.6 컨테이너 구성
        - `Dockerfile`, `docker-compose.yml`. `api` 컨테이너 하나, SQLite 는 named volume
        - 별도 `web` 컨테이너·Redis·Celery 를 두지 않는다 (`.claude/docs/tech-stack.md`)
        - [x] 1.6.V 검증: `docker compose up` 후 컨테이너 1개 기동, 볼륨에 DB 파일 생성 확인, `down` 후 재기동 시 파일 유지 확인
