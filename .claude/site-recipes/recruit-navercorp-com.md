# 네이버 (recruit.navercorp.com)

- 리스트 URL: https://recruit.navercorp.com/rcrt/list.do
- 수집 방식: 목록·상세 둘 다 `static` (크롤러 32, 2026-08-25 등록). 브라우저를 띄우지 않는다
- 상세 URL 형식: `rcrt/view.do?annoId=<공고번호>&sw=&subJobCdArr=&sysCompanyCdArr=&empTypeCdArr=&entTypeCdArr=&workAreaCdArr=`
- 페이지네이션: 첫 화면에 10건이다. 그 아래는 무한 스크롤이 `/rcrt/loadJobList.do` 를 불러
  채운다 — **등록된 크롤러는 첫 10건만 가져온다.** 그 API 는 스크롤해야 나가므로 렌더 중에
  관찰되지 않았다
- 날짜 포맷: 목록에는 모집 기간이 `dd.info_text` 다섯 개 중 마지막에 `2026.08.12 ~ 2026.08.25`
  로 있다. 클래스가 다 같아 모델이 두 번 다 `list.date` 를 비웠고, 비운 채로 저장했다
- robots.txt: 공용 fetch 클라이언트의 robots 확인을 통과했다
- 권장 주기: 미승격. 워크플로우로 올릴 때 정한다

## 항목 셀렉터에 함정이 있다

`li.item` 이 144건 잡히는데 그중 공고는 0건이다. 필터와 네비게이션이 같은 클래스를 쓴다.
실제 공고는 `li.card_item` (= `ul.card_list > li`) 10건이다.

2026-08-25 생성에서 모델은 `.card_item` 을 골랐다. 넓은 쪽을 골랐더라도 등록이 제목이 있는
반복 요소로 좁힌다 (`app/selector/narrow.py`) — 그 판정을 픽스처로 고정해 뒀다
(`tests/test_item_narrow.py`).

## 항목에 `href` 가 없다. 클릭하면 GET 으로 이동한다

```html
<a class="card_link" href="#n" onclick="show('30005276')">
```

`show()` 는 폼을 GET 으로 보내고 주소가 `view.do?annoId=30005276&...` 로 바뀐다. 등록할 때의
판정이 그 주소에서 `30005276` 이 항목의 `onclick` 첫 인자와 같다는 것을 보고
`view.do?annoId={onclick|arg1}&...` 형식을 만들었다. 공고 두 건을 실제로 열어 제목을 확인한
뒤에 저장했다.

**공유 버튼을 값의 출처로 쓰지 않는다.** 항목 안 `a.social.*` 의 `href` 가
`javascript:share('blog','30005276','제목')` 이라 같은 번호를 갖고 있지만, 그것으로 주소를
만들면 공유 링크의 다른 인자까지 끌려 들어온다.

## 이력

| 날짜 | 일 | 원인 | 조치 |
|---|---|---|---|
| 2026-08-25 | 최초 등록(크롤러 23) | `list.date` 가 빈 채로 저장돼 파서가 `select("")` 에서 문법 오류를 냈고 항목 10건이 0건으로 읽혔다 | 빈 셀렉터를 빈 값으로 읽게 고쳤다 (`app/crawler/parser.py`) |
| 2026-08-25 | 재등록(크롤러 28) | 목록이 렌더로 판정됐다 | 주소 형식을 알아낸 뒤 정적으로도 읽히면 정적으로 두게 했다 |
| 2026-08-25 | 재등록(크롤러 32) | | 목록 10건, 상세 3건 성공, 실패 0건 (run 304) |

## 칸 매핑 (2026-08-26, 본문 나누기 Push 2)

`crawlers` 32번 행의 설정에서 그대로 옮겼다. 같은 값이
`seeds/site-configs-20260826.json` 에 있고 `tests/test_split_body_mapping.py` 가 픽스처에
돌려 본다. 문서와 저장된 설정이 갈리지 않는지는 `tests/test_site_recipe_mapping.py` 가 본다.

정적 HTML 이다. 모집 부서가 'NAVER' 즉 계열사라 company 로 가고 department 는 비운다. 마감일이 지금까지 비어 있었는데 모집
기간(dd)에서 읽는다. 모집 분야 dd 가 둘인데 첫 번째만 읽힌다.

| 칸 | 어디서 | 자리 |
|---|---|---|
| 제목 | 상세 HTML | `h4.card_title` |
| 본문 원문 | 상세 HTML | `.detail_wrap` |
| 필수 조건 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 모집 마감일 | 상세 HTML | `.card_info dt:-soup-contains("모집 기간") + dd` |
| 조직·부서 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 모집 기업 | 상세 HTML | `.card_info dt:-soup-contains("모집 부서") + dd` |
| 모집 시작일 | 상세 HTML | `.card_info dt:-soup-contains("모집 기간") + dd` |
| 직군 | 상세 HTML | `.card_info dt:-soup-contains("모집 분야") + dd` |
| 고용형태 | 상세 HTML | `.card_info dt:-soup-contains("근로 조건") + dd` |
| 경력 구분 | 상세 HTML | `.card_info dt:-soup-contains("모집 경력") + dd` |
| 근무지 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 모집인원 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 주요 업무 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 우대 조건 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 전형 절차 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 기타 | 비움 | 사이트가 이 값을 따로 주지 않는다 |

빈 칸은 그 사이트가 그 값을 따로 주지 않는다는 사실이다. 다른 값으로 채우지 않는다 —
한화 `department` 에 근무지가 들어가 있던 것이 그렇게 생긴 버그다.
