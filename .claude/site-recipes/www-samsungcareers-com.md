# 삼성 (www.samsungcareers.com)

- 리스트 URL: https://www.samsungcareers.com/hr/
- 수집 방식: 목록·상세 둘 다 `api` (2026-08-25 전환). 브라우저를 띄우지 않는다. 목록만
  응답이 JSON 이 아니라 HTML 조각이라 CSS 셀렉터로 읽는다
- 페이지네이션: `currentPageNo` 를 1부터 올린다. 총 수와 쪽 수가 응답 안
  `<input class="divCnt" data-value="16" data-max="2">` 에 있다. 2026-08-25 에 9+7 = 16건
- 날짜 포맷: 목록의 `span.period` 가 `2026.08.20 ~ 2026.09.02` 인 기간이다. `deadline` 규칙이
  `~` 앞을 떼고 뒤쪽만 남긴다. 상세의 `enddate` 는 `202609021700` 이라 쓰지 않는다
- robots.txt: 공용 fetch 클라이언트의 robots 확인을 통과했다
- 권장 주기: 30분으로 등록돼 있다 (workflow 3)
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

## 2026-08-25: 등록 경로를 API 로 바꿨다

목록은 폼 본문으로 물어보고 HTML 조각을 받는다. 그 조각을 CSS 셀렉터로 읽는 설정이
`crawlers.api_config_json` 에 들어간다 — `items_path` 가 항목 셀렉터, `fields` 가 항목 안의
셀렉터, `id_field` 가 `<셀렉터>@<속성>` 이다 (`seeds/site-configs-20260826.json`).

**공고 번호는 `a[data-value]` 에서 천 단위 쉼표를 뺀 값이다.** `id_field` 끝에 `|digits` 를
붙여 숫자만 남긴다. 숫자 표기에 기대는 자리이므로 사이트가 표기를 바꾸면 여기가 먼저 깨진다.
쉼표를 그대로 두면 주소에서 `%2C` 로 인코딩돼 상세가 열리지 않는다.

**사람이 볼 상세 주소가 이 사이트에는 없다.** 클릭해도 주소가 바뀌지 않고 모달이 열린다.
그래서 `raw_jobs.source_url` 에 `detail.data` 주소가 그대로 들어간다 — 공고마다 다르고 실제로
그 공고를 돌려주는 유일한 주소다. 소비 측에 사람용 주소를 줘야 한다면 이 자리가 먼저 걸린다.

본문은 `data.items` 의 모집 직무마다 있는 `titleKr`·`taskKr` 을 모은다. 2026-08-25 에 받은
공고 하나에 직무가 12개였다. 자격요건은 같은 배열의 `qlfctKr`(필수)과 `favorKr`(우대)이다.

첫 실행(run 249)은 54초에 16건을 적재했고 실패 0건, 본문이 빈 행 0건이다. 계열사 12곳이
`p.company` 에서 온다 — 삼성전자 DX/DS, 삼성디스플레이, 삼성SDI, 삼성전기, 삼성SDS,
삼성바이오로직스, 삼성바이오에피스, 삼성중공업, 삼성E&A, 삼성물산 건설부문, 삼성물산 상사부문.

## 칸 매핑 (2026-08-26, 본문 나누기 Push 2)

`crawlers` 14번 행의 설정에서 그대로 옮겼다. 같은 값이
`seeds/site-configs-20260826.json` 에 있고 `tests/test_split_body_mapping.py` 가 픽스처에
돌려 본다. 문서와 저장된 설정이 갈리지 않는지는 `tests/test_site_recipe_mapping.py` 가 본다.

목록은 폼으로 물어보고 HTML 조각으로 온다. 공고 번호는 a[data-value] 에서 천 단위 쉼표를 뺀 값이다. 마감일은 목록의 기간(시작 ~ 마감)에서
온다. 자격요건이 공고 전체(result.qlfctKr)와 직무별(items.*.qlfctKr) 둘로 나뉘어 있어 둘 다 읽는다. 조직 소개(introKr)는 본문에
넣었다 — 세 곳만 주는 값이라 칸을 만들지 않았다.

| 칸 | 어디서 | 자리 |
|---|---|---|
| 제목 | 상세 API | `data.result.title` |
| 본문 원문 | 상세 API | `data.result.introKr`<br>`data.items.*.titleKr`<br>`data.items.*.taskKr` |
| 필수 조건 | 상세 API | `data.result.qlfctKr`<br>`data.items.*.qlfctKr` |
| 모집 마감일 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 조직·부서 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 모집 기업 | 상세 API | `data.result.cmpNameKr` |
| 모집 시작일 | 상세 API | `data.result.startdate` |
| 직군 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 고용형태 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 경력 구분 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 근무지 | 상세 API | `data.items.*.workPlaceKr` |
| 모집인원 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 주요 업무 | 상세 API | `data.items.*.taskKr` |
| 우대 조건 | 상세 API | `data.items.*.favorKr` |
| 전형 절차 | 비움 | 사이트가 이 값을 따로 주지 않는다 |
| 기타 | 상세 API | `data.result.etcKr`<br>`data.result.processKr`<br>`data.result.docInfoKr`<br>`data.result.attachmentKr`<br>`data.items.*.memoKr`<br>`data.addFiles.*.titleKr`<br>`data.addFiles.*.fileOriginalName`<br>`data.result.mainTel`<br>`data.result.email` |

빈 칸은 그 사이트가 그 값을 따로 주지 않는다는 사실이다. 다른 값으로 채우지 않는다 —
한화 `department` 에 근무지가 들어가 있던 것이 그렇게 생긴 버그다.
