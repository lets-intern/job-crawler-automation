# Tasks: job-crawler - Push 25

> PRD: `.claude/tasks/done/job-crawler/prd-job-crawler.md`
> Push 범위: 세 가지 수집 방식을 화면에서 보고 고치게 한다
> 상태: 대기

## 배경

Push 23 이 방식을 셋으로 늘리고 Push 24 가 자동으로 고른다. 화면은 아직 `static` /
`playwright` 둘만 안다. AI 수정도 CSS 셀렉터만 고칠 줄 안다.

## 관련 파일

- `app/api/ui_crawlers.py` - 등록 화면
- `app/api/ui_tests.py` - 테스트 실행 화면
- `app/selector/repair.py` - AI 수정
- `app/templates/fragments/selector_repair_macro.html` - 등록·테스트가 공유하는 조각

## 선행 조건

- Push 23, 24 완료

## 작업

- [ ] 25.0 화면이 세 방식을 다룬다
    - [ ] 25.1 등록 화면에 목록·상세 방식과 판정 근거를 보인다
        - 둘을 따로 고를 수 있게 한다. 섞어 쓰는 것이 정상적인 선택지다
        - 자동 판정이 고른 값과 근거를 같이 보이고, 운영자가 바꾼 뒤에는 덮어쓰지 않는다
        - [ ] 25.1.V 검증: 로컬에서 화면을 열어 조합을 바꿔 저장하고 HTMX 동작 확인
    - [ ] 25.2 테스트 실행 화면이 API 결과도 필드별로 보인다
        - 셀렉터일 때와 같은 표다. 필드마다 성공 / 실패 / 해당 없음
        - `api` 인 크롤러에 CSS 셀렉터 필드를 실패로 적지 않는다. LG 가 목록 전용일 때
          상세 필드를 실패로 적었던 것과 같은 실수다
        - [ ] 25.2.V 검증: 로컬에서 LG 를 테스트 실행해 필드별 판정 확인
    - [ ] 25.3 AI 수정이 API 매핑도 고친다
        - `api` 면 CSS 셀렉터가 아니라 JSON 매핑을 고친다. 힌트 입력칸은 그대로 쓴다 —
          운영자가 넣을 것이 F12 경로에서 JSON 키로 바뀔 뿐이다
        - 고친 매핑도 실제 응답에 돌려 검증한 뒤에만 보인다
        - [ ] 25.3.V 검증: LG 매핑 한 자리를 일부러 틀리게 두고 AI 수정으로 복구되는지
    - [ ] 25.4 문서를 맞춘다
        - `.claude/docs/architecture.md` 의 파이프라인 설명에 세 방식을 넣는다
        - `.claude/rules/crawling.md` 의 "정적 먼저, Playwright 는 사이트별 승격" 에 API 를 넣는다.
          순서는 static -> api -> playwright 다. API 가 있으면 브라우저를 띄울 이유가 없다
        - `.claude/site-recipes/careers-lg-com.md` 를 API 기준으로 다시 쓴다
        - [ ] 25.4.V 검증: 문서에 적은 경로·필드명이 실제 코드와 같은지 대조
