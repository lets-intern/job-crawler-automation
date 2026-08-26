# 카카오 (careers.kakao.com)

- 리스트 URL: https://careers.kakao.com/jobs?part=BUSINESS_SERVICES&company=KAKAO&page=1
- 수집 방식: 목록은 `api`, 상세는 `playwright` (크롤러 30, 2026-08-25 등록)
- 목록 API:
  `GET https://careers.kakao.com/public/api/job-list?skillSet=&part=BUSINESS_SERVICES&company=KAKAO&employeeType=&page=1`
  - `items_path` 는 `jobList`, 제목은 `jobOfferTitle`, 회사명은 `companyName`,
    id 는 `realId`(`P-14503`)
  - 헤더 없이 공용 fetch 클라이언트로 200 이다. `referer` 도 필요 없었다
- 상세 URL 형식: `https://careers.kakao.com/jobs/<realId>?skillSet=&part=...&company=...&employeeType=&page=1`
  (목록 페이지가 항목에 걸어 둔 주소 그대로다. 쿼리를 떼지 않았다)
- 페이지네이션: 없음. 등록된 것은 `part=BUSINESS_SERVICES&company=KAKAO` 한 묶음이고
  2026-08-25 에 11건이었다. 다른 직군은 `part` 를 바꿔 따로 등록한다
- 날짜 포맷: 목록 응답의 `endDate` 가 `null` 인 공고가 많다(상시 영입). 마감일은 상세에서 온다
- robots.txt: 공용 fetch 클라이언트의 robots 확인을 통과했다
- 권장 주기: 미승격. 워크플로우로 올릴 때 정한다

## 정적으로는 껍데기다

목록 페이지를 정적으로 받으면 공고가 하나도 없다. 등록이 스스로 렌더로 올려 셀렉터를 만들고,
렌더 중에 나간 `job-list` 응답을 목록 API 로 채택했다 — 그 뒤로 목록은 브라우저 없이 온다.

## 항목 자체가 `a` 다

목록 마크업이 `<a href="/jobs/P-14503?..."><li>...</li></a>` 라, 항목 안에서 링크를 찾는
셀렉터로는 주소가 나오지 않는다. 그래서 `list.link` 는 0건으로 남아 있다 — **목록이 API 라
실행에는 쓰이지 않는다.** 상세 주소는 `api_config_json` 의 `link_template` 이 만든다.

상세 주소 형식(`https://careers.kakao.com{href}`)은 등록할 때 만들어 봤지만 채택하지 않았다.
정적으로 열면 그 공고 제목이 없어서다(상세가 JS 로 그려진다). 그 사실이 그대로
`detail_mode = playwright` 의 근거다.

## 이력

| 날짜 | 일 | 원인 | 조치 |
|---|---|---|---|
| 2026-08-25 | 최초 등록(크롤러 25) | 상세 URL 없이 등록해 상세 셀렉터가 확인되지 않았다 | 판정이 찾은 상세 주소로 상세 셀렉터까지 만들게 했다 |
| 2026-08-25 | 재등록(크롤러 30) | | 목록 11건, 상세 3건 성공, 실패 0건 (run 303) |

## 칸 매핑 (2026-08-26, 본문 나누기 Push 2)

`crawlers` 30번 행의 설정에서 그대로 옮겼다. 같은 값이
`seeds/site-configs-20260826.json` 에 있고 `tests/test_split_body_mapping.py` 가 픽스처에
돌려 본다. 문서와 저장된 설정이 갈리지 않는지는 `tests/test_site_recipe_mapping.py` 가 본다.

목록은 API, 상세는 렌더다. 상세 문서는 본문이 '◆ 업무내용' 처럼 한 덩어리라 갈라낼 수 없고, 같은 값이 목록 API 에 항목마다 별도 필드로 있다. 그래서
직군·모집인원·주요 업무·자격요건·전형절차·근로제도를 목록에서 읽어 나른다. 상세 문서가 주는 회사·직원유형·근무지·영입마감일은 이름표(dt)로 읽는다.
start_date 는 공고 등록일(regDate)이다 — 사이트가 모집 시작일을 따로 적지 않는다.

| 칸 | 어디서 | 자리 |
|---|---|---|
| 제목 | 상세 HTML | `.tit_jobs` |
| 본문 원문 | 상세 HTML | `.cont_board` |
| 필수 조건 | 목록 API | `qualification` |
| 모집 마감일 | 상세 HTML | `.list_info dt:-soup-contains("영입마감일") + dd` |
| 조직·부서 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 모집 기업 | 상세 HTML | `.list_info dt:-soup-contains("회사정보") + dd` |
| 모집 시작일 | 목록 API | `regDate` |
| 직군 | 목록 API | `jobPartName` |
| 고용형태 | 상세 HTML | `.list_info dt:-soup-contains("직원유형") + dd` |
| 경력 구분 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 근무지 | 상세 HTML | `.list_info dt:-soup-contains("근무지 정보") + dd` |
| 모집인원 | 목록 API | `displayRecruitCount` |
| 주요 업무 | 목록 API | `workContentDesc` |
| 우대 조건 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 전형 절차 | 목록 API | `jobOfferProcessDesc` |
| 기타 | 목록 API | `workTypeDesc` |

빈 칸은 그 사이트가 그 값을 따로 주지 않는다는 사실이다. 다른 값으로 채우지 않는다 —
한화 `department` 에 근무지가 들어가 있던 것이 그렇게 생긴 버그다.
