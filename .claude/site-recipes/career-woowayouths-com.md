# 우아한형제들 (career.woowayouths.com)

- 리스트 URL: https://career.woowayouths.com/recruitment/
- 수집 방식: 목록은 `api`, 상세는 `playwright` (크롤러 29, 2026-08-25 등록)
- 목록 API:
  `GET https://career.woowayouths.com/w1/recruits?category=jobGroupCodes%3ABA005010&recruitCampaignSeq=0&jobGroupCodes=BA005010&page=0&size=21&sort=updateDate%2Cdesc`
  - `items_path` 는 `data.list`, 제목은 `recruitName`, id 는 `recruitNumber`(`R2607031`)
  - 헤더 없이 공용 fetch 클라이언트로 200 이다. `referer` 도 필요 없었다
- 상세 URL 형식: `https://career.woowayouths.com/recruitment/<공고번호>/detail?category=jobGroupCodes%3ABA005010`
- 페이지네이션: 없음. 이 크롤러는 목록 API 를 관찰된 그대로(한 쪽, `size=21`) 저장했고
  2026-08-25 에 8건이 왔다. 직군을 바꾸려면 `jobGroupCodes` 를 다른 값으로 등록한다
- 날짜 포맷: 목록 `div.flag-type` 이 `기간제 영입 종료시` 처럼 낱말이라 날짜가 아니다.
  마감일은 상세의 같은 자리에서 온다
- robots.txt: 공용 fetch 클라이언트의 robots 확인을 통과했다
- 권장 주기: 미승격. 워크플로우로 올릴 때 정한다

## 상세는 브라우저가 있어야 한다

목록 항목의 `a.title` 에 상세 주소가 그대로 있지만, 그 주소를 정적으로 열면 제목이 없다.
2026-08-25 등록에서 확인했고 그래서 `detail_mode` 가 `playwright` 다. 목록은 API 라 실행마다
브라우저가 뜨는 것은 상세 때문이다.

## 항목 하나가 제목이 없다

`ul.recruit-type-list > li` 가 9건 잡히는데 그중 8건만 제목이 있다. 등록이 제목이 있는 것만
남기는 `:has()` 로 좁혔다.

```
.recruit-type-list > li:has(a.title p.fr-view)
```

좁힐 때 항목 안의 `link`·`date` 셀렉터가 살아 있는지 함께 본다 — `div.title-wrap` 처럼 더
안쪽으로 좁히면 `a.title` 이 항목 밖으로 나가 링크가 끊긴다 (`app/selector/narrow.py`).

## 이력

| 날짜 | 일 | 원인 | 조치 |
|---|---|---|---|
| 2026-08-25 | 최초 등록(크롤러 24) | 상세 URL 없이 등록해 상세 셀렉터가 확인되지 않았다 | 판정이 찾은 상세 주소로 상세 셀렉터까지 만들게 했다 |
| 2026-08-25 | 재등록(크롤러 29) | | 목록 8건, 상세 3건 성공, 실패 0건 (run 302) |

## 칸 매핑 (2026-08-26, 본문 나누기 Push 2)

`crawlers` 29번 행의 설정에서 그대로 옮겼다. 같은 값이
`seeds/site-configs-20260826.json` 에 있고 `tests/test_split_body_mapping.py` 가 픽스처에
돌려 본다. 문서와 저장된 설정이 갈리지 않는지는 `tests/test_site_recipe_mapping.py` 가 본다.

목록은 API, 상세는 렌더다. 목록 응답의 careerType·jobGroup·employmentType 은 코드만 있고 표시할 이름이 없어 읽지 않는다. 같은
값이 상세 문서에 이름표(.flag-career/.flag-type/.flag-tag)로 있어 그쪽에서 읽는다. 마감일이 .flag-type 전체를 잡아 '기간제
영입 종료시' 로 들어오고 있었다 — 두 번째 span 만 읽는다.

| 칸 | 어디서 | 자리 |
|---|---|---|
| 제목 | 상세 HTML | `.recruit-detail-title-inner .title` |
| 본문 원문 | 상세 HTML | `.detail-view` |
| 필수 조건 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 모집 마감일 | 상세 HTML | `.flag-type span:nth-of-type(2)` |
| 조직·부서 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 모집 기업 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 모집 시작일 | 목록 API | `recruitOpenDate` |
| 직군 | 상세 HTML | `.flag-tag button` |
| 고용형태 | 상세 HTML | `.flag-type span:nth-of-type(1)` |
| 경력 구분 | 상세 HTML | `.flag-career` |
| 근무지 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 모집인원 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 주요 업무 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 우대 조건 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 전형 절차 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 기타 | 비움 | 사이트가 이 값을 따로 주지 않는다 |

빈 칸은 그 사이트가 그 값을 따로 주지 않는다는 사실이다. 다른 값으로 채우지 않는다 —
한화 `department` 에 근무지가 들어가 있던 것이 그렇게 생긴 버그다.
