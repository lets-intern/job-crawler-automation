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

## 칸 매핑 (2026-08-26, 수집은 여섯 칸)

**이 사이트는 여섯 칸만 수집한다** — 제목·본문·모집 마감일·모집 시작일·모집 기업, 그리고 원본 주소. 나머지 열한 칸(직군·근무지·경력 구분·고용형태·모집인원·주요 업무·우대사항·전형 절차·자격요건·조직 부서·기타)은 본문을 읽어 나눈다.

`crawlers` 15번 행의 설정에서 그대로 옮겼다. 같은 값이 `seeds/site-configs-20260826.json` 에 있고 `tests/test_split_body_mapping.py` 가 픽스처에 돌려 본다. 문서와 저장된 설정이 갈리지 않는지는 `tests/test_site_recipe_mapping.py` 가 본다.

| 칸 | 어디서 | 자리 |
|---|---|---|
| 제목 | 상세 셀렉터 | `.box-title` |
| 본문 | 상세 셀렉터 | `.detail-content-wrapper` |
| 모집 마감일 | 상세 셀렉터 | `.box-detail-item:has(.label:-soup-contains("지원 기간")) .value` |
| 모집 시작일 | 상세 셀렉터 | `.box-detail-item:has(.label:-soup-contains("지원 기간")) .value` |
| 모집 기업 | 상세 셀렉터 | `.box-detail-item:has(.label:-soup-contains("회사")) .value` |

여기 없는 칸은 이 사이트가 그 값을 주지 않는다는 사실이다. 다른 값으로 채우지 않는다.

2026-08-26 이전에는 이 표에 열여섯 칸이 있었다. 그 매핑을 뺀 이유는 `seeds/site-configs-20260826.json` 의 `why_the_mappings_were_removed` 에 있다 — 사이트 11곳 x 칸 16개 = 176번의 판단이 640건에서 절반도 채우지 못했고, 그중 다섯 곳이 뜻이 다른 칸에 값을 넣고 있었다.
