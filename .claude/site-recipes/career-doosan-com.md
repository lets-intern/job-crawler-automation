# 두산 (career.doosan.com)

- 리스트 URL: https://career.doosan.com/dsp/sa/RecList.jsp
- 수집 방식: 목록·상세 둘 다 `static` (크롤러 31, 2026-08-25 등록). 브라우저를 띄우지 않는다
- 상세 URL 형식: 목록과 **같은 주소**에 쿼리를 붙인 것이다.
  `RecList.jsp?REC_ID=<공고번호>&REC_TYPE_CD=...&REC_MGT_CD=...&q_COMP_CD=...&mode=goDetail`
- 페이지네이션: 없음. 한 쪽에 30건이 다 온다 (2026-08-25 측정)
- 날짜 포맷: 목록 `div.deadline` 이 `D-6 2026-07-15 ~ 2026-08-31` 처럼 남은 일수와 기간을
  한 덩어리로 담고 있다. 상세에 마감일 셀렉터가 따로 있어 목록 날짜는 마감일로 쓰이지 않는다
- robots.txt: 공용 fetch 클라이언트의 robots 확인을 통과했다
- 권장 주기: 미승격. 워크플로우로 올릴 때 정한다

## 항목에 `href` 가 없다. 상세는 폼 POST 다

이 사이트의 핵심이다. 항목의 링크는 이렇게 생겼다.

```html
<a class="list-tit" href="javascript:void(0);"
   onclick="goDetail('1000361539', 'C_REC_MGT_04', 'C_REC_TYPE_02', '08000002');">
```

`goDetail()` 은 폼에 값을 넣고 **같은 주소로 POST** 한다. 그래서 클릭해도 주소가 바뀌지 않고,
주소만 보면 상세에 못 간 것으로 읽힌다.

등록할 때의 판정이 그 POST 를 관찰해 같은 값을 쿼리로 붙인 GET 주소를 만들고, 공고 두 건을
실제로 열어 제목이 있는지 확인한 뒤에 `list.link_template` 으로 저장했다
(`app/selector/link_probe.py`). 자리표시자 넷이 전부 같은 `onclick` 의 인자다.

```
{onclick|arg1}  REC_ID        1000361539
{onclick|arg2}  REC_MGT_CD    C_REC_MGT_04
{onclick|arg3}  REC_TYPE_CD   C_REC_TYPE_02
{onclick|arg4}  q_COMP_CD     08000002
```

**GET 으로도 같은 문서가 온다.** 2026-08-25 에 확인했다(54,177바이트, 공고 제목 포함). 사이트가
POST 만 받게 바뀌면 여기가 먼저 깨진다.

## 셀렉터 특이사항

항목은 `ul.list-cont > li` 30건이다. 항목 안에 지원 버튼이 하나 더 있고 그 버튼도 같은
`goDetail()` 인자를 갖고 있어, 주소 형식의 출처로 둘 중 어느 것을 골라도 결과가 같다.

회사명이 `div.company` 에 계열사 이름으로 온다 (두산매거진, 두산에너빌리티 등). 운영자가 적는
`default_company` 는 비워 둔다.

## 이력

| 날짜 | 일 | 원인 | 조치 |
|---|---|---|---|
| 2026-08-25 | 최초 등록(크롤러 20, 22) | 상세 경로를 못 찾았다 | `onclick` 인자를 읽는 주소 형식을 판정에 넣었다 |
| 2026-08-25 | 재등록(크롤러 31) | | 목록 30건, 상세 3건 성공, 실패 0건 (run 301) |

## 칸 매핑 (2026-08-26, 본문 나누기 Push 2)

`crawlers` 31번 행의 설정에서 그대로 옮겼다. 같은 값이
`seeds/site-configs-20260826.json` 에 있고 `tests/test_split_body_mapping.py` 가 픽스처에
돌려 본다. 문서와 저장된 설정이 갈리지 않는지는 `tests/test_site_recipe_mapping.py` 가 본다.

정적 HTML 이다. 마감일이 tbody > tr:nth-child(4) > td 를 보고 있어 '지원자 개별일정' 을 마감일로 읽고 있었다 — 이름표(th)로
바꿨다. 자회사/BG 가 계열사라 company 로 가고 department 는 비운다. 본문을 div.content 로 넓혔다. dt/dd 와 표가 서로 다른
블록이라 좁게 잡으면 접수방법·문의처·일정이 통째로 사라진다. 끝에 이전글/다음글이 딸려 온다.

| 칸 | 어디서 | 자리 |
|---|---|---|
| 제목 | 상세 HTML | `h2.h2-title` |
| 본문 원문 | 상세 HTML | `div.content` |
| 필수 조건 | 상세 HTML | `th:-soup-contains("자격요건") + td` |
| 모집 마감일 | 상세 HTML | `th:-soup-contains("채용공고") + td` |
| 조직·부서 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 모집 기업 | 상세 HTML | `dt:-soup-contains("자회사/BG") + dd` |
| 모집 시작일 | 상세 HTML | `th:-soup-contains("채용공고") + td` |
| 직군 | 상세 HTML | `dt:-soup-contains("모집분야") + dd` |
| 고용형태 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 경력 구분 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 근무지 | 상세 HTML | `dt:-soup-contains("지역") + dd` |
| 모집인원 | 상세 HTML | `dt:-soup-contains("인원") + dd` |
| 주요 업무 | 상세 HTML | `dt:-soup-contains("수행업무") + dd` |
| 우대 조건 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 전형 절차 | 상세 HTML | `th:-soup-contains("전형절차") + td` |
| 기타 | 상세 HTML | `th:-soup-contains("기타사항") + td` |

빈 칸은 그 사이트가 그 값을 따로 주지 않는다는 사실이다. 다른 값으로 채우지 않는다 —
한화 `department` 에 근무지가 들어가 있던 것이 그렇게 생긴 버그다.
