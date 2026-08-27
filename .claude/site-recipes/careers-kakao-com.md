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

## 칸 매핑 (2026-08-26, 수집은 여섯 칸)

**이 사이트는 여섯 칸만 수집한다** — 제목·본문·모집 마감일·모집 시작일·모집 기업, 그리고 원본 주소. 나머지 열한 칸(직군·근무지·경력 구분·고용형태·모집인원·주요 업무·우대사항·전형 절차·자격요건·조직 부서·기타)은 본문을 읽어 나눈다.

`crawlers` 30번 행의 설정에서 그대로 옮겼다. 같은 값이 `seeds/site-configs-20260826.json` 에 있고 `tests/test_split_body_mapping.py` 가 픽스처에 돌려 본다. 문서와 저장된 설정이 갈리지 않는지는 `tests/test_site_recipe_mapping.py` 가 본다.

| 칸 | 어디서 | 자리 |
|---|---|---|
| 제목 | 상세 셀렉터 | `.tit_jobs` |
| 본문 | 상세 셀렉터 | `.cont_board` |
| 모집 마감일 | 상세 셀렉터 | `.list_info dt:-soup-contains("영입마감일") + dd` |
| 모집 시작일 | 목록 API | `regDate` |
| 모집 기업 | 상세 셀렉터 | `.list_info dt:-soup-contains("회사정보") + dd` |

여기 없는 칸은 이 사이트가 그 값을 주지 않는다는 사실이다. 다른 값으로 채우지 않는다.

2026-08-26 이전에는 이 표에 열여섯 칸이 있었다. 그 매핑을 뺀 이유는 `seeds/site-configs-20260826.json` 의 `why_the_mappings_were_removed` 에 있다 — 사이트 11곳 x 칸 16개 = 176번의 판단이 640건에서 절반도 채우지 못했고, 그중 다섯 곳이 뜻이 다른 칸에 값을 넣고 있었다.
