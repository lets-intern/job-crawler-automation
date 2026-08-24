# 삼성 (www.samsungcareers.com)

- 리스트 URL: https://www.samsungcareers.com/hr/
- 렌더링: 목록이 `POST /hr/list.data` 로 채워진다. 정적 응답에는 항목이 없다
- 항목 셀렉터: `#list > li` (2026-08-25 기준 9건)
- 계열사: 한 사이트에 여럿이다 — 삼성전자 DX부문/DS부문, 삼성디스플레이, 삼성SDI, 삼성전기,
  삼성SDS, 삼성바이오로직스, 삼성바이오에피스, 삼성중공업

## 클릭하면 모달이 열린다. 주소는 바뀌지 않는다

이것이 이 사이트의 핵심이다. 항목 안 `a` 의 `href` 는 `/#none` 이고 클릭해도 주소가 그대로다.
**주소만 보고 판정하면 실패로 읽힌다.**

실제로는 모달이 열린다. 2026-08-25 측정에서 본문이 1,620자에서 9,798자로 늘었고, 그때 요청이
나갔다.

```
GET https://www.samsungcareers.com/recruit/detail.data?seqno=22878&strCode=
```

`22878` 은 항목의 `a[data-value="22,878"]` 에서 쉼표를 뺀 값이다.

## 두 요청 다 브라우저 없이 된다

목록:

```
POST https://www.samsungcareers.com/hr/list.data
  content-type: application/x-www-form-urlencoded;charset=utf-8
  referer: https://www.samsungcareers.com/hr/
  body currentPageNo=1&intNo=0&strVal=&strTxt=&strKey=&strCompany=&strType=&strOrderBy=&strEntity=
```

HTML 조각 17,935바이트를 돌려준다. JSON 이 아니다. 파라미터가 하나라도 빠지면 500 이 온다 —
`strOrderBy` 와 `strEntity` 를 빼고 불렀다가 `{"code":500}` 을 받았다.

상세:

```
GET https://www.samsungcareers.com/recruit/detail.data?seqno=<번호>&strCode=
```

39,490바이트 JSON, `data.result` 에 필드 41개다. `title`, `startdate`(`202608201000`),
`enddate`, `introKr`, `introEn`, `compCd`, `email` 등이 들어 있다.

## 이력

| 날짜 | 일 | 결과 |
|---|---|---|
| 2026-08-24 | 항목 컨테이너 클릭 | 이동하지 않음. 이때는 실패로 판정했다 |
| 2026-08-25 | 목록이 뜬 것을 확인하고 다시 클릭 | 모달이 열리고 `detail.data` 요청이 나갔다 |
| 2026-08-25 | 두 요청을 `curl` 로 직접 호출 | 둘 다 200 |

목록이 늦게 채워져 항목 0건인 채로 클릭한 회차가 있었다. **항목이 실제로 잡힌 뒤에 클릭해야
한다.**
