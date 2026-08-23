# Tasks: job-crawler - Push 8

> PRD: `.claude/tasks/todo/prd-job-crawler.md`
> Push 범위: 제공 API — 커서 기반 조회, 전달 확인, `delivered_at` 쓰기 경로 격리
> 상태: 진행 중

## 관련 파일

- `app/api/jobs.py` - 제공 API 라우터
- `.claude/docs/api-contract.md` - 계약. 구현과 이 문서는 같은 커밋에서 바뀐다
- `tests/fixtures/` - 페이지네이션 검증용 데이터 시드

## 선행 조건

- Push 5 완료 (`normalized_jobs` 에 데이터가 있어야 제공할 것이 있다)
- Push 7 완료. 회사명 해결이 끝나야 한다 — 그 전에는 응답의 `company` 가 항상 NULL 로 나간다
- 계약을 바꾸는 작업은 없다. 필드·타입은 `.claude/docs/api-contract.md` 를 그대로 구현한다

## 작업

- [x] 8.0 제공 API (Push 범위)

    - [x] 8.1 커서 기반 조회
        - `GET /api/jobs`. 응답은 `items`, `next_cursor`, `has_more`
        - 오프셋 기반으로 만들지 않는다. 폴링 사이에 삽입된 행 때문에 건너뛰는 건이 생긴다
        - [x] 8.1.V 검증: 커서로 두 번 조회해 누락·중복 없는지 확인 — 시드 데이터를 `limit` 보다 많게 넣고 두 페이지를 이어 받아 id 집합이 전체와 일치하는지 단언

    - [x] 8.2 `updated_after` 와 `limit`
        - `updated_after` 는 `normalized_at` 기준. `limit` 기본 100, 상한 500
        - `normalized_at` 의 의미를 바꾸지 않는다. 소비 측 커서가 이 값에 걸려 있다
        - [x] 8.2.V 검증: 커서로 두 번 조회해 누락·중복 없는지 확인 — `updated_after` 경계값 앞뒤 데이터로 필터가 맞는지, `limit=1000` 요청이 500 으로 잘리는지 확인

    - [x] 8.3 전달 확인 엔드포인트
        - `POST /api/jobs/delivered`. 받은 id 에 `delivered_at` 을 현재 시각으로 찍는다
        - 이미 찍힌 건은 덮어쓰지 않는다
        - [x] 8.3.V 검증: 픽스처 기반 pytest 작성 및 통과 — 같은 id 로 두 번 호출 시 첫 번째 시각이 유지되는지 단언

    - [x] 8.4 `delivered_at` 쓰기 경로 격리
        - 이 엔드포인트 외에는 아무 코드도 `delivered_at` 을 쓰지 않는다 (`.claude/rules/data-safety.md`)
        - 크롤링·재정규화·수동 수정 경로에서 이 컬럼을 만지는 곳이 없는지 확인하고, 있으면 제거한다
        - [x] 8.4.V 검증: 픽스처 기반 pytest 작성 및 통과 — 전달 표시된 행을 재정규화하고 같은 워크플로우를 1회 더 실행한 뒤 `delivered_at` 이 불변인지 단언
