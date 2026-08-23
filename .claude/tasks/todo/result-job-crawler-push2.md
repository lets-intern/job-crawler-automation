# 결과보고서: tasks-job-crawler-push2.md

> 완료일: 2026-08-22
> Push 범위: 셀렉터 생성 — HTML 정제, LLM 호출, 셀렉터 JSON 스키마 검증, 크롤러 등록
> 브랜치: `feat/job-crawler-pipeline` (푸시하지 않음)

## 구현 요약

| 작업 | 상태 | 커밋 |
|---|---|---|
| 2.1 HTML 정제와 샘플링 | 완료 | `9b17148` |
| 2.2 셀렉터 JSON 스키마와 검증 | 완료 | `3b1b28c` |
| 2.3 LLM 셀렉터 생성 호출 | 완료 | `b99313a` |
| 2.4 생성 시점 셀렉터 자체 검증 | 완료 | `bf26e11` |
| 2.5 크롤러 등록과 수동 보정 API | 완료 | `d9c4981` |

## 생성·수정 파일

- `app/selector/cleaner.py` - script·style·svg·주석·인라인 핸들러 제거, 반복 영역 샘플링, 입력 상한
- `app/selector/schema.py` - 셀렉터 JSON 스키마와 검증
- `app/selector/generator.py` - Gemini 호출, 스키마 강제, 깨진 응답 1회 재시도, 생성 로그
- `app/selector/verify.py` - 생성 즉시 같은 HTML 에 셀렉터를 적용해 필드별 매칭 확인
- `app/api/crawlers.py` - 등록(`POST /api/crawlers`)과 수동 보정(`PUT /api/crawlers/{id}/selectors`)
- `tests/fixtures/pythonorg-jobs-list-20260821.html`, `pythonorg-job-detail-20260821.html`
- `tests/test_selector_cleaner.py`, `test_selector_schema.py`, `test_selector_verify.py`, `test_api_crawlers.py`

Gemini 전환에 따라 같이 고친 파일: `.claude/rules/llm.md`, `.claude/docs/tech-stack.md`,
`.claude/docs/architecture.md`, `.env.example`, `app/config.py`, `docker-compose.yml`.

## 검증 결과

| 대상 | 검증 | 결과 |
|---|---|---|
| 정제 | 픽스처 pytest | script·style·svg·주석 0개. `ol.list-recent-jobs > li` 25개를 4개로 샘플링. 69,448자를 16,628자로 축소(상한 30,000) |
| 스키마 | 픽스처 pytest | 정상 JSON 통과. 파싱 불가·미정의 필드·필드 누락이 각각 `unparsable`·`unknown_field`·`missing_field` 로 분류 |
| 생성 | 저장 HTML 로 생성 호출 후 필드별 매칭 개수 | 리스트 4개 필드 전부 25개 매칭(item 25, title 25/25, link 25/25, date 25/25). 상세는 title·body·department 각 1개, 사이트에 없는 requirements·deadline 은 `skipped` |
| 자체 검증 | 틀린 셀렉터 픽스처 | `list.date` 를 존재하지 않는 선택자로 바꾸면 `failed == ["list.date"]`. item 을 깨뜨리면 리스트 4개 필드 전부 실패 |
| 등록 API | 저장 HTML 로 생성 후 DB 확인 | `POST` 201, `crawlers` 1건 `status=draft`. `PUT` 200 후 셀렉터만 바뀌고 `status` 는 `draft` 유지, 재생성 호출 없음. 미정의 필드 `PUT` 은 422 이고 `selectors_json` 무변경 |

Push 단위 검사: `pytest -m "not live"` 107건 통과, `ruff check` 통과, `mypy` 26파일 무오류.

## 생성 호출 실측

모델 ID 는 기억이 아니라 라이브 `models.list()` 로 확인했다. `GEMINI_MODEL` 로 교체 가능하다.

| 항목 | 1회차 | 2회차 |
|---|---|---|
| 모델 | `gemini-3.5-flash` | `gemini-3.5-flash` |
| 입력 토큰 | 10,399 | 10,399 |
| 출력 토큰 | 139 | 139 |
| 합계 토큰 | 11,229 | 11,229 |
| 지연 | 5,649ms | 5,801ms |

사이트 하나 등록에 약 11,000 토큰이 든다. 주기 실행에는 이 호출이 끼지 않는다.

## 이슈 및 특이사항

- 2.3.1 로 기록: Gemini 가 `additionalProperties` 를 모른다. pydantic 의 `extra="forbid"` 가 그 키로
  변환돼 400 INVALID_ARGUMENT 가 났다. 스키마 모델에서 제거하고 미정의 필드 거절은
  `validate_selectors()` 가 계속 담당한다
- 2.5.1 로 기록: FastAPI 가 동기 엔드포인트를 스레드풀에서 돌려 SQLite 연결 생성 스레드와 사용
  스레드가 갈리면서 `sqlite3.ProgrammingError` 가 났다. `app/db.py` 의 `connect()` 에
  `check_same_thread=False` 를 추가했다
- 픽스처는 python.org 채용 목록·상세를 공용 fetch 클라이언트로 각 1회만 받아 저장했다.
  이후 검증은 전부 저장된 파일로 돌렸다
- `pyproject.toml` 에 `beautifulsoup4` 와 `google-genai` 가 추가됐다. 로컬은 `.venv` 에 설치했고
  Docker 이미지는 재빌드 시 자동 반영된다
- `CLAUDE.md` 와 `.claude/rules/core.md` 에 남아 있던 Anthropic 표기는 이 Push 의 지시 범위 밖이라
  워커가 손대지 않았고, 코디네이터가 `cc365e7` 로 따로 정리했다
