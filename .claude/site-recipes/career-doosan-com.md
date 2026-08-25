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
