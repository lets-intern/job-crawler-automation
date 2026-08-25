# 결과보고서: tasks-job-crawler-push23.md

> 완료일: 2026-08-24
> Push 범위: 수집 방식을 목록·상세 각각 `static` / `api` / `playwright` 로 고를 수 있게 한다

## 구현 요약

| 작업 | 상태 | 커밋 |
|---|---|---|
| 23.1 마이그레이션 0008 (list_mode, detail_mode, api_config_json) | 완료 | `ac3a84f` |
| 23.2 `api_config_json` 형식과 검증 | 완료 | `dc112e1` |
| 23.3 API 수집 경로 | 완료 | `5c867f0` |
| 23.4 모드별 실행 분기 | 완료 | `27fcc15` |
| 23.5 LG 설정·실행과 레시피 갱신 | 완료 | `44f3708` |

`render_mode` 열은 없앴다. 두 곳이 같은 것을 말하면 곧 어긋난다.

## 검증 결과

| 대상 | 검증 | 결과 |
|---|---|---|
| 스키마 | 임시 DB 적용·역적용 | pytest 3건 통과. 운영 DB 는 백업 후 적용, 크롤러 6개가 이전 `render_mode` 와 일치 |
| API 설정 형식 | 픽스처 pytest | 17건. `items_path` 없음·공백, `fields` 빈 객체, 없는 필드명, `{id}` 없는 `link_template` 이 각각 이름을 대며 실패 |
| API 수집 | LG 응답 픽스처 pytest | 16건. 83건 추출, 링크 83개 전부 상이, 실패 3분류 확인 |
| 실행 분기 | 픽스처 pytest | 7건. 네 조합 전부 의도한 경로. 목록이 `api` 인 조합에서 렌더러가 한 번도 생성되지 않음 |
| 실사이트 | 1회 실행 (`crawl_runs` 152, trigger=manual) | success 83 / new 83 / fail 0, 약 4분 13초 |

전체 794 passed. ruff, mypy 에러 0.

## 실사이트 실행에서 확인한 것

`source_url` 이 공고마다 다르다. 새 `raw_jobs` 83행의 주소가 전부 고유하고 모양은
`https://careers.lg.com/apply/detail?id=1002029` 이다. 이전 89행은 전부 목록 URL 하나였다.

`company` 에 계열사명이 들어갔다. LG CNS 25, 비즈테크아이 20, LG유플러스 7, 하이엠솔루텍 7,
D&O 6, 로보스타 5, LG전자 3, LG에너지솔루션 3, LG화학 2, LG경영연구원·LG이노텍·
하이케어솔루션·HSAD·LG Magna 각 1 — 계열사 14곳. `company_source` 는 `parsed` 다.

정규화 83건 전부 통과.

## 이슈 및 특이사항

**개발용 컨테이너의 `/app/migrations` 바인드 마운트가 비어 있었다.** `docker-compose.override.yml`
이 붙이는 마운트가 `/Users/...` 로 잡혀(정상은 `/host_mnt/Users/...`) 컨테이너 안에서 0개로
보였다. 기동할 때 도는 `migrate up` 이 "이미 최신" 이라고 답하므로, 재기동해도 새 마이그레이션이
적용되지 않는 상태였다. `docker compose up -d --force-recreate api` 로 마운트를 다시 잡아
해소했다. 9개가 보이고 0008 이 적용됐다.

배포는 영향이 없다. Dockerfile 이 `COPY migrations ./migrations` 로 이미지에 굽고
`docker-compose.coolify.yml` 에는 이를 덮는 마운트가 없다.

**`CRAWL_USER_AGENT` 가 기본값 `job-crawler-automation (contact: unset)` 이다.**
`.claude/rules/crawling.md` 는 이름과 연락처를 정직하게 적을 것을 요구한다. 지금까지의 모든
요청이 연락처 없이 나갔다. 환경변수라 코드로 정하지 않았고 운영자가 넣어야 한다.

**`normalized_jobs.body` 에 LG 상세의 HTML 태그가 남아 있다.** 수집이 아니라 정규화가 다룰
문제다 (`CLAUDE.md`). 소비 측에 텍스트로 보내려면 태그 제거 규칙이 필요하다.

**화면은 아직 두 열을 갈라 고르지 못한다.** `static` / `playwright` 한 값을 받아 두 열에 함께
쓴다. Push 25 몫이다.
