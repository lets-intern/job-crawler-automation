# Tasks: job-crawler - Push 2

> PRD: `.claude/tasks/todo/prd-job-crawler.md`
> Push 범위: 셀렉터 생성 — HTML 정제, LLM 호출, 셀렉터 JSON 스키마 검증, 크롤러 등록
> 상태: 완료

## 관련 파일

- `app/selector/cleaner.py` - HTML 정제와 반복 영역 샘플링
- `app/selector/generator.py` - LLM API 호출
- `app/selector/schema.py` - 셀렉터 JSON 스키마와 검증
- `app/api/crawlers.py` - 크롤러 등록·수동 보정 라우터
- `app/crawler/fetcher.py` - 페이지를 가져올 때도 이 클라이언트를 쓴다
- `tests/fixtures/` - 생성 검증용 저장 HTML

## 선행 조건

- Push 1 완료 (`crawlers` 테이블, 설정 로딩, fetch 클라이언트)
- **결정됨 (2026-08-21): LLM 제공자는 Gemini.** `.env` 에 있는 `GEMINI_API_KEY` 를 쓴다.
  PRD 6장과 `.claude/rules/llm.md`, `.claude/docs/tech-stack.md` 는 Anthropic 기준으로 적혀 있으므로
  2.3 에서 같이 고친다. `.env.example` 의 `ANTHROPIC_API_KEY` 도 `GEMINI_API_KEY` 로 바꾼다.
  응답 스키마 강제는 Gemini 의 structured output 을 쓴다. 제공자를 고르는 어댑터 계층은 만들지 않는다
  (`.claude/rules/core.md` 단순함 우선)
- 결정됨: 생성 실패 시 재시도는 `.claude/rules/llm.md` 의 "깨진 응답만 1회" 를 그대로 구현한다

## 작업

- [x] 2.0 셀렉터 생성 (Push 범위)

    - [x] 2.1 HTML 정제와 샘플링
        - `app/selector/cleaner.py`. `script`, `style`, `svg`, 주석, 인라인 이벤트 핸들러 제거
        - 반복 리스트는 형제 3~4개만 남긴다. 정제 후에도 상한을 넘으면 영역을 좁힌 뒤 자르고, 좁혔다는 사실을 응답에 남긴다
        - [x] 2.1.V 검증: 픽스처 기반 pytest 작성 및 통과 — 저장 HTML 정제 후 스크립트 0개, 리스트 아이템 4개 이하, 출력 크기 상한 이하

    - [x] 2.2 셀렉터 JSON 스키마와 검증
        - `app/selector/schema.py`. 리스트 필드(item, title, link, date)와 상세 필드(title, body, requirements, deadline, department)
        - 스키마에 없는 필드명이 오면 실패로 처리한다. 추측해서 고치지 않는다
        - [x] 2.2.V 검증: 픽스처 기반 pytest 작성 및 통과 — 정상 JSON 통과, 필드 누락·미정의 필드·파싱 불가 응답은 각각 실패로 분류

    - [x] 2.3 LLM 셀렉터 생성 호출
        - `app/selector/generator.py`. Gemini API 로 구현한다. 모델 ID 와 파라미터는 기억으로 쓰지 말고 문서를 확인한다
        - 같은 커밋에서 `.claude/rules/llm.md`, `.claude/docs/tech-stack.md`, `.env.example` 의 Anthropic 표기를 Gemini 로 고친다
        - 응답을 셀렉터 JSON 스키마로 강제한다. 깨진 응답만 1회 재시도하고, 반복 실패는 운영자에게 넘긴다
        - 생성마다 모델 ID, 입출력 토큰 수, 지연을 로그로 남긴다 (`.claude/rules/llm.md`)
        - API 키는 환경변수에서만 읽는다
        - [x] 2.3.1 수정: Gemini 가 `additionalProperties` 를 모른다
            - 응답 스키마로 넘긴 pydantic 모델의 `extra="forbid"` 가 `additionalProperties: false` 로
              변환돼 400 INVALID_ARGUMENT 가 났다. 스키마 모델에서 `extra="forbid"` 를 뺀다
            - 스키마에 없는 필드명 거절은 `validate_selectors()` 가 계속 담당한다 (2.2 그대로)
        - [x] 2.3.V 검증: 저장된 HTML 로 생성 호출, 필드별 매칭 개수 확인 — 리스트 필드 4개가 모두 1개 이상 매칭되는지 확인하고 로그에 모델 ID·토큰·지연이 남았는지 확인

    - [x] 2.4 생성 시점 셀렉터 자체 검증
        - 생성된 셀렉터를 방금 가져온 그 HTML 에 즉시 적용한다
        - 0개 매칭 필드는 성공으로 표시하지 않는다. 실패한 필드 이름을 그대로 결과에 넣는다
        - [x] 2.4.V 검증: 저장된 HTML 로 생성 호출, 필드별 매칭 개수 확인 — 일부러 틀린 셀렉터를 넣은 픽스처에서 해당 필드가 실패 목록에 뜨는지 확인

    - [x] 2.5 크롤러 등록과 수동 보정 API
        - 리스트 URL·상세 URL 입력 → 생성 → `crawlers` 행을 `status=draft` 로 저장
        - 셀렉터 수동 편집 엔드포인트. 편집된 셀렉터를 요청 없이 재생성하지 않는다 (`.claude/rules/llm.md`)
        - [x] 2.5.1 수정: 요청 스레드가 갈려 SQLite 연결을 못 쓴다
            - FastAPI 는 의존성과 동기 엔드포인트를 스레드풀에서 돌린다. 연결을 만든 스레드와 쓰는
              스레드가 달라 `sqlite3.ProgrammingError` 가 났다
            - `db.connect()` 에 `check_same_thread=False` 를 준다. 연결은 요청 1건이 열고 닫으므로
              동시에 공유되지 않는다
        - [x] 2.5.V 검증: 저장된 HTML 로 생성 호출 후 `crawlers` 행이 `status=draft` 로 1건 생성됐는지, 수동 편집 후 `selectors_json` 이 바뀌고 `status` 는 그대로인지 확인
