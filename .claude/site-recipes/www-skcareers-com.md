# SK (www.skcareers.com)

- 리스트 URL: https://www.skcareers.com/Recruit
- 상세 URL 패턴: `/Recruit/Detail/<공고ID>`. 공고ID 는 목록 API 의 `noticeID` 다 (`R261752`)
- 수집 방식: 목록은 `api`, 상세는 `static` (2026-08-25 전환). 브라우저를 띄우지 않는다
- 페이지네이션: 없다. 목록 API 한 번에 전부 온다 (2026-08-25 확인, `totalCount` 104건)
- 날짜 포맷: 영어 월 이름이다. 목록의 `end` 가 `August 25, 2026(Tue)`, 상세는
  `August 11, 2026(Tue)~August 25, 2026(Tue)` 인 기간이다. `deadline` 규칙이 `~` 앞을 떼고
  요일 표기를 뗀 뒤 `%B %d, %Y` 로 읽는다
- robots.txt: 공용 fetch 클라이언트의 robots 확인을 통과했다
- 권장 주기: 30분으로 등록돼 있다 (workflow 4)

## 목록은 폼으로 물어본다

```
POST https://www.skcareers.com/Recruit/GetRecruitList
  content-type: application/x-www-form-urlencoded
  body sort=2&searchText=&corpCode=&jobRole=0&recruitType=&workingType=&workingRegion=
  -> totalCount 와 list. 항목마다 noticeID / title / corpName / start / end
```

JSON 본문으로 보내면 답하지 않는다. 요청 전문은 `seeds/site-configs-20260826.json` 의 SK
항목에 있고 DB 가 진실이다.

## 상세는 서버가 그린 HTML 이다

목록만 API 이고 상세는 `static` 이다. 항목의 `noticeID` 로 만든 주소를 그대로 따라가면
서버가 완성된 HTML 을 준다 (2026-08-25 픽스처 기준 텍스트 4,496자). 상세 셀렉터는 DB 에 있고
`tests/test_site_configs.py` 가 같은 픽스처에 돌려 본다.

계열사는 상세의 회사명 자리에서 온다. `default_company` 에 `SK` 가 적혀 있지만 상세 값이
있으면 그쪽이 이긴다.

## 한 번에 104건이라 실행이 길다

2026-08-25 실행(run 252)은 4분 13초가 걸렸다. 목록 104건 중 이미 아는 공고 20건과 마감이 지난
1건을 상세 없이 넘기고, 83건의 상세를 가져왔다. 호스트 딜레이가 요청마다 붙으므로 신규가 많은
날은 이보다 길어진다. 실행 시간 제한은 600초다 (`RUN_TIMEOUT_SECONDS`).

`list.date_is_deadline` 을 참으로 적었다. 목록의 `end` 가 그 공고의 마감일이다.

## 이력

| 날짜 | 일 | 원인 | 조치 |
|---|---|---|---|
| 2026-08-23 | 마감일이 정규화에서 통째로 빠짐 | `date_parse` 가 한국식 형식만 시도했다 | `%B %d, %Y` 를 규칙에 더하고 재정규화 (`seeds/snapshot/README.md`) |
| 2026-08-25 | 목록을 렌더에서 API 로 전환 | 목록 API 가 104건을 한 번에 준다. 렌더 경로는 20건만 보고 있었다 | 수동 실행 1회(run 252)에서 83건 적재, 실패 0건 |

## 칸 매핑 (2026-08-26, 본문 나누기 Push 2)

`crawlers` 15번 행의 설정에서 그대로 옮겼다. 같은 값이
`seeds/site-configs-20260826.json` 에 있고 `tests/test_split_body_mapping.py` 가 픽스처에
돌려 본다. 문서와 저장된 설정이 갈리지 않는지는 `tests/test_site_recipe_mapping.py` 가 본다.

목록은 폼으로 물어보고 104건이 한 번에 온다. 상세는 서버가 그린 HTML 이라 셀렉터로 읽는다. 값 상자는 자리(nth-child)가 아니라
이름표(.label)로 찾는다 — 자리로 잡으면 상자 순서가 바뀔 때 조용히 다른 값이 들어온다. 그 버그로 직무가 department 에 들어가 있었다. 마감
시간(23:59)은 지원 기간과 다른 상자라 지금 어느 칸에도 안 들어간다.

| 칸 | 어디서 | 자리 |
|---|---|---|
| 제목 | 상세 HTML | `.box-title` |
| 본문 원문 | 상세 HTML | `.detail-content-wrapper` |
| 필수 조건 | 상세 HTML | `.detail-content-item:has(.detail-content-title:-soup-contains("Looking For")) .detail-content-box` |
| 모집 마감일 | 상세 HTML | `.box-detail-item:has(.label:-soup-contains("지원 기간")) .value` |
| 조직·부서 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 모집 기업 | 상세 HTML | `.box-detail-item:has(.label:-soup-contains("회사")) .value` |
| 모집 시작일 | 상세 HTML | `.box-detail-item:has(.label:-soup-contains("지원 기간")) .value` |
| 직군 | 상세 HTML | `.box-detail-item:has(.label:-soup-contains("직무")) .value` |
| 고용형태 | 상세 HTML | `.box-detail-item:has(.label:-soup-contains("유형")) .value` |
| 경력 구분 | 상세 HTML | `.box-detail-item:has(.label:-soup-contains("구분")) .value` |
| 근무지 | 상세 HTML | `.box-detail-item:has(.label:-soup-contains("지역")) .value` |
| 모집인원 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 주요 업무 | 상세 HTML | `.detail-content-item:has(.detail-content-title:-soup-contains("About the job")) .detail-content-box` |
| 우대 조건 | 상세 HTML | `.detail-content-item:has(.detail-content-title:-soup-contains("Preferred")) .detail-content-box` |
| 전형 절차 | 상세 HTML | `.detail-content-item:has(.detail-content-title:-soup-contains("Recruiting Process")) .detail-content-box` |
| 기타 | 상세 HTML | `.detail-content-item:has(.detail-content-title:-soup-contains("Please Read")) .detail-content-box` |

빈 칸은 그 사이트가 그 값을 따로 주지 않는다는 사실이다. 다른 값으로 채우지 않는다 —
한화 `department` 에 근무지가 들어가 있던 것이 그렇게 생긴 버그다.
